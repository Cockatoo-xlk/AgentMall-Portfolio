"""CONTRACT_TEST_ONLY: SDK parse failures stop once; accepted decisions stay committed."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from aftersales_helpers import delivered_order
from conftest import row
from langchain_core.messages import HumanMessage
from openai import InternalServerError
from playground_helpers import SDKProgram
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env
from test_v213_l2_sdk import direct_sdk

from agentmall.agents.budgets import GraphBudget, RunStopped
from agentmall.agents.model_control import model_call
from agentmall.infra.llm import deepseek_model


def runtime(model):
    result = SimpleNamespace(
        models={"supervisor": model}, budget=GraphBudget(), trace={"events": []}
    )
    result.event = lambda kind, **data: result.trace["events"].append({"kind": kind, **data})
    return result


async def test_invalid_http_json_stops_as_response_parse_failure_without_usage_or_hash():
    """A decoder failure before _create_chat_result must retain the full reservation."""

    def respond(request):
        return httpx.Response(
            200, content=b'{"private_canary":', headers={"Content-Type": "application/json"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as sync:
            model = deepseek_model("SYNTHETIC_NOT_LIVE", http_client=sync, http_async_client=client)
            observed = runtime(model)
            with pytest.raises(RunStopped, match="^MODEL_RESPONSE_INVALID$"):
                await model_call(
                    observed,
                    "supervisor",
                    lambda cap: model.ainvoke([HumanMessage(content="SYNTHETIC")], max_tokens=cap),
                )
    event = observed.trace["events"][-1]
    assert event["diagnostic_stage"] == "SDK_RESPONSE_PARSE"
    assert event["error_code"] == "MODEL_RESPONSE_INVALID"
    assert event["response_body_sha256"] == event["provider_response_id"] == "UNKNOWN"
    assert event["provider_usage_state"] == "UNKNOWN"
    assert event["usage"] == "UNKNOWN" and "observed_provider_usage" not in event
    assert event["output_budget_state"] == "UNRESOLVED"
    assert observed.budget.used["models"] == 1
    assert observed.budget.used["output_tokens"] == 2048
    assert "private_canary" not in json.dumps(observed.trace)


async def test_http_status_failure_is_not_relabelled_as_sdk_response_parse_failure():
    def respond(request):
        return httpx.Response(503, json={"error": {"message": "SYNTHETIC_UNAVAILABLE"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as sync:
            model = deepseek_model("SYNTHETIC_NOT_LIVE", http_client=sync, http_async_client=client)
            observed = runtime(model)
            with pytest.raises(InternalServerError):
                await model_call(
                    observed,
                    "supervisor",
                    lambda cap: model.ainvoke([HumanMessage(content="SYNTHETIC")], max_tokens=cap),
                )
    event = observed.trace["events"][-1]
    assert "diagnostic_stage" not in event
    assert event["error_code"] == "MODEL_INVOKE_FAILED"
    assert observed.budget.used["models"] == 1
    assert observed.budget.used["output_tokens"] == 2048


@pytest.mark.parametrize("fault", ["message", "json"])
async def test_supervisor_parse_failure_after_confirmation_makes_same_resume_read_only(
    durable_env, buyer, product, monkeypatch, fault
):
    """An accepted Resume must not spend another model reservation on identical replay."""
    env = durable_env
    original_order = await delivered_order(env[0], buyer, product)
    transport = SDKProgram.transport

    def with_failure(program, role):
        base = transport(program, role)

        async def respond(request):
            response = await base.handle_async_request(request)
            if role != "supervisor":
                return response
            body = json.loads(request.content)
            state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            if not any(outcome["status"] == "EXECUTED" for outcome in state["action_outcomes"]):
                return response
            if fault == "json":
                return httpx.Response(
                    200, content=b"{", headers={"Content-Type": "application/json"}
                )
            malformed = response.json()
            malformed["choices"][0]["message"] = "SYNTHETIC_INVALID_SUPERVISOR_MESSAGE"
            return httpx.Response(200, json=malformed)

        return httpx.MockTransport(respond)

    monkeypatch.setattr(SDKProgram, "transport", with_failure)
    wire = SDKProgram("return_replace", original_order["id"])
    clients = await direct_sdk(env, wire)
    try:
        tid = await thread(env, buyer)
        first = (
            await start(
                env,
                buyer,
                tid,
                message=f"订单{original_order['id']}质量问题，申请退货并推荐另一款静音键盘。",
            )
        ).json()
        assert first["status"] == "WAITING_INPUT", first
        assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        confirmation_id = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        request_id = str(uuid4())
        done = (await resume(env, buyer, tid, first, confirmation_id, request_id)).json()
        assert done["status"] == "PARTIAL", done
        assert done["pending_confirmation"] is None
        assert "MODEL_RESPONSE_INVALID" in done["result"]["error_codes"]
        assert (
            row(env[1], "SELECT count(*) n FROM aftersales_cases WHERE status='REQUESTED'")["n"]
            == 1
        )
        assert (
            row(env[1], "SELECT consumed_at FROM confirmations WHERE id=:id", id=confirmation_id)[
                "consumed_at"
            ]
            is not None
        )
        assert row(env[1], "SELECT count(*) n FROM orders WHERE status='PENDING_PAYMENT'")["n"] == 0
        events_before = row(
            env[1], "SELECT count(*) n FROM run_events WHERE run_id=:id", id=done["id"]
        )["n"]
        replay = (await resume(env, buyer, tid, first, confirmation_id, request_id)).json()
        assert replay["budget"] == done["budget"]
        assert replay == done
        assert (
            row(env[1], "SELECT count(*) n FROM run_events WHERE run_id=:id", id=done["id"])["n"]
            == events_before
        )
        assert (
            row(env[1], "SELECT count(*) n FROM aftersales_cases WHERE status='REQUESTED'")["n"]
            == 1
        )
        journal = row(env[1], "SELECT resume_journal FROM agent_runs WHERE id=:id", id=done["id"])[
            "resume_journal"
        ]
        assert journal[request_id]["completed"] is True
    finally:
        await clients.aclose()
