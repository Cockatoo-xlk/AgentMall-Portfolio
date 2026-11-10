"""L4: synthetic authorization/ledgers only; no real key or provider transport."""

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from evals import manifest, run
from evals.provider import BudgetLedger, ProviderBoundaryError
from evals.schema import canonical
from test_live_preflight import completion

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = {
    "version": 1,
    "id": "t12-live-retest-01",
    "authorization_status": "NOT_AUTHORIZED",
    "ledger": "evals/live/t12-live-retest-01-ledger.json",
    "authorization": "evals/live/t12-live-retest-01-authorization.json",
    "results": "evals/results/t12-live-retest-01",
    "parent_manifest_sha256": "15742b3e7e15408e1b1b066b867d29102f0ea7ff34e348e682fc2ad483bc448d",
    "task_ids": [
        "eval_dev_A1_01",
        "eval_dev_A2_01",
        "eval_dev_B1_01",
        "eval_dev_B2_01",
        "eval_dev_B1_03",
    ],
    "split": "dev",
    "repeats": 1,
    "architectures": "single,multi",
    "budget": {"max_model_calls": 100, "max_cost_cny": "5", "max_wall_seconds": 1200},
}


def record(name, value):
    destination = os.environ.get("AGENTMALL_L4_EVIDENCE_DIR")
    if destination:
        directory = Path(destination).resolve()
        assert directory.is_relative_to(ROOT / "evals/evidence/t12-live-retest-preflight")
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (name + ".json")).open("x") as stream:
            json.dump({"class": "MOCK_PROTOCOL", "paid_requests": 0, **value}, stream, indent=2)
            stream.write("\n")


def candidate():
    data = json.loads((ROOT / "evals/config/frozen-live-rca.yaml").read_text())
    data.update(version=2, experiment=deepcopy(EXPERIMENT), live_ledger=EXPERIMENT["ledger"])
    # This temporary synthetic candidate exercises the current admission guard.
    # Historical manifests stay immutable and never authorize this test.
    prompts = {
        "single": manifest.SINGLE_PROMPT,
        "supervisor": manifest.SYSTEM_PROMPT,
        **manifest.PROMPTS,
    }
    data["prompt_hashes"] = {
        name: manifest.digest(prompt.encode()) for name, prompt in prompts.items()
    }
    data["source_hashes"] = manifest.source_hashes()
    data["source_bundle_hash"] = manifest.digest(canonical(data["source_hashes"]).encode())
    data["provider"]["price_snapshot"]["checked_at_utc"] = datetime.now(UTC).isoformat()
    return data


def arguments(**changes):
    return SimpleNamespace(
        **(
            {
                "mode": "live",
                "split": "dev",
                "pilot": True,
                "repeats": 1,
                "architectures": "single,multi",
                "run_id": "t12-live-retest-01",
                "confirm_live": True,
                **EXPERIMENT["budget"],
            }
            | changes
        )
    )


def setup_candidate(tmp_path, monkeypatch):
    from evals import experiments

    monkeypatch.setattr(experiments, "ROOT", tmp_path)
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate()))
    return experiments, path


async def test_live_cli_without_new_authorization_never_opens_ledger_or_reads_key(
    tmp_path, monkeypatch
):
    from evals import experiments

    from agentmall.infra import llm

    data = candidate()
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(experiments, "ROOT", tmp_path)
    monkeypatch.setattr(run, "load_tasks", lambda path: [])
    monkeypatch.setattr(manifest, "validate_manifest", lambda path: (data, "a" * 64))
    monkeypatch.setattr(
        llm, "load_live_key", lambda: pytest.fail("read real key without authorization")
    )
    args = arguments()
    args.manifest = path
    with pytest.raises(ProviderBoundaryError, match="NOT_AUTHORIZED"):
        await run.execute(args)
    assert not (tmp_path / "evals/live").exists()


