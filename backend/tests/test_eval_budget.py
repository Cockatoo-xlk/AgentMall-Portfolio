import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from evals.provider import BudgetLedger, LivePolicy, MeteredTransport, ProviderBoundaryError


def policy(**changes):
    base = {
        "confirm_live": True,
        "max_model_calls": 2,
        "max_cost_cny": "5",
        "max_wall_seconds": 120,
        "manifest_hash": "a" * 64,
        "price_checked_at": datetime.now(UTC).isoformat(),
        "input_cny_per_million": "2",
        "output_cny_per_million": "8",
        "price_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
    }
    return LivePolicy(**(base | changes))


def test_live_requires_all_hard_limits_and_current_price():
    for changes in (
        {"confirm_live": False},
        {"max_model_calls": 0},
        {"max_cost_cny": "0"},
        {"max_cost_cny": "NaN"},
        {"max_wall_seconds": 0},
        {"input_cny_per_million": None},
        {"price_checked_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()},
    ):
        with pytest.raises((ValueError, ProviderBoundaryError)):
            policy(**changes)


def test_unknown_usage_retains_reservation_and_restart_does_not_reset(tmp_path):
    path = tmp_path / "ledger.json"
    p = policy(max_cost_cny="3")
    ledger = BudgetLedger(path, p)
    attempt = ledger.reserve("task:0:single", 100)
    assert json.loads(path.read_text())["attempts"][0]["state"] == "RESERVED"
    ledger.finish(attempt, {}, http_status=502)
    before = json.loads(path.read_text())
    assert before["attempts"][0]["usage"] == "UNKNOWN"
    resumed = BudgetLedger(path, p)
    with pytest.raises(ProviderBoundaryError, match="BUDGET"):
        resumed.reserve("different-run-label:0:multi", 100)
    assert len(json.loads(path.read_text())["attempts"]) == 1
    with pytest.raises(ProviderBoundaryError, match="BINDING"):
        BudgetLedger(path, policy(max_model_calls=3))


def test_settlement_releases_only_proven_usage_and_counts_errors(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json", policy())
    first = ledger.reserve("task:0:single", 100)
    ledger.finish(
        first,
        {
            "id": "synthetic-response",
            "model": "alias",
            "system_fingerprint": "fp-synthetic",
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
        http_status=200,
    )
    second = ledger.reserve("task:0:multi", 100)
    ledger.finish(second, {}, http_status=500)
    with pytest.raises(ProviderBoundaryError, match="BUDGET"):
        ledger.reserve("third", 100)
    rows = ledger.read()["attempts"]
    assert Decimal(rows[0]["held_cny"]) == Decimal("0.00036")
    assert rows[1]["usage"] == "UNKNOWN"
    assert rows[0]["response_id"] == "synthetic-response"


@pytest.mark.parametrize(
    "bad_usage",
    [
        None,
        {},
        {"prompt_tokens": 10, "completion_tokens": 0},
        {"prompt_tokens": True, "completion_tokens": 0, "total_tokens": 1},
        {"prompt_tokens": 10, "completion_tokens": -1, "total_tokens": 9},
        {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 999},
    ],
)
def test_missing_or_invalid_usage_never_refunds_budget(tmp_path, bad_usage):
    ledger = BudgetLedger(tmp_path / "ledger.json", policy())
    token = ledger.reserve("task", 100)
    before = ledger.read()["attempts"][0]["held_cny"]
    ledger.finish(token, {"usage": bad_usage}, http_status=200)
    assert ledger.read()["attempts"][0]["held_cny"] == before
    assert ledger.read()["attempts"][0]["usage"] == "UNKNOWN"


async def test_actual_sdk_wire_is_metered_before_mock_http_and_never_logs_prompt(tmp_path):
    from agentmall.infra.llm import deepseek_model

    ledger = BudgetLedger(tmp_path / "ledger.json", policy())
    received = []

    def wire(request):
        assert len(ledger.read()["attempts"]) == 1
        body = json.loads(request.content)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        assert body["tools"][0]["function"]["name"] == "get_cart"
        received.append(body)
        return httpx.Response(
            200,
            json={
                "id": "mock-response",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "system_fingerprint": "fp-mock",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_local",
                                    "type": "function",
                                    "function": {"name": "get_cart", "arguments": "{}"},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    transport = MeteredTransport(ledger, "task:0:single", inner=httpx.MockTransport(wire))
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        model = deepseek_model("synthetic-t12-key", http_async_client=client)
        model = model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_cart",
                        "description": "read",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        )
        message = await model.ainvoke("synthetic private prompt marker", max_tokens=100)
        assert message.tool_calls[0]["name"] == "get_cart"
    text = (tmp_path / "ledger.json").read_text()
    assert "synthetic private prompt marker" not in text
    assert "synthetic-t12-key" not in text
    assert len(received) == 1


async def test_transport_refuses_other_provider_and_oversize_context(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json", policy())

    def forbidden(request):
        raise AssertionError("Network must not be reached")

    async with httpx.AsyncClient(
        transport=MeteredTransport(ledger, "task", inner=httpx.MockTransport(forbidden))
    ) as client:
        with pytest.raises(ProviderBoundaryError):
            await client.post("https://other.invalid/chat/completions", json={})
        with pytest.raises(ProviderBoundaryError):
            await client.post(
                "https://api.deepseek.com/chat/completions",
                json={
                    "model": "deepseek-flash",
                    "thinking": {"type": "disabled"},
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "x" * 70000}],
                },
            )
    assert ledger.read()["attempts"] == []


def test_concurrent_reservations_are_atomic_and_wall_cap_survives_restart(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    p = policy(max_model_calls=3, max_cost_cny="20")
    ledger = BudgetLedger(tmp_path / "ledger.json", p)

    def reserve(i):
        try:
            return ledger.reserve(f"task:{i}", 100)
        except ProviderBoundaryError:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        attempts = list(executor.map(reserve, range(12)))
    assert sum(x is not None for x in attempts) == 3
    assert len(ledger.read()["attempts"]) == 3
    other = tmp_path / "time-ledger.json"
    timed = BudgetLedger(other, p)
    data = timed.read()
    data["started_at"] = (datetime.now(UTC) - timedelta(seconds=121)).isoformat()
    timed._write(data)
    with pytest.raises(ProviderBoundaryError, match="BUDGET"):
        BudgetLedger(other, p).reserve("task", 100)


def test_live_failure_evidence_reconciles_durable_reservation(tmp_path):
    from evals.run import reconcile_live

    ledger = BudgetLedger(tmp_path / "ledger.json", policy())
    ledger.reserve("task:0:single", 100)
    output = {"paid_provider_requests": 0, "cost_cny": "NOT_APPLICABLE"}
    reconcile_live(output, ledger, "task", 0, "single")
    assert output["paid_provider_requests"] == 1
    assert output["cost_cny"] == "UNKNOWN"
    assert Decimal(output["reserved_upper_cost_cny"]) > 0
    assert len(output["provider_calls"]) == 1


async def test_transport_deadline_charges_before_canceling_slow_mock(tmp_path, monkeypatch):
    import asyncio

    ledger = BudgetLedger(tmp_path / "ledger.json", policy())
    monkeypatch.setattr(ledger, "seconds_left", lambda: 0.01)

    async def slow(request):
        await asyncio.Event().wait()

    async with httpx.AsyncClient(
        transport=MeteredTransport(ledger, "task", inner=httpx.MockTransport(slow))
    ) as client:
        with pytest.raises(TimeoutError):
            await client.post(
                "https://api.deepseek.com/chat/completions",
                json={
                    "model": "deepseek-flash",
                    "thinking": {"type": "disabled"},
                    "max_tokens": 100,
                },
            )
    attempts = ledger.read()["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["usage"] == "UNKNOWN"
    assert attempts[0]["http_status"] == "TRANSPORT_ERROR"
