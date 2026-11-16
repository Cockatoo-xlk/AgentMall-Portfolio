"""OFFLINE_ONLY / CONTRACT_TEST_ONLY, synthetic development scenarios only."""

import json
from uuid import uuid4

import httpx
import pytest
from conftest import row
from playground_helpers import SDKProgram
from t09_helpers import durable_env as durable_env
from test_v213_l2_sdk import direct_sdk


def test_frozen_score_binds_identity_hash_and_keeps_unknown_usage():
    from evals.controlled_offline import freeze, score

    run = {
        "id": "synthetic-run",
        "thread_id": "synthetic-thread",
        "request_id": "synthetic-request",
        "status": "COMPLETED",
        "result": {"error_codes": []},
        "budget": {"models": 1},
    }
    events = [{"event_type": "model_end", "payload_summary": {"usage": "UNKNOWN"}}]
    frozen = freeze("development-synthetic", run, events)
    run["status"] = "PARTIAL"
    report = score(frozen, expected_status="COMPLETED")
    assert report["run_status"] == "COMPLETED" and report["evaluation_success"] is True
    assert report["run_id"] == "synthetic-run" and report["evidence_sha256"] == frozen.sha256
    assert report["usage"] == report["billing_state"] == "UNKNOWN"
    assert report["evidence_class"] == "CONTRACT_TEST_ONLY"
    assert score(frozen, expected_status="WAITING_INPUT")["evaluation_success"] is False
    # A completed Run cannot make an unmet contract pass; scoring reads frozen bytes only.
    assert (
        score(frozen, expected_status="COMPLETED", required_errors=("MISSING",))[
            "evaluation_success"
        ]
        is False
    )
    with pytest.raises(ValueError, match="EVIDENCE_HASH_MISMATCH"):
        score(type(frozen)(frozen.payload + b" ", frozen.sha256), expected_status="COMPLETED")


@pytest.mark.parametrize("condition", ["incomplete", "unknown_wire", "unresolved_budget"])
def test_partial_usage_never_becomes_zero_or_settled(condition):
    from evals.controlled_offline import freeze, score

    run = {
        "id": "run",
        "thread_id": "thread",
        "request_id": "request",
        "status": "PARTIAL",
        "budget": {"models": 2 if condition == "incomplete" else 1},
    }
    end = {
        "usage": {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
        "provider_usage_state": "UNKNOWN" if condition == "unknown_wire" else "OBSERVED_VALID",
        "output_budget_state": "UNRESOLVED" if condition == "unresolved_budget" else "RECONCILED",
    }
    evidence = freeze(
        "synthetic-development", run, [{"event_type": "model_end", "payload_summary": end}]
    )
    report = score(evidence, expected_status="PARTIAL")
    assert report["usage"] == report["billing_state"] == "UNKNOWN"


async def test_inspect_never_calls_decision_resume_or_recover():
    from evals.controlled_offline import Operator

    calls = []
    pending = {"interrupt_id": "interrupt-1", "proposal_id": "proposal-1"}
    run = {"id": "run-1", "pending_confirmation": pending}

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/threads/thread-1"):
            return httpx.Response(200, json={"runs": [run]})
        return httpx.Response(200, json={"id": "proposal-1", "canonical_payload": {}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://test"
    ) as c:
        operator = Operator(c, {"Authorization": "Bearer synthetic"})
        inspection = await operator.inspect("thread-1", "run-1")
        assert inspection["run"] == run
    assert calls == [
        ("GET", "/api/v1/agent/threads/thread-1"),
        ("GET", "/api/v1/proposals/proposal-1"),
    ]


async def test_A_recommendation_freezes_then_scores(durable_env, buyer):
    from evals.controlled_offline import Operator, freeze, score

    env = durable_env
    wire = SDKProgram("recommend")
    clients = await direct_sdk(env, wire)
    try:
        operator = Operator(env[0], buyer)
        tid = await operator.create_thread()
        run = await operator.start(tid, str(uuid4()), "推荐一款300元以内静音键盘，仅供选择")
        inspection = await operator.inspect(tid, run["id"])
        assert inspection["proposal"] is None
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        events = await operator.events(run["id"])
        frozen = freeze("A-development-recommendation", inspection["run"], events)
        calls = len(wire.requests)
        report = score(frozen, expected_status="COMPLETED")
        assert report["evaluation_success"], report
        assert report["execution_mode"] == "OFFLINE_ONLY"
        assert report["billing_state"] == "NOT_APPLICABLE"
        assert report["usage"]["total_tokens"] > 0
        assert len(wire.requests) == calls
    finally:
        await clients.aclose()


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_B_purchase_requires_separate_decision_and_resume(durable_env, buyer, decision):
    from evals.controlled_offline import Operator, freeze, score

    env = durable_env
    wire = SDKProgram("purchase")
    clients = await direct_sdk(env, wire)
    try:
        operator = Operator(env[0], buyer)
        tid = await operator.create_thread()
        run = await operator.start(tid, str(uuid4()), "找一款300元以内静音键盘准备购买，送演示宿舍")
        inspection = await operator.inspect(tid, run["id"])
        assert inspection["run"]["status"] == "WAITING_INPUT"
        assert inspection["proposal"]["action_type"] == "CHECKOUT"
        assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        waiting = freeze(
            "B-development-purchase", inspection["run"], await operator.events(run["id"])
        )
        assert score(waiting, expected_status="WAITING_INPUT")["evaluation_success"] is True
        with pytest.raises(ValueError, match="EXPLICIT_DECISION_REQUIRED"):
            await operator.decide(inspection, decision="wait")
        # This explicit test actor approves or rejects. The helper does not choose a decision.
        calls_before_decision = len(wire.requests)
        confirmation = await operator.decide(inspection, decision=decision)
        assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert len(wire.requests) == calls_before_decision
        assert (await operator.inspect(tid, run["id"]))["run"]["status"] == "WAITING_INPUT"
        request_id = str(uuid4())
        done = await operator.resume(tid, inspection, confirmation["confirmation_id"], request_id)
        assert done["id"] == run["id"]
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == (decision == "approve")
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
        calls = len(wire.requests)
        assert (
            await operator.resume(tid, inspection, confirmation["confirmation_id"], request_id)
            == done
        )
        assert len(wire.requests) == calls
        events = await operator.events(done["id"])
        frozen = freeze("B-development-purchase", done, events)
        assert not any("recover" in e.get("event_type", "") for e in events)
        # Verify outcome independently of Run status through committed business facts above.
        report = score(frozen, expected_status="COMPLETED")
        assert report["evaluation_success"], report
        assert report["run_id"] == run["id"]
    finally:
        await clients.aclose()


async def test_missing_usage_is_unknown_after_freeze(durable_env, buyer):
    from evals.controlled_offline import Operator, freeze, score

    env = durable_env
    wire = SDKProgram("missing_usage")
    clients = await direct_sdk(env, wire)
    try:
        operator = Operator(env[0], buyer)
        tid = await operator.create_thread()
        run = await operator.start(tid, str(uuid4()), "推荐一款合成键盘，仅供选择")
        events = await operator.events(run["id"])
        report = score(freeze("missing-usage-development", run, events), expected_status="PARTIAL")
        assert report["usage"] == report["billing_state"] == "UNKNOWN"
        assert report["evaluation_success"], json.dumps(report)
        assert report["run_status"] == "PARTIAL"
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    finally:
        await clients.aclose()