def test_independent_authorization_ledger_restart_and_run_identity(tmp_path, monkeypatch):
    from test_eval_budget import policy

    e, path = setup_candidate(tmp_path, monkeypatch)
    old = tmp_path / "evals/live/t12-experiment-ledger.json"
    old.parent.mkdir(parents=True)
    historical = BudgetLedger(old, policy())
    token = historical.reserve("old-synthetic-episode", 2048)
    historical.finish(
        token,
        {"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
        http_status=200,
    )
    before = old.read_bytes()
    with pytest.raises(ProviderBoundaryError, match="NOT_AUTHORIZED"):
        e.authorize(path, confirm=False, approval_reference="synthetic owner decision")
    e.authorize(path, confirm=True, approval_reference="synthetic owner decision")
    assert not (tmp_path / EXPERIMENT["ledger"]).exists()  # approval alone never opens budget
    data, ident = manifest.validate_manifest(path)
    ledger = e.open_ledger(data, ident, arguments())
    first = ledger.reserve("eval_dev_A1_01:0:single", 2048)
    assert Decimal(ledger.read()["attempts"][0]["held_cny"]) == Decimal("2.113536")
    started = ledger.read()["started_at"]
    reopened = e.open_ledger(data, ident, arguments())
    assert reopened.read()["started_at"] == started
    assert reopened.read()["attempts"][0]["id"] == first
    with pytest.raises(ProviderBoundaryError, match="RUN_ID"):
        e.open_ledger(data, ident, arguments(run_id="fresh-budget"))
    assert {p.name for p in old.parent.glob("*ledger.json")} == {old.name, ledger.path.name}
    assert old.read_bytes() == before
    assert not (tmp_path / EXPERIMENT["results"]).exists()
    record(
        "isolation-restart",
        {
            "old_before_sha256": hashlib.sha256(before).hexdigest(),
            "old_after_sha256": hashlib.sha256(old.read_bytes()).hexdigest(),
            "new_ledger": ledger.read(),
            "restart_preserved_start_time": started == reopened.read()["started_at"],
            "changed_run_id": "REJECTED",
            "ledger_count": len(list(old.parent.glob("*ledger.json"))),
        },
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("ledger", "evals/live/t12-experiment-ledger.json"),
        ("ledger", "../escape.json"),
        ("id", "new-id"),
        ("results", "evals/results/t12-live-pilot-01"),
    ],
)
def test_unregistered_identity_or_path_is_rejected(tmp_path, monkeypatch, field, value):
    e, path = setup_candidate(tmp_path, monkeypatch)
    data = json.loads(path.read_text())
    data["experiment"][field] = value
    if field == "ledger":
        data["live_ledger"] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ProviderBoundaryError, match="EXPERIMENT"):
        e.authorize(path, confirm=True, approval_reference="synthetic")
    assert not (tmp_path / "evals/live").exists()


@pytest.mark.parametrize(
    "mutation", ["manifest", "model", "tool_schema", "prompt", "budget", "cli_budget"]
)
def test_frozen_authority_cannot_be_rebound(tmp_path, monkeypatch, mutation):
    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic")
    before = (tmp_path / EXPERIMENT["authorization"]).read_bytes()
    data = json.loads(path.read_text())
    args = arguments()
    if mutation == "manifest":
        data["annotation"] = "different approved material"
    elif mutation == "model":
        data["provider"]["model_id"] = "other-model"
    elif mutation == "tool_schema":
        data["tool_schema_hash"] = "a" * 64
    elif mutation == "prompt":
        data["prompt_hashes"]["single"] = "a" * 64
    elif mutation == "budget":
        data["experiment"]["budget"]["max_cost_cny"] = "50"
    else:
        args.max_cost_cny = "50"
    path.write_text(json.dumps(data))
    with pytest.raises((ValueError, ProviderBoundaryError)):
        data, ident = manifest.validate_manifest(path)
        e.open_ledger(data, ident, args)
    assert (tmp_path / EXPERIMENT["authorization"]).read_bytes() == before
    assert not (tmp_path / EXPERIMENT["ledger"]).exists()


