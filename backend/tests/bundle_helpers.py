"""Offline SDK transport driven by trusted bundle tasks and actual tool receipts."""

import json
from uuid import uuid4

import httpx


class BundleSDK:
    def __init__(self):
        self.requests = []

    def transport(self, role):
        def respond(request):
            body = json.loads(request.content)
            content = json.loads(
                next(m["content"] for m in body["messages"] if m["role"] == "user")
            )
            self.requests.append({"role": role, "content": content, "body": body})
            c = content.get("canonical_constraints", content.get("constraints"))
            selected = content.get("thread_context", {}).get("selected_bundle")
            completed = content.get("completed", content.get("prior_results", []))
            tools = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            calls = []
            if role == "supervisor":
                composition = content.get("bundle_progress", {}).get("composition")
                if (
                    completed
                    and getattr(self, "clarify_budget", None) == c["bundle"]["budget_cents"]
                ):
                    plan = {"tasks": [], "terminal": "clarify"}
                elif completed and (selected or composition):
                    plan = {"tasks": [], "terminal": "finish"}
                else:
                    goal = "prepare_checkout" if c["purchase_requested"] else "find_products"
                    plan = {
                        "tasks": [
                            {
                                "subtask_id": "bundle-"
                                + str(content.get("thread_context", {}).get("version", 0)),
                                "target": "order" if c["purchase_requested"] else "shopping",
                                "goal": goal,
                                "constraints": c,
                                "entity_refs": content["entity_refs"],
                                "read_only": not c["purchase_requested"],
                            }
                        ]
                    }
                calls = [("route", plan)]
            elif role == "single" and completed:
                pass
            elif selected and c["purchase_requested"] and not tools:
                calls = [
                    (
                        "prepare_bundle_checkout",
                        {"bundle_id": getattr(self, "purchase_bundle_id", selected["bundle_id"])},
                    )
                ]
            elif not selected and c.get("bundle"):
                seen = {t.get("data", {}).get("category") for t in tools if t.get("ok")}
                calls = [
                    ("retrieve_bundle_candidates", {"category": part["category"]})
                    for part in c["bundle"]["parts"]
                    if part["category"] not in seen
                ][:4]
            message = {"role": "assistant", "content": "" if calls else '{"terminal":"finish"}'}
            if calls:
                message["tool_calls"] = [
                    {
                        "id": "bundle-" + uuid4().hex,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                    for name, args in calls
                ]
            return httpx.Response(
                200,
                json={
                    "id": "mock-bundle-" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if calls else "stop",
                            "message": message,
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                },
            )

        return httpx.MockTransport(respond)


async def install_bundle_sdk(env, state_dir):
    from datetime import UTC, datetime

    from retrieval_helpers import index

    from agentmall.playground.app import attach_models
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint
    from agentmall.seed import seed

    provider = getattr(env[2].state, "playground", None)
    if provider:
        await provider.close()
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    program = BundleSDK()
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
        env[2], policy, state_dir, "synthetic-mock-bundle-only", program.transport
    )
    return provider, program
