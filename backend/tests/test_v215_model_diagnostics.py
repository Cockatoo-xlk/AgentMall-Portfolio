"""CONTRACT_TEST_ONLY: safe future diagnostics, never a historical episode replay."""

import asyncio
import json
import re
import warnings
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from t09_helpers import durable_env as durable_env

from agentmall.agents.budgets import GraphBudget, RunStopped
from agentmall.agents.model_control import model_call
from agentmall.infra.llm import deepseek_model
from agentmall.infra.observability import public_summary


def runtime(model):
    r = SimpleNamespace(models={"supervisor": model}, budget=GraphBudget(), trace={"events": []})
    r.event = lambda kind, **data: r.trace["events"].append({"kind": kind, **data})
    return r


async def test_model_attempt_has_correlated_start_end_without_raw_content():
    r = runtime(SimpleNamespace(max_retries=0))

    async def invoke(cap):
        return AIMessage(
            content="CONTRACT_TEST_ONLY_PRIVATE",
            usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        )

    await model_call(r, "supervisor", invoke)
    start, end = r.trace["events"]
    assert re.fullmatch(r"[0-9a-f]{32}", start.get("model_request_id", ""))
    assert start["model_request_id"] == end["model_request_id"]
    assert "CONTRACT_TEST_ONLY_PRIVATE" not in json.dumps(r.trace)


async def test_sdk_receipt_captures_schema_response_and_usage_without_body():
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-contract-v215",
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "SYNTHETIC_PRIVATE_RESPONSE"},
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 7, "total_tokens": 37},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as sync:
            model = deepseek_model("SYNTHETIC_NOT_LIVE", http_client=sync, http_async_client=client)
            bound = model.bind_tools(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "route",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ]
            )
            r = runtime(model)
            await model_call(
                r,
                "supervisor",
                lambda cap: bound.ainvoke(
                    [HumanMessage(content="SYNTHETIC_PRIVATE_PROMPT")], max_tokens=cap
                ),
            )
    end = r.trace["events"][-1]
    assert re.fullmatch(r"[0-9a-f]{64}", end.get("tool_schema_sha256", ""))
    assert re.fullmatch(r"[0-9a-f]{64}", end.get("response_body_sha256", ""))
    assert end["provider_response_id"] == "chatcmpl-contract-v215"
    assert end["provider_usage_state"] == "OBSERVED_VALID"
    assert end["output_budget_state"] == "RECONCILED"
    assert end["observed_provider_usage"] == {
        "input_tokens": 30,
        "output_tokens": 7,
        "total_tokens": 37,
    }
    assert len(seen) == 1 and seen[0]["thinking"] == {"type": "disabled"}
    assert all(
        secret not in json.dumps(r.trace)
        for secret in [
            "SYNTHETIC_PRIVATE_PROMPT",
            "SYNTHETIC_PRIVATE_RESPONSE",
            "SYNTHETIC_NOT_LIVE",
        ]
    )


async def test_sdk_parse_failure_preserves_observation_but_not_budget_settlement():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-invalid-v215",
                "model": "deepseek-flash",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": "INVALID_MESSAGE_CONTRACT"}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as sync:
            model = deepseek_model("SYNTHETIC_NOT_LIVE", http_client=sync, http_async_client=client)
            r = runtime(model)
            with pytest.raises(RunStopped, match="MODEL_RESPONSE_INVALID"):
                await model_call(
                    r,
                    "supervisor",
                    lambda cap: model.ainvoke([HumanMessage(content="SYNTHETIC")], max_tokens=cap),
                )
    end = r.trace["events"][-1]
    assert end["provider_usage_state"] == "OBSERVED_VALID"
    assert end["output_budget_state"] == "UNRESOLVED"
    assert end["diagnostic_stage"] == "SDK_RESPONSE_PARSE"
    assert r.budget.used["models"] == 1 and r.budget.used["output_tokens"] == 2048
    assert end["usage"] == "UNKNOWN"


async def test_malformed_response_does_not_echo_private_body_through_serializer_warnings():
    canary = "SYNTHETIC_PRIVATE_RESPONSE_CANARY"

    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-private-warning",
                "model": "deepseek-flash",
                "choices": [{"index": 0, "finish_reason": "stop", "message": canary}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
        )

    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as sync:
                model = deepseek_model(
                    "SYNTHETIC_NOT_LIVE", http_client=sync, http_async_client=client
                )
                r = runtime(model)
                with pytest.raises(RunStopped, match="MODEL_RESPONSE_INVALID"):
                    await model_call(
                        r,
                        "supervisor",
                        lambda cap: model.ainvoke(
                            [HumanMessage(content="SYNTHETIC")], max_tokens=cap
                        ),
                    )
    assert all(canary not in str(w.message) for w in emitted)
    assert canary not in json.dumps(r.trace)


