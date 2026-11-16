"""Small formal-API operator for synthetic OFFLINE_ONLY / CONTRACT_TEST_ONLY checks.

No task dataset, Oracle, provider key, retry, approval loop or Recover is imported.
The entry point runs a fixed pytest selection under its offline network/key boundary.
"""

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class Operator:
    """Each call performs one operator action; inspect/events only issue GETs.

    Use inside the repository's offline pytest boundary with its authenticated
    ASGI client and explicitly installed SDK MockTransport models.
    """

    def __init__(self, client, auth):
        self.client, self.auth = client, auth

    async def _request(self, method, path, payload=None):
        response = await self.client.request(
            method, path, headers=self.auth, json=payload
        )
        response.raise_for_status()
        return response.json()

    async def create_thread(self, mode="multi"):
        return (await self._request("POST", "/api/v1/agent/threads", {"mode": mode}))[
            "id"
        ]

    async def start(self, thread_id, request_id, message):
        return await self._request(
            "POST",
            f"/api/v1/agent/threads/{thread_id}/runs",
            {"request_id": request_id, "message": message},
        )

    async def inspect(self, thread_id, run_id):
        thread = await self._request("GET", f"/api/v1/agent/threads/{thread_id}")
        run = next((run for run in thread["runs"] if run["id"] == run_id), None)
        if run is None:
            raise ValueError("RUN_NOT_IN_THREAD")
        pending = run.get("pending_confirmation") or {}
        proposal = None
        if pending.get("proposal_id"):
            proposal = await self._request(
                "GET", f"/api/v1/proposals/{pending['proposal_id']}"
            )
        return {"run": run, "proposal": proposal}

    async def decide(self, inspection, *, decision):
        if decision not in {"approve", "reject"}:
            raise ValueError("EXPLICIT_DECISION_REQUIRED")
        pending = inspection["run"].get("pending_confirmation") or {}
        if not pending.get("proposal_id") or inspection["proposal"] is None:
            raise ValueError("INSPECT_PROPOSAL_FIRST")
        return await self._request(
            "POST",
            f"/api/v1/proposals/{pending['proposal_id']}/confirmations",
            {"decision": decision},
        )

    async def resume(self, thread_id, inspection, confirmation_id, request_id):
        run = inspection["run"]
        pending = run["pending_confirmation"]
        return await self._request(
            "POST",
            f"/api/v1/agent/threads/{thread_id}/resume",
            {
                "request_id": request_id,
                "run_id": run["id"],
                "interrupt_id": pending["interrupt_id"],
                "proposal_id": pending["proposal_id"],
                "confirmation_id": confirmation_id,
            },
        )

    async def events(self, run_id):
        items, after = [], 0
        for _ in range(100):
            page = await self._request(
                "GET", f"/api/v1/agent/runs/{run_id}/events?after_seq={after}&limit=100"
            )
            items.extend(page["items"])
            if len(page["items"]) < 100:
                return items
            if page["next_seq"] <= after:
                break
            after = page["next_seq"]
        raise ValueError("INCOMPLETE_EVENT_EVIDENCE")


@dataclass(frozen=True)
class FrozenEvidence:
    """Local immutable bytes; a hash binds observations but is not authentication."""

    payload: bytes
    sha256: str


def freeze(scenario_id, run, events):
    """Copy API observations to canonical bytes before calling the contract scorer."""
    payload = json.dumps(
        {
            "scenario_id": scenario_id,
            "execution_mode": "OFFLINE_ONLY",
            "evidence_class": "CONTRACT_TEST_ONLY",
            "token_evidence_class": "SYNTHETIC_SDK_MOCK_TRANSPORT",
            "run": run,
            "events": events,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return FrozenEvidence(payload, hashlib.sha256(payload).hexdigest())


def score(frozen, *, expected_status, required_errors=()):
    """Post-freeze status/error contract only; business facts stay in integration tests.

    This is neither a business Oracle nor a held-out effectiveness measurement.
    No runtime action, API request, approval or recovery is reachable from here.
    """
    if hashlib.sha256(frozen.payload).hexdigest() != frozen.sha256:
        raise ValueError("EVIDENCE_HASH_MISMATCH")
    evidence = json.loads(frozen.payload)
    if (evidence["execution_mode"], evidence["evidence_class"]) != (
        "OFFLINE_ONLY",
        "CONTRACT_TEST_ONLY",
    ):
        raise ValueError("CONTRACT_EVIDENCE_REQUIRED")
    run = evidence["run"]
    ends = [
        e["payload_summary"]
        for e in evidence["events"]
        if e["event_type"] == "model_end"
    ]
    usage = "UNKNOWN"
    if (
        ends
        and len(ends) == run.get("budget", {}).get("models")
        and all(
            isinstance(end.get("usage"), dict)
            and end.get("provider_usage_state") == "OBSERVED_VALID"
            and end.get("output_budget_state") == "RECONCILED"
            and all(
                type(end["usage"].get(key)) is int and end["usage"][key] >= 0
                for key in ("input_tokens", "output_tokens", "total_tokens")
            )
            and end["usage"]["total_tokens"]
            == end["usage"]["input_tokens"] + end["usage"]["output_tokens"]
            for end in ends
        )
    ):
        usage = {
            key: sum(end["usage"][key] for end in ends)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
    errors = (run.get("result") or {}).get("error_codes", [])
    return {
        "scenario_id": evidence["scenario_id"],
        "execution_mode": evidence["execution_mode"],
        "evidence_class": evidence["evidence_class"],
        "token_evidence_class": evidence["token_evidence_class"],
        "run_id": run["id"],
        "thread_id": run["thread_id"],
        "request_id": run["request_id"],
        "evidence_sha256": frozen.sha256,
        "run_status": run["status"],
        "contract": {
            "expected_status": expected_status,
            "required_errors": list(required_errors),
        },
        "evaluation_success": run["status"] == expected_status
        and set(required_errors).issubset(errors),
        "usage": usage,
        "billing_state": "UNKNOWN" if usage == "UNKNOWN" else "NOT_APPLICABLE",
    }


def main(argv=None):
    """Fixed contract-test entry; all operator choices are visible in the tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("A", "B", "C", "all"), default="all")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    tests = root / "backend/tests"
    selected = {
        "A": [
            str(tests / "test_v216_controlled_eval.py")
            + "::test_A_recommendation_freezes_then_scores"
        ],
        "B": [
            str(tests / "test_v216_controlled_eval.py")
            + "::test_B_purchase_requires_separate_decision_and_resume"
        ],
        "C": [str(tests / "test_v215_workflow.py")],
        "all": [
            str(tests / "test_v216_controlled_eval.py"),
            str(tests / "test_v215_workflow.py"),
        ],
    }
    import pytest

    print(
        "OFFLINE_ONLY / CONTRACT_TEST_ONLY / SYNTHETIC_DEVELOPMENT / SDK_MOCK_TRANSPORT",
        flush=True,
    )
    return pytest.main(
        [
            "-c",
            str(root / "pytest.ini"),
            "--ci-offline-core",
            "-q",
            *selected[args.scenario],
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
