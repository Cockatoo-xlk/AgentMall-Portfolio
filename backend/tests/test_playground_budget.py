"""Offline SDK/ledger tests; synthetic keys, no Live authorization or provider network."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import HumanMessage


def policy(**changes):
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint

    return PlaygroundPolicy(
        enabled=True,
        evidence_mode="MOCK_TRANSPORT",
        session_id=uuid4(),
        environment_id=uuid4(),
        source_sha256=source_fingerprint(),
        price_checked_at=datetime.now(UTC),
        **changes,
    )


def scope():
    from agentmall.playground.context import CallScope

    return CallScope(uuid4(), uuid4(), uuid4(), uuid4())


def wire(*, usage=True, tool=None, model="deepseek-flash"):
    message = {"role": "assistant", "content": "合成结果"}
    if tool is not None:
        message["tool_calls"] = [tool]
    response = {
        "id": "chatcmpl-synthetic",
        "model": model,
        "choices": [
            {"index": 0, "finish_reason": "tool_calls" if tool else "stop", "message": message}
        ],
    }
    if usage:
        response["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    return response


def test_default_app_and_live_gate_do_not_read_key_without_approval(tmp_path, monkeypatch):
    from agentmall.playground.app import create_live_app
    from agentmall.playground.policy import PlaygroundRejected

    monkeypatch.setattr("agentmall.playground.app.load_live_key", lambda: pytest.fail("Key read"))
    p = policy().model_copy(update={"enabled": False, "evidence_mode": "LIVE_DEEPSEEK"})
    with pytest.raises(PlaygroundRejected, match="LIVE_DISABLED"):
        create_live_app(p, approval_path=tmp_path / "missing", state_dir=tmp_path)
    p = p.model_copy(update={"enabled": True})
    with pytest.raises(PlaygroundRejected, match="APPROVAL_REQUIRED"):
        create_live_app(p, approval_path=tmp_path / "missing", state_dir=tmp_path)
    assert not (tmp_path / "ledger.json").exists()


def test_historical_or_mock_approval_is_not_live_authority(tmp_path):
    from agentmall.playground.policy import PlaygroundRejected, validate_approval

    p = policy().model_copy(update={"evidence_mode": "LIVE_DEEPSEEK"})
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({"experiment": "t12-live-retest-01", "approved": True}))
    approval.chmod(0o600)
    with pytest.raises(PlaygroundRejected):
        validate_approval(p, approval)


def test_stale_price_or_source_is_rejected_before_send(tmp_path):
    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.policy import PlaygroundRejected

    old = policy().model_copy(update={"price_checked_at": datetime.now(UTC) - timedelta(days=2)})
    with pytest.raises(PlaygroundRejected, match="PRICE_EXPIRED"):
        PlaygroundLedger(tmp_path / "ledger.json", old)
    bad = policy().model_copy(update={"source_sha256": "0" * 64})
    with pytest.raises(PlaygroundRejected, match="SOURCE_MISMATCH"):
        bad.validate_current()


async def test_real_sdk_reserves_before_wire_and_reports_safe_usage(tmp_path):
    from agentmall.playground.context import call_scope
    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.provider import metered_model

    ledger = PlaygroundLedger(tmp_path / "ledger.json", policy())
    actor = scope()
    requests = []

    def receive(request):
        data = json.loads(request.content)
        rows = ledger.read()["attempts"]
        assert rows[-1]["state"] == "RESERVED"
        assert data["model"] == "deepseek-flash" and data["max_tokens"] == 200
        assert data["thinking"] == {"type": "disabled"} and data["temperature"] == 0
        assert request.url == "https://api.deepseek.com/chat/completions"
        requests.append(data)
        return httpx.Response(200, json=wire(), headers={"x-request-id": "synthetic-request"})

    model, clients = metered_model(
        ledger, "supervisor", "synthetic-not-a-real-key", httpx.MockTransport(receive)
    )
    try:
        with call_scope(actor):
            reply = await model.ainvoke([HumanMessage(content="合成需求私密文本")], max_tokens=200)
        assert reply.usage_metadata["total_tokens"] == 120
        summary = ledger.summary(actor.user_id, actor.store_id, actor.run_id)
        assert summary["mode"] == "MOCK_TRANSPORT" and summary["requests_reserved"] == 1
        assert summary["valid_responses"] == 1 and summary["actual_bill_cny"] == "UNKNOWN"
        assert summary["usage"]["input_tokens"] == 100
        assert Decimal(summary["estimated_upper_cost_cny"]) == Decimal("0.00036")
        raw = (tmp_path / "ledger.json").read_text()
        assert "合成需求私密文本" not in raw and "synthetic-not-a-real-key" not in raw
        assert "Bearer" not in raw and len(requests) == 1
    finally:
        await clients.close()


@pytest.mark.parametrize("failure", ["usage", "http", "timeout", "tool", "length", "model"])
async def test_failure_halts_and_holds_unknown_reservation_without_retry(tmp_path, failure):
    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.context import call_scope
    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.provider import metered_model

    ledger = PlaygroundLedger(tmp_path / "ledger.json", policy())
    sent = 0

    def receive(request):
        nonlocal sent
        sent += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic provider secret must never escape")
        data = wire(
            usage=failure != "usage",
            model="unknown-model" if failure == "model" else "deepseek-flash",
        )
        if failure == "tool":
            data = wire(
                tool={
                    "id": "synthetic",
                    "type": "function",
                    "function": {"name": "approve_payment", "arguments": "{}"},
                }
            )
        if failure == "length":
            data["choices"][0]["finish_reason"] = "length"
        return httpx.Response(500 if failure == "http" else 200, json=data)

    model, clients = metered_model(ledger, "order", "synthetic-key", httpx.MockTransport(receive))
    try:
        with call_scope(scope()), pytest.raises(RunStopped):
            await model.ainvoke([HumanMessage(content="私密请求")], max_tokens=200)
        with call_scope(scope()), pytest.raises(RunStopped):
            await model.ainvoke([HumanMessage(content="不得自动补发")], max_tokens=200)
        assert sent == 1
        data = ledger.read()
        assert data["halted"] and len(data["attempts"]) == 1
        assert Decimal(data["attempts"][0]["held_cny"]) == Decimal("2.098752")
        assert "synthetic provider secret" not in (tmp_path / "ledger.json").read_text()
    finally:
        await clients.close()


async def test_restart_or_missing_scope_never_blindly_replays_paid_node(tmp_path):
    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.context import call_scope
    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.provider import metered_model

    p, owner = policy(), scope()
    ledger = PlaygroundLedger(tmp_path / "ledger.json", p)
    count = 0

    def receive(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json=wire())

    model, clients = metered_model(ledger, "order", "synthetic-key", httpx.MockTransport(receive))
    try:
        with pytest.raises(RunStopped, match="RUN_SCOPE_REQUIRED"):
            await model.ainvoke("无持久Run", max_tokens=200)
        with call_scope(owner):
            await model.ainvoke("原节点", max_tokens=200)
        reopened = PlaygroundLedger(tmp_path / "ledger.json", p)
        model2, clients2 = metered_model(
            reopened, "order", "synthetic-key", httpx.MockTransport(receive)
        )
        try:
            with call_scope(owner), pytest.raises(RunStopped, match="MODEL_REPLAY_BLOCKED"):
                await model2.ainvoke("即使上下文改变也不再付费", max_tokens=200)
            assert count == 1
        finally:
            await clients2.close()
    finally:
        await clients.close()


def test_ledger_concurrent_caps_owner_isolation_and_no_reset(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.ledger import PlaygroundLedger

    p = policy(max_model_calls=2, max_cost_cny="5")
    path = tmp_path / "ledger.json"
    ledger = PlaygroundLedger(path, p)
    owners = [scope() for _ in range(8)]

    def reserve(owner):
        try:
            return ledger.reserve(owner, "supervisor", "supervisor:0", 1, 200, "0" * 64)
        except RunStopped:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, owners))
    assert sum(r is not None for r in results) == 2
    assert len(PlaygroundLedger(path, p).read()["attempts"]) == 2
    unowned = scope()
    assert ledger.summary(unowned.user_id, unowned.store_id)["requests_reserved"] == 0
    assert len(json.loads(path.read_text())["attempts"]) == 2


def test_unknown_after_process_stop_blocks_new_calls_and_does_not_release(tmp_path):
    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.ledger import PlaygroundLedger

    p, owner = policy(), scope()
    ledger = PlaygroundLedger(tmp_path / "ledger.json", p)
    ledger.reserve(owner, "order", "order:buy", 1, 200, "0" * 64)
    reopened = PlaygroundLedger(tmp_path / "ledger.json", p)
    with pytest.raises(RunStopped, match="PROVIDER_OUTCOME_UNKNOWN"):
        reopened.reserve(scope(), "order", "order:next", 1, 200, "0" * 64)
    assert len(reopened.read()["attempts"]) == 1


@pytest.mark.parametrize("limit", ["input", "output", "cost", "wall"])
def test_each_budget_dimension_is_enforced(tmp_path, limit):
    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.ledger import PlaygroundLedger

    changes = (
        {"max_input_tokens": 1}
        if limit == "input"
        else {"max_output_tokens": 1}
        if limit == "output"
        else {"max_cost_cny": "0.01"}
        if limit == "cost"
        else {}
    )
    ledger = PlaygroundLedger(tmp_path / "ledger.json", policy(**changes))
    if limit == "wall":
        data = ledger.read()
        data["started_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        ledger._write(data)
    with pytest.raises(RunStopped):
        ledger.reserve(scope(), "order", "order:x", 1, 200, "0" * 64)
    assert ledger.read()["attempts"] == []


@pytest.mark.parametrize("corruption", ["cost", "json", "future_clock"])
def test_corrupt_or_uncertain_ledger_never_reserves_again(tmp_path, corruption):
    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.ledger import PlaygroundLedger

    p = policy()
    ledger = PlaygroundLedger(tmp_path / "ledger.json", p)
    token = ledger.reserve(scope(), "order", "order:x", 1, 200, "0" * 64)
    ledger.finish(token, wire(), 200, "synthetic")
    data = ledger.read()
    if corruption == "cost":
        data["attempts"][0]["held_cny"] = "0"
        ledger._write(data)
    elif corruption == "future_clock":
        data["started_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        ledger._write(data)
    else:
        (tmp_path / "ledger.json").write_text("{")
    with pytest.raises(RunStopped):
        ledger.reserve(scope(), "order", "order:y", 1, 200, "0" * 64)


@pytest.mark.parametrize("malformed", ["forced_route", "usage_details", "reasoning"])
async def test_review_protocol_errors_halt_before_sdk_parse_or_automatic_repair(
    tmp_path, malformed
):
    from agentmall.agents.budgets import RunStopped
    from agentmall.playground.context import call_scope
    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.provider import metered_model

    ledger = PlaygroundLedger(tmp_path / "ledger.json", policy())
    data = wire()
    if malformed == "usage_details":
        data["usage"]["prompt_tokens_details"] = [1]
    if malformed == "reasoning":
        data["choices"][0]["message"]["reasoning"] = "private reasoning must never enter graph"
    count = 0

    def respond(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json=data)

    model, clients = metered_model(ledger, "supervisor", "synthetic", httpx.MockTransport(respond))
    if malformed == "forced_route":
        model = model.bind_tools(
            [{"type": "function", "function": {"name": "route", "parameters": {"type": "object"}}}],
            tool_choice="route",
        )
    try:
        with call_scope(scope()), pytest.raises(RunStopped):
            await model.ainvoke("synthetic request", max_tokens=200)
        with call_scope(scope()), pytest.raises(RunStopped):
            await model.ainvoke("no automatic repair", max_tokens=200)
        assert count == 1
        row = ledger.read()["attempts"][0]
        assert row["state"] == "STOPPED" and row["usage"] == "UNKNOWN"
    finally:
        await clients.close()