def test_model_diagnostics_public_whitelist_rejects_forged_values():
    d = public_summary(
        "model_end",
        {
            "model_request_id": "a" * 32,
            "tool_schema_sha256": "b" * 64,
            "response_body_sha256": "c" * 64,
            "tool_schema_version": "V215_TOOL_SCHEMA_V1",
            "provider_usage_state": "OBSERVED_VALID",
            "output_budget_state": "UNRESOLVED",
            "observed_provider_usage": {"input_tokens": 30, "output_tokens": 7, "total_tokens": 37},
            "provider_response_id": "chatcmpl-safe",
            "prompt": "PRIVATE",
            "authorization": "PRIVATE",
            "arguments": {"address": "PRIVATE"},
        },
    )
    assert d["model_request_id"] == "a" * 32
    assert d["observed_provider_usage"]["total_tokens"] == 37
    assert "PRIVATE" not in json.dumps(d)
    assert "response_body_sha256" not in public_summary(
        "model_end", {"response_body_sha256": "PRIVATE"}
    )
    assert "provider_response_id" not in public_summary(
        "model_end", {"provider_response_id": "chatcmpl-sk-PRIVATE"}
    )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": 3, "completion_tokens": -1, "total_tokens": 2},
        {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 9},
        {"prompt_tokens": 3, "completion_tokens": 2049, "total_tokens": 2052},
    ],
)
def test_invalid_observed_usage_is_never_a_settlement_receipt(raw):
    from agentmall.infra.model_diagnostics import capture_model_diagnostics, observe_response

    with capture_model_diagnostics() as receipt:
        observe_response({"usage": raw})
        d = public_summary("model_end", receipt.summary())
    assert d["provider_usage_state"] in {"UNKNOWN", "INVALID"}
    assert "observed_provider_usage" not in d
    assert d["usage"] == "UNKNOWN"
    assert "actual_cost" not in d


@pytest.mark.parametrize("value", [[], {}, ["OBSERVED_VALID"], 12, None])
def test_malformed_metadata_cannot_break_public_projection(value):
    from agentmall.infra.model_diagnostics import public_model_diagnostics

    assert public_model_diagnostics(value) == {}
    d = public_model_diagnostics(
        {"diagnostic_stage": value, "provider_usage_state": value, "output_budget_state": value}
    )
    assert d == {}


async def test_parallel_models_have_distinct_correlated_receipts():
    from agentmall.infra.model_diagnostics import CURRENT, observe_request

    async def attempt(name):
        r = runtime(SimpleNamespace(max_retries=0))

        async def invoke(cap):
            observe_request({"tools": [{"name": name}], "max_tokens": cap})
            await asyncio.sleep(0)
            return AIMessage(
                content="",
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            )

        await model_call(r, "supervisor", invoke)
        return r.trace["events"][-1]

    a, b = await asyncio.gather(attempt("one"), attempt("two"))
    assert a["model_request_id"] != b["model_request_id"]
    assert a["tool_schema_sha256"] != b["tool_schema_sha256"]
    assert CURRENT.get() is None


async def test_failed_sdk_node_diagnostics_are_fenced_durable_and_deduplicated(durable_env, buyer):
    from uuid import UUID

    from conftest import row
    from multiagent_helpers import install, make_models, route
    from t09_helpers import start, thread

    from agentmall.agents.durable_budget import DurableBudget
    from agentmall.agents.locking import claim_execution, thread_lock
    from agentmall.agents.models import AgentRun
    from agentmall.infra.errors import DomainError

    env = durable_env
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message="结束本次CONTRACT_TEST_ONLY，不购买")).json()
    journal_before = row(env[1], "SELECT node_journal FROM agent_runs WHERE id=:id", id=run["id"])[
        "node_journal"
    ]

    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-durable-v215",
                "model": "deepseek-flash",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": "PRIVATE_INVALID_MESSAGE"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    async with thread_lock(env[3], tid) as lock:
        async with env[2].state.sessions.begin() as session:
            record = await session.get(AgentRun, UUID(run["id"]))
            fence = await claim_execution(session, record, lock, env[2].state.sessions)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as sync:
                model = deepseek_model(
                    "SYNTHETIC_NOT_LIVE", http_client=sync, http_async_client=client
                )
                r = runtime(model)
                r.budget = DurableBudget(fence)
                await r.budget.reload()
                with pytest.raises(RunStopped, match="MODEL_RESPONSE_INVALID"):
                    await model_call(
                        r,
                        "supervisor",
                        lambda cap: model.ainvoke(
                            [HumanMessage(content="PRIVATE_PROMPT")], max_tokens=cap
                        ),
                    )
        attempt = r.trace["events"][-1]
        assert attempt["error_code"] == "MODEL_RESPONSE_INVALID"
        assert attempt["output_budget_state"] == "UNRESOLVED"
        reconstructed = DurableBudget(fence)
        await reconstructed.reload()
        count = row(
            env[1],
            "SELECT count(*) n FROM run_events WHERE run_id=:id AND event_type='model_end'",
            id=run["id"],
        )["n"]
        await asyncio.gather(
            reconstructed.record_model_event(attempt), r.budget.record_model_event(attempt)
        )
        assert (
            row(
                env[1],
                "SELECT count(*) n FROM run_events WHERE run_id=:id AND event_type='model_end'",
                id=run["id"],
            )["n"]
            == count
        )
        stored = row(
            env[1],
            "SELECT payload_summary FROM run_events WHERE run_id=:id AND event_type='model_end' "
            "ORDER BY seq DESC LIMIT 1",
            id=run["id"],
        )["payload_summary"]
        assert stored["model_request_id"] == attempt["model_request_id"]
        assert stored["provider_usage_state"] == "OBSERVED_VALID"
        assert stored["output_budget_state"] == "UNRESOLVED"
        assert "PRIVATE" not in json.dumps(stored)
        assert (
            row(env[1], "SELECT node_journal FROM agent_runs WHERE id=:id", id=run["id"])[
                "node_journal"
            ]
            == journal_before
        )
    with pytest.raises(DomainError) as exc:
        await reconstructed.record_model_event({**attempt, "attempt": 99})
    assert exc.value.code == "STALE_EXECUTOR"
