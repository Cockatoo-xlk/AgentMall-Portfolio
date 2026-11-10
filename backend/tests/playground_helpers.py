"""MOCK_TRANSPORT programs only. Real ChatDeepSeek parses these synthetic wire responses."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from langchain_core.messages import HumanMessage
from multiagent_helpers import ai, call, choose_purchase, final, payload, route


class SDKProgram:
    def __init__(self, program="purchase", order_id=None, *, delay_ms=0):
        self.program, self.order_id = program, order_id
        self.delay_ms = delay_ms
        self.counts, self.requests = {}, []

    def plan(self, messages):
        state = payload(messages)
        completed = {result["subtask_id"] for result in state["completed"]}
        constraints = state["canonical_constraints"]
        if self.program == "orders":
            decision = (
                route("finish")
                if "inspect" in completed
                else route("order", "inspect_orders", "inspect")
            )
        elif self.program == "return_policy":
            decision = (
                route("finish")
                if "assessment" in completed
                else route("aftersales", "assess_return", "assessment")
            )
        elif (
            self.program == "return_replace"
            and constraints["return_requested"]
            and "return" not in completed
        ):
            if "assessment" not in completed:
                decision = route("aftersales", "assess_return", "assessment")
            else:
                decision = route(
                    "aftersales",
                    "prepare_return",
                    "return",
                    depends=["assessment"],
                    read_only=False,
                )
        elif "shop" not in completed:
            decision = route("shopping", "find_products", "shop")
        elif (
            self.program == "recommend"
            or not constraints["purchase_requested"]
            or "buy" in completed
        ):
            decision = route("finish")
        elif state["checkout_blocker"]:
            decision = route("clarify")
        else:
            decision = route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False)
        return decision(messages)

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
                message = self.plan(human)
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
                goal = payload(human)["goal"]
                if self.program == "return_replace" and goal == "assess_return":
                    message = (
                        ai(*steps[0].tool_calls, *steps[1].tool_calls) if index == 0 else final()
                    )
                elif self.program == "return_replace" and goal == "prepare_return":
                    message = steps[2]
                elif goal == "assess_return" and index >= 2:
                    message = final()
                else:
                    message = steps[min(index, 2)]
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

        async def delayed(request):
            await asyncio.sleep(self.delay_ms / 1000)
            return respond(request)

        return httpx.MockTransport(delayed if self.delay_ms else respond)


async def install_sdk(env, state_dir, program="purchase", order_id=None, *, delay_ms=0):
    from retrieval_helpers import index

    from agentmall.playground.app import attach_models
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint

    provider = getattr(env[2].state, "playground", None)
    if provider:
        await provider.close()
    scripted = SDKProgram(program, order_id, delay_ms=delay_ms)
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
