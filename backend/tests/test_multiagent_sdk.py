"""Actual provider SDK + create_agent + StateGraph, with an in-memory HTTP transport."""

import json

import httpx
from multiagent_helpers import install, send

from agentmall.infra.llm import deepseek_model


async def test_real_sdk_routing_and_tool_loop_offline(env, buyer):
    requests = []
    supervisor_calls = 0

    def respond(request):
        nonlocal supervisor_calls
        body = json.loads(request.content)
        requests.append(body)
        assert 0 < body.get("max_tokens", body.get("max_completion_tokens")) <= 2048
        assert env[2].state.engine.pool.checkedout() == 0
        names = {t["function"]["name"] for t in body["tools"]}
        message = {"role": "assistant", "content": ""}
        if names == {"route"}:
            supervisor_calls += 1
            state = json.loads(body["messages"][-1]["content"])
            args = (
                {"terminal": "finish"}
                if supervisor_calls == 2
                else {
                    "tasks": [
                        {
                            "subtask_id": "search",
                            "target": "shopping",
                            "goal": "find_products",
                            "constraints": state["canonical_constraints"],
                            "read_only": True,
                        }
                    ]
                }
            )
            name = "route"
        elif body["messages"][-1]["role"] == "tool":
            assert body["messages"][-1]["tool_call_id"] == "sdk_2"
            message["content"] = "商品已检索，未创建订单"
            name = None
        else:
            assert names == {"retrieve_products", "get_product"}
            name, args = "retrieve_products", {"query": "静音键盘"}
        if name:
            message["tool_calls"] = [
                {
                    "id": "sdk_" + str(len(requests)),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": "offline-sdk-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if name else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport, trust_env=False) as client:
        async with httpx.AsyncClient(transport=transport, trust_env=False) as async_client:
            models = {
                role: deepseek_model(
                    "offline-placeholder", http_client=client, http_async_client=async_client
                )
                for role in ("supervisor", "shopping", "order", "aftersales")
            }
            trace = await install(env, models)
            result = await send(env, buyer, message="搜索300元以内静音键盘")
            assert result["error_codes"] == [], (result, trace)
            assert result["budget"]["used"]["models"] == len(requests) == 3
            assert result["budget"]["used"]["tools"] == 1
            assert any(f["kind"] == "product" for f in result["facts"])
            assert result["proposal_ids"] == []
