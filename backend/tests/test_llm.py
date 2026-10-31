import json
from decimal import Decimal

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langsmith import tracing_context

from agentmall.infra.llm import AgentStopped, Budget, deepseek_model, load_live_key


def test_real_key_inaccessible_and_http_blocked():
    with pytest.raises(AgentStopped, match="KEY_UNAVAILABLE"):
        load_live_key()
    with pytest.raises(AssertionError, match="forbids"):
        httpx.get("https://api.deepseek.com")


def test_budget_reserves_before_send_and_unknown_usage_stops():
    saved = []
    budget = Budget(persist=lambda: saved.append("saved"))
    budget.start()
    assert saved == ["saved"] and budget.held == Decimal("2.113536")
    with pytest.raises(AgentStopped, match="USAGE_UNKNOWN"):
        budget.finish(AIMessage(content="unknown"))
    with pytest.raises(AgentStopped, match="BUDGET_EXHAUSTED"):
        budget.start()
    assert len(budget.attempts) == 1


def usage_message(usage):
    return AIMessage(
        content="",
        usage_metadata=usage,
        response_metadata={
            "token_usage": {
                "prompt_tokens": usage["input_tokens"],
                "completion_tokens": usage["output_tokens"],
                "total_tokens": usage["total_tokens"],
            }
        },
    )


def test_budget_settlement_and_request_cap():
    budget = Budget(max_calls=2)
    for _ in range(2):
        budget.start()
        budget.finish(
            usage_message({"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
        )
    assert budget.held == Decimal("0.00056")
    with pytest.raises(AgentStopped, match="BUDGET_EXHAUSTED"):
        budget.start()


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1, "output_tokens": 0, "total_tokens": -1},
        {"input_tokens": 10, "output_tokens": 2049, "total_tokens": 2059},
        {"input_tokens": 10, "output_tokens": 2, "total_tokens": 13},
    ],
)
def test_invalid_usage_keeps_reservation(usage):
    budget = Budget()
    budget.start()
    with pytest.raises(AgentStopped, match="USAGE_INVALID"):
        budget.finish(usage_message(usage))
    assert budget.held == Decimal("2.113536")


async def test_deepseek_sdk_real_wire_protocol_with_mock_transport():
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.host == "api.deepseek.com"
        assert body["model"] == "deepseek-flash" and body["thinking"] == {"type": "disabled"}
        assert body.get("max_tokens", body.get("max_completion_tokens")) == 2048
        assert "parallel_tool_calls" not in body
        message = {"role": "assistant", "content": "完成"}
        if len(requests) == 1:
            message["tool_calls"] = [
                {
                    "id": "call_sdk_1",
                    "type": "function",
                    "function": {"name": "get_product", "arguments": '{"product_id":"synthetic"}'},
                }
            ]
        else:
            assert body["messages"][-1]["role"] == "tool"
            assert body["messages"][-1]["tool_call_id"] == "call_sdk_1"
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_cache_hit_tokens": 10,
                    "prompt_cache_miss_tokens": 90,
                },
            },
        )

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport, trust_env=False) as sync_client:
        async with httpx.AsyncClient(transport=transport, trust_env=False) as async_client:
            model = deepseek_model(
                "offline-placeholder", http_client=sync_client, http_async_client=async_client
            )
            assert model.root_async_client.max_retries == 0
            tool = {
                "type": "function",
                "function": {
                    "name": "get_product",
                    "description": "fact",
                    "parameters": {
                        "type": "object",
                        "properties": {"product_id": {"type": "string"}},
                        "required": ["product_id"],
                    },
                },
            }
            with tracing_context(enabled=False):
                bound = model.bind_tools([tool])
                first = await bound.ainvoke([HumanMessage(content="synthetic")])
                assert first.tool_calls[0]["id"] == "call_sdk_1"
                second = await bound.ainvoke(
                    [
                        HumanMessage(content="synthetic"),
                        first,
                        ToolMessage(content='{"ok":true}', tool_call_id="call_sdk_1"),
                    ]
                )
            assert second.content == "完成" and len(requests) == 2
            assert first.usage_metadata["input_tokens"] == 100
            assert first.usage_metadata["input_token_details"]["cache_read"] == 10


@pytest.mark.parametrize(
    "raw_usage",
    [
        {"completion_tokens": 20},
        {"prompt_cache_hit_tokens": 100},
        {"prompt_tokens": None, "completion_tokens": 20, "total_tokens": 20},
    ],
)
async def test_sdk_synthesized_zero_usage_does_not_release_budget(raw_usage):
    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "done"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": raw_usage,
            },
        )

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport, trust_env=False) as sync_client:
        async with httpx.AsyncClient(transport=transport, trust_env=False) as async_client:
            model = deepseek_model(
                "offline-placeholder", http_client=sync_client, http_async_client=async_client
            )
            budget = Budget()
            budget.start()
            with tracing_context(enabled=False):
                response = await model.ainvoke("synthetic")
            with pytest.raises(AgentStopped, match="USAGE_"):
                budget.finish(response)
            assert budget.held == Decimal("2.113536")
            assert budget.attempts[0]["state"] == "RESERVED"
            with pytest.raises(AgentStopped, match="BUDGET_EXHAUSTED"):
                budget.start()
