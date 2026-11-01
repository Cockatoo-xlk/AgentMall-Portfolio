"""MOCK_TRANSPORT programs only. Real ChatDeepSeek parses these synthetic wire responses."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from langchain_core.messages import HumanMessage
from multiagent_helpers import ai, call, choose_purchase, final, route


class SDKProgram:
    def __init__(self, program="purchase", order_id=None):
        self.program, self.order_id = program, order_id
        self.counts, self.requests = {}, []

    def transport(self, role):
        def respond(request):
            body = json.loads(request.content)
            index = self.counts.get(role, 0)
            self.counts[role] = index + 1
            self.requests.append({"role": role, "body": body})
            human = [
                HumanMessage(content=m["content"]) for m in body["messages"] if m["role"] == "user"
            ]
            if self.program == "timeout":
                raise httpx.ReadTimeout("synthetic provider error; never log this text")
            if self.program == "missing_usage":
                message = final()
            elif self.program == "malicious":
                message = ai(call("approve_payment", {"approved": True, "amount": 0}))
            elif role == "supervisor":
                steps = (
                    [route("order", "inspect_orders", "inspect"), route("finish")]
                    if self.program == "orders"
                    else [route("shopping", "find_products", "find"), route("finish")]
                    if self.program == "recommend"
                    else [
                        route("aftersales", "prepare_return", "return", read_only=False),
                        route("shopping", "find_products", "replacement"),
                        route(
                            "order",
                            "prepare_checkout",
                            "new",
                            depends=["replacement"],
                            read_only=False,
                        ),
                        route("finish"),
                    ]
                    if self.program == "return_replace"
                    else [
                        route("shopping", "find_products", "shop"),
                        route(
                            "order", "prepare_checkout", "buy", depends=["shop"], read_only=False
                        ),
                        route("finish"),
                    ]
                )
                message = steps[index](human)
            elif role == "shopping":
                message = (
                    ai(call("retrieve_products", {"query": "静音键盘"})) if index == 0 else final()
                )
            elif role == "aftersales":
                steps = [
                    ai(call("get_order", {"order_id": self.order_id})),
                    ai(
                        call(
                            "check_eligibility",
                            {"order_id": self.order_id, "reason_code": "QUALITY_ISSUE"},
                        ),
                        call(
                            "retrieve_policies",
                            {"order_id": self.order_id, "query": "质量问题退货期限"},
                        ),
                    ),
                    ai(
                        call(
                            "prepare_return",
                            {
                                "order_id": self.order_id,
                                "reason_code": "QUALITY_ISSUE",
                                "description": "合成按键故障",
                            },
                        )
                    ),
                ]
                message = steps[index]
            elif self.program == "orders" or role == "single":
                message = ai(call("list_orders")) if index == 0 else final('{"terminal":"finish"}')
            else:
                message = choose_purchase(human)
            calls = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": json.dumps(c["args"], ensure_ascii=False),
                    },
                }
                for c in message.tool_calls
            ]
            data = {
                "id": "chatcmpl-mock-" + uuid4().hex,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls" if calls else "stop",
                        "message": {
                            "role": "assistant",
                            "content": message.content,
                            **({"tool_calls": calls} if calls else {}),
                        },
                    }
                ],
            }
            if self.program != "missing_usage":
                data["usage"] = {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}
            return httpx.Response(200, json=data, headers={"x-request-id": "mock-" + uuid4().hex})

        return httpx.MockTransport(respond)


async def install_sdk(env, state_dir, program="purchase", order_id=None):
    from retrieval_helpers import index

    from agentmall.playground.app import attach_models
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint

    provider = getattr(env[2].state, "playground", None)
    if provider:
        await provider.close()
    scripted = SDKProgram(program, order_id)
    policy = PlaygroundPolicy(
        enabled=True,
        evidence_mode="MOCK_TRANSPORT",
        session_id=uuid4(),
        environment_id=uuid4(),
        source_sha256=source_fingerprint(),
        price_checked_at=datetime.now(UTC),
    )
    env[2].state.retrieval_encoder = await index(env)
    provider = attach_models(
        env[2], policy, state_dir, "synthetic-sdk-key-not-live", scripted.transport
    )
    return provider, scripted
