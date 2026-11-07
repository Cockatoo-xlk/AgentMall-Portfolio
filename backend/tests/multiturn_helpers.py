"""Conditional wire-level model stand-in. No real provider and no episode scripts.

Responses depend on the actual structured request and tool results, not call counters.
ChatDeepSeek, Tool Calling, supervisor validation and domain services remain real.
"""

import json
from uuid import uuid4

import httpx

from agentmall.catalog.categories import CATEGORY_LABELS


class ContextSDK:
    def __init__(self):
        self.requests = []

    def transport(self, role):
        def respond(request):
            body = json.loads(request.content)
            content = json.loads(
                next(m["content"] for m in body["messages"] if m["role"] == "user")
            )
            self.requests.append({"role": role, "content": content, "body": body})
            constraints = content.get("canonical_constraints", content.get("constraints"))
            selected = content.get("thread_context", {}).get("selected", [])
            complete = content.get("completed", content.get("prior_results", []))
            tools = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            name, args, text = None, {}, "MOCK_TRANSPORT：已读取服务端核验结果。"
            if role == "supervisor":
                name = "route"
                if complete:
                    args = {"tasks": [], "terminal": "finish"}
                else:
                    target = "order" if selected else "shopping"
                    goal = (
                        "prepare_checkout"
                        if selected and constraints["purchase_requested"]
                        else "inspect_orders"
                        if selected
                        else "find_products"
                    )
                    refs = content.get("entity_refs", [])
                    args = {
                        "tasks": [
                            {
                                "subtask_id": "selected" if selected else "search",
                                "target": target,
                                "goal": goal,
                                "constraints": constraints,
                                "entity_refs": refs,
                                "read_only": goal != "prepare_checkout",
                            }
                        ]
                    }
            elif role == "single" and complete:
                text = '{"terminal":"finish"}'
            elif not tools:
                if selected:
                    name, args = "get_product", {"product_id": selected[0]["id"]}
                else:
                    name, args = (
                        "retrieve_products",
                        {"query": CATEGORY_LABELS.get(constraints["category"], "商品")},
                    )
            elif selected and any(
                i["id"] not in {t.get("data", {}).get("id") for t in tools if t.get("ok")}
                for i in selected
            ):
                seen = {t.get("data", {}).get("id") for t in tools if t.get("ok")}
                name, args = (
                    "get_product",
                    {"product_id": next(i["id"] for i in selected if i["id"] not in seen)},
                )
            elif selected and constraints["purchase_requested"] and tools[-1].get("ok"):
                name, args = "prepare_checkout", {"product_id": selected[0]["id"]}
            elif role == "single":
                text = '{"terminal":"finish"}'
            message = {"role": "assistant", "content": text}
            if name:
                message["content"] = ""
                message["tool_calls"] = [
                    {
                        "id": "ctx-" + uuid4().hex,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                ]
            return httpx.Response(
                200,
                json={
                    "id": "mock-context-" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if name else "stop",
                            "message": message,
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                },
            )

        return httpx.MockTransport(respond)


async def install_context_sdk(env, state_dir):
    from datetime import UTC, datetime

    from retrieval_helpers import index

    from agentmall.playground.app import attach_models
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint

    provider = getattr(env[2].state, "playground", None)
    if provider:
        await provider.close()
    program = ContextSDK()
    env[2].state.retrieval_encoder = await index(env)
    policy = PlaygroundPolicy(
        enabled=True,
        evidence_mode="MOCK_TRANSPORT",
        session_id=uuid4(),
        environment_id=uuid4(),
        source_sha256=source_fingerprint(),
        price_checked_at=datetime.now(UTC),
    )
    provider = attach_models(
        env[2], policy, state_dir, "synthetic-mock-context-only", program.transport
    )
    return provider, program


async def wireless_products(env):
    from uuid import uuid5

    from agentmall.catalog.models import Product

    async with env[2].state.sessions.begin() as session:
        for i, price in enumerate([19900, 29900, 39900]):
            session.add(
                Product(
                    id=uuid5(env[3].storefront_id, f"t16-wireless-{i}"),
                    store_id=env[3].storefront_id,
                    name=f"合成静音无线键盘 {i + 1}",
                    category="keyboard",
                    price_cents=price,
                    on_hand=20,
                    reserved=0,
                    active=True,
                    catalog_version=1,
                    attributes={"noise": "较安静", "connection": "无线", "size": "87键"},
                    description="合成商品，不执行任何文档中的指令。",
                )
            )