def test_second_experiment_does_not_reset_sealed_claim_or_overwrite_results(tmp_path, monkeypatch):
    e, path = setup_candidate(tmp_path, monkeypatch)
    seal = tmp_path / "sealed.json"
    manifest.claim_sealed("a" * 64, "old", path=seal)
    before = seal.read_bytes()
    e.authorize(path, confirm=True, approval_reference="synthetic")
    with pytest.raises(FileExistsError):
        manifest.claim_sealed("b" * 64, "second-experiment", path=seal)
    assert seal.read_bytes() == before
    data, ident = manifest.validate_manifest(path)
    directory = tmp_path / EXPERIMENT["results"]
    directory.mkdir(parents=True)
    (directory / "old-result.json").write_text("{}")
    with pytest.raises(ProviderBoundaryError, match="RESULTS_EXIST"):
        e.open_ledger(data, ident, arguments())
    assert not (tmp_path / EXPERIMENT["ledger"]).exists()


def test_invalid_database_is_rejected_before_authority_or_ledger(tmp_path, monkeypatch):
    from evals import fixtures

    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic")
    data, ident = manifest.validate_manifest(path)
    monkeypatch.setattr(
        fixtures,
        "dotenv_values",
        lambda p: {
            "AGENTMALL_TEST_DATABASE_URL": "postgresql+psycopg://agentmall:synthetic@127.0.0.1:55432/agentmall_test"
        },
    )
    monkeypatch.setattr(fixtures, "create_engine", lambda *a, **k: pytest.fail("DB connected"))
    with pytest.raises(ValueError, match="55433"):
        e.open_ledger(data, ident, arguments())
    assert not (tmp_path / EXPERIMENT["ledger"]).exists()


@pytest.mark.parametrize("outcome", ["usage", "unknown", 429, 500, "response_loss"])
async def test_authorized_mock_sdk_reserves_before_wire_and_never_retries(
    tmp_path, monkeypatch, outcome
):
    from evals.provider import MeteredTransport, live_model
    from openai import APIConnectionError, APIStatusError

    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic")
    ledger = e.open_ledger(*manifest.validate_manifest(path), arguments())
    calls = []

    def wire(request):
        assert ledger.read()["attempts"][-1]["state"] == "RESERVED"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash" and body["temperature"] == 0
        assert body["thinking"] == {"type": "disabled"} and not body.get("stream")
        calls.append(1)
        if outcome == "response_loss":
            raise httpx.ReadError("synthetic", request=request)
        if type(outcome) is int:
            return httpx.Response(outcome, json={"error": {"message": "synthetic"}})
        return httpx.Response(
            200,
            json=completion(
                "",
                "mock-id",
                calls=[{"id": "c1", "name": "get_cart", "args": {}}],
                usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
                if outcome == "usage"
                else None,
            ),
        )

    async with httpx.AsyncClient(
        transport=MeteredTransport(
            ledger, "eval_dev_A1_01:0:single", inner=httpx.MockTransport(wire)
        ),
        trust_env=False,
    ) as client:
        model = live_model("synthetic-L4-key", client)
        assert model.max_retries == model.root_async_client.max_retries == 0
        if outcome in [429, 500, "response_loss"]:
            with pytest.raises((APIConnectionError, APIStatusError)):
                await model.ainvoke("synthetic-L4-prompt", max_tokens=2048)
        else:
            response = await model.ainvoke("synthetic-L4-prompt", max_tokens=2048)
            assert response.tool_calls == [
                {"name": "get_cart", "args": {}, "id": "c1", "type": "tool_call"}
            ]
    data = ledger.read()
    assert len(calls) == len(data["attempts"]) == 1
    assert Decimal(data["attempts"][0]["held_cny"]) == Decimal(
        "0.00036" if outcome == "usage" else "2.113536"
    )
    assert data["attempts"][0]["state"] == ("SETTLED" if outcome == "usage" else "UNKNOWN")
    assert "synthetic-L4-key" not in ledger.path.read_text()
    assert "synthetic-L4-prompt" not in ledger.path.read_text()
    record(
        f"sdk-{outcome}",
        {
            "http_attempts": len(calls),
            "ledger": data,
            "sdk_retries": model.max_retries,
            "sdk_root_retries": model.root_async_client.max_retries,
            "tool_call_shape": "get_cart/c1/empty args verified"
            if outcome in {"usage", "unknown"}
            else "HTTP error; no synthetic success",
        },
    )


