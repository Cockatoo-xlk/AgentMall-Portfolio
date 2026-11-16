"""Actual SDK + existing native metering, CONTRACT_TEST_ONLY wire responses."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from test_v217_live1_gate import implementation
from test_v217_smoke_contract import proposal

from agentmall.agents.budgets import RunStopped
from agentmall.playground.context import CallScope, call_scope


def price():
    return {
        "source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        "checked_at": datetime.now(UTC).isoformat(),
        "peak_input_cache_miss": "2",
        "peak_output": "8",
        "model": "deepseek-flash",
        "documented_revision": "DeepSeek-V4.1-Flash-1017",
    }


def response():
    return {
        "id": "contract-response",
        "model": "deepseek-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_contract",
                            "type": "function",
                            "function": {"name": "get_cart", "arguments": "{}"},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def initialized(tmp_path):
    m = implementation()
    assert hasattr(m, "attach_smoke_models"), "Bound SDK composition is missing"
    g = m.SmokeBatch(tmp_path / "batch.json", proposal(), "b" * 64)
    g.arm("contract-A")
    g.initialized(str(uuid4()), "test_" + uuid4().hex, "cp_" + uuid4().hex)
    scope = CallScope(uuid4(), uuid4(), uuid4(), uuid4())
    g.bind_actor(str(scope.user_id), str(scope.store_id))
    g.bind_thread(str(scope.thread_id))
    g.start_episode()
    app = FastAPI()
    app.state.settings = SimpleNamespace()
    return m, g, app, scope


@pytest.mark.parametrize(
    "fault",
    [
        "ok",
        "503",
        "timeout",
        "json",
        "arguments",
        "usage",
        "model",
        "required",
        "type",
        "unknown_tool",
        "usage_inconsistent",
        "redirect",
        "argument_json",
    ],
)
async def test_sdk_fail_closed_and_no_second_provider_request(tmp_path, fault):
    m, gate, app, scope = initialized(tmp_path)
    sent = []

    def wire(request):
        # Reservation must already exist on disk before any HTTP reaches this peer.
        rows = json.loads((tmp_path / "ledger.json").read_text())["attempts"]
        assert len(rows) == 1 and rows[0]["state"] == "RESERVED"
        sent.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC_CREDENTIAL_MUST_NOT_BE_LOGGED")
        if fault == "503":
            return httpx.Response(503, json={"error": "synthetic"})
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://unrelated.invalid/"})
        if fault == "json":
            return httpx.Response(200, content=b"{")
        data = response()
        if fault == "arguments":
            data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = '{"extra":1}'
        if fault in {"required", "type", "unknown_tool", "argument_json"}:
            fn = data["choices"][0]["message"]["tool_calls"][0]["function"]
            fn["name"] = (
                "get_product"
                if fault in {"required", "type"}
                else "not_declared"
                if fault == "unknown_tool"
                else "get_cart"
            )
            fn["arguments"] = (
                '{"product_id":42}'
                if fault == "type"
                else "{"
                if fault == "argument_json"
                else "{}"
            )
        if fault == "usage":
            data.pop("usage")
        if fault == "model":
            data["model"] = "wrong-model"
        if fault == "usage_inconsistent":
            data["usage"]["total_tokens"] = 999
        return httpx.Response(200, json=data)

    provider = await m.attach_smoke_models(
        app, gate, tmp_path, price(), lambda role: httpx.MockTransport(wire)
    )
    model = app.state.durable_single_model.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "get_cart",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_product",
                    "parameters": {
                        "type": "object",
                        "properties": {"product_id": {"type": "string", "format": "uuid"}},
                        "required": ["product_id"],
                        "additionalProperties": False,
                    },
                },
            },
        ]
    )
    try:
        with call_scope(scope):
            if fault == "ok":
                message = await model.ainvoke("CONTRACT_TEST_ONLY private prompt", max_tokens=100)
                assert message.tool_calls[0]["name"] == "get_cart"
            else:
                with pytest.raises(RunStopped):
                    await model.ainvoke("CONTRACT_TEST_ONLY private prompt", max_tokens=100)
                with pytest.raises(RunStopped):
                    await model.ainvoke("must never send", max_tokens=100)
        row = provider.ledger.read()["attempts"][0]
        assert len(sent) == 1
        assert row["state"] == ("SETTLED" if fault == "ok" else "STOPPED")
        if fault != "ok":
            assert row["usage"] == "UNKNOWN" and row["held_cny"] == "2.097952"
            assert gate.read()["stop_code"]
        text = (tmp_path / "ledger.json").read_text() + (tmp_path / "batch.json").read_text()
        assert "private prompt" not in text and "SYNTHETIC_CREDENTIAL" not in text
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "change",
    [{"checked_at": "2020-01-01T00:00:00+00:00"}, {"model": "other"}, {"peak_output": "4"}],
)
async def test_current_model_and_peak_price_required_before_constructing_sender(tmp_path, change):
    m, gate, app, _ = initialized(tmp_path)
    with pytest.raises(m.SmokeStopped):
        await m.attach_smoke_models(
            app,
            gate,
            tmp_path,
            price() | change,
            lambda role: httpx.MockTransport(lambda r: httpx.Response(200)),
        )
    assert not (tmp_path / "ledger.json").exists()


async def test_no_provider_request_after_episode_has_finished(tmp_path):
    m, gate, app, scope = initialized(tmp_path)
    sent = []

    def wire(request):
        sent.append(request)
        return httpx.Response(200, json=response())

    provider = await m.attach_smoke_models(
        app, gate, tmp_path, price(), lambda role: httpx.MockTransport(wire)
    )
    gate.end_episode()
    try:
        with call_scope(scope), pytest.raises(RunStopped, match="MODEL_AFTER_EPISODE_FORBIDDEN"):
            await app.state.durable_single_model.ainvoke("CONTRACT_TEST_ONLY", max_tokens=100)
        assert sent == []
        assert provider.ledger.read()["attempts"] == []
    finally:
        await provider.close()


@pytest.mark.parametrize("kind", ["http", "cost"])
async def test_native_pre_send_http_and_cost_caps(tmp_path, kind):
    m, gate, app, scope = initialized(tmp_path)
    sent = []

    def wire(request):
        sent.append(request)
        data = response()
        data["choices"][0] = {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "CONTRACT_TEST_ONLY"},
        }
        if kind == "cost":
            data["usage"] = {
                "prompt_tokens": 1048576,
                "completion_tokens": 20,
                "total_tokens": 1048596,
            }
        return httpx.Response(200, json=data)

    provider = await m.attach_smoke_models(
        app, gate, tmp_path, price(), lambda role: httpx.MockTransport(wire)
    )
    bound = 12 if kind == "http" else 1
    try:
        with call_scope(scope):
            for _ in range(bound):
                await app.state.durable_single_model.ainvoke("CONTRACT_TEST_ONLY", max_tokens=100)
            with pytest.raises(RunStopped, match="PLAYGROUND_BUDGET_EXHAUSTED"):
                await app.state.durable_single_model.ainvoke(
                    "no second illegal send", max_tokens=100
                )
        assert len(sent) == bound
        assert len(provider.ledger.read()["attempts"]) == bound
    finally:
        await provider.close()


@pytest.mark.parametrize("kind", ["reserve", "settle"])
async def test_ledger_io_failure_halts_without_automatic_resend(tmp_path, monkeypatch, kind):
    m, gate, app, scope = initialized(tmp_path)
    sent = []

    def wire(request):
        sent.append(request)
        return httpx.Response(200, json=response())

    provider = await m.attach_smoke_models(
        app, gate, tmp_path, price(), lambda role: httpx.MockTransport(wire)
    )
    original = provider.ledger._write

    def fail(data):
        if data["attempts"] and data["attempts"][-1]["state"] == (
            "RESERVED" if kind == "reserve" else "SETTLED"
        ):
            raise OSError("synthetic ledger fault; never log payload")
        return original(data)

    monkeypatch.setattr(provider.ledger, "_write", fail)
    try:
        model = app.state.durable_single_model.bind_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_cart",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        )
        with call_scope(scope), pytest.raises(RunStopped):
            await model.ainvoke("CONTRACT_TEST_ONLY", max_tokens=100)
        assert len(sent) == (kind == "settle")
        assert gate.read()["stop_code"]
        with call_scope(scope), pytest.raises(RunStopped):
            await model.ainvoke("never resend", max_tokens=100)
        assert len(sent) == (kind == "settle")
    finally:
        await provider.close()