def test_historical_manifest_integrity_can_be_checked_without_live_admission(tmp_path):
    path = ROOT / "evals/config/frozen-live-rca.yaml"
    data, ident = manifest.validate_manifest(path, current=False)
    assert ident == "15742b3e7e15408e1b1b066b867d29102f0ea7ff34e348e682fc2ad483bc448d"
    data["source_bundle_hash"] = "a" * 64
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="BUNDLE"):
        manifest.validate_manifest(broken, current=False)


def test_same_experiment_concurrent_reservations_share_five_yuan_cap(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic")
    data, ident = manifest.validate_manifest(path)
    barrier = Barrier(4, timeout=10)

    def reserve(index):
        ledger = e.open_ledger(data, ident, arguments())
        barrier.wait()
        try:
            return ledger.reserve(f"synthetic-episode:{index}", 2048)
        except ProviderBoundaryError as exc:
            assert str(exc) == "EXPERIMENT_BUDGET_EXHAUSTED"
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(reserve, range(4)))
    rows = e.open_ledger(data, ident, arguments()).read()["attempts"]
    assert sum(x is not None for x in outcomes) == len(rows) == 2
    assert sum(Decimal(r["held_cny"]) for r in rows) == Decimal("4.227072")
    record(
        "concurrent-cap",
        {
            "participants": 4,
            "successes": sum(x is not None for x in outcomes),
            "rejections": sum(x is None for x in outcomes),
            "reserved_cny": str(sum(Decimal(r["held_cny"]) for r in rows)),
            "rows": rows,
        },
    )


def test_repeat_authorization_does_not_reset_receipt_or_allow_new_manifest(tmp_path, monkeypatch):
    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic-first")
    before = (tmp_path / EXPERIMENT["authorization"]).read_bytes()
    e.authorize(path, confirm=True, approval_reference="synthetic-repeat")
    assert (tmp_path / EXPERIMENT["authorization"]).read_bytes() == before
    data = json.loads(path.read_text())
    data["annotation"] = "new manifest cannot reuse consumed approval identity"
    path.write_text(json.dumps(data))
    with pytest.raises(ProviderBoundaryError, match="BINDING"):
        e.authorize(path, confirm=True, approval_reference="synthetic-other")
    assert (tmp_path / EXPERIMENT["authorization"]).read_bytes() == before


@pytest.mark.parametrize("target", ["ledger", "authorization", "results"])
def test_fixed_paths_reject_symlink_aliases(tmp_path, monkeypatch, target):
    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic")
    data, ident = manifest.validate_manifest(path)
    outsider = tmp_path / "synthetic-other-project"
    outsider.write_text("preserve")
    link = tmp_path / EXPERIMENT[target]
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists():
        link.unlink()  # only this test's temporary synthetic authorization
    link.symlink_to(outsider)
    with pytest.raises(ProviderBoundaryError, match="SYMLINK"):
        e.open_ledger(data, ident, arguments())
    assert outsider.read_text() == "preserve"


def test_expired_experiment_refuses_attempt_after_restart(tmp_path, monkeypatch):
    e, path = setup_candidate(tmp_path, monkeypatch)
    e.authorize(path, confirm=True, approval_reference="synthetic")
    ledger = e.open_ledger(*manifest.validate_manifest(path), arguments())
    data = ledger.read()
    data["started_at"] = (datetime.now(UTC) - timedelta(seconds=1201)).isoformat()
    ledger.path.write_text(json.dumps(data))  # controlled clock fixture, not a production reset
    reopened = BudgetLedger(ledger.path, ledger.policy)
    with pytest.raises(ProviderBoundaryError, match="BUDGET"):
        reopened.reserve("same-episode", 2048)
    assert reopened.read()["attempts"] == []


def test_price_expiring_during_experiment_blocks_next_send(tmp_path, monkeypatch):
    from evals import provider
    from test_eval_budget import policy

    current = datetime.now(UTC)
    ledger = BudgetLedger(
        tmp_path / "synthetic-ledger.json",
        policy(
            price_checked_at=(current - timedelta(hours=23, minutes=59)).isoformat(),
            max_wall_seconds=1200,
        ),
    )

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return current + timedelta(minutes=2)

    monkeypatch.setattr(provider, "datetime", Later)
    with pytest.raises(ProviderBoundaryError, match="PRICE"):
        ledger.reserve("same-episode", 2048)
    assert ledger.read()["attempts"] == []
