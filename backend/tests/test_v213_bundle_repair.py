"""Actual SDK MockTransport, scoped Bundle tools and independent PostgreSQL assertions."""

import json
from uuid import uuid4

import httpx
from bundle_helpers import BundleSDK
from conftest import row
from retrieval_helpers import index
from t09_helpers import confirm, resume, thread
from t09_helpers import durable_env as durable_env
from test_bundle_shopping import MESSAGE
from worker_process_helpers import configure

from agentmall.seed import seed


async def test_bundle_write_goal_repair_requests_bundle_tool(durable_env, buyer, monkeypatch):
    env = durable_env
    original = BundleSDK.transport
    stages = []

    def transport(program, role):
        base = original(program, role)

        async def respond(request):
            body = json.loads(request.content)
            content = json.loads(
                next(m["content"] for m in body["messages"] if m["role"] == "user")
            )
            selected = content.get("thread_context", {}).get("selected_bundle")
            if role != "order" or not selected:
                return await base.handle_async_request(request)
            stage = len(stages)
            stages.append(stage)
            calls = []
            if stage == 0:
                calls = [("get_product", {"product_id": selected["items"][0]["id"]})]
            elif stage == 2:
                required = content["orchestration_feedback"]["required_tool"]
                assert required == "prepare_bundle_checkout"
                calls = [(required, {"bundle_id": selected["bundle_id"]})]
            message = {"role": "assistant", "content": "" if calls else "商品已经读取。"}
            if calls:
                message["tool_calls"] = [
                    {
                        "id": "repair-" + uuid4().hex,
                        "type": "function",
                        "function": {"name": n, "arguments": json.dumps(a)},
                    }
                    for n, a in calls
                ]
            return httpx.Response(
                200,
                json={
                    "id": "mock-" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "tool_calls" if calls else "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                },
            )

        return httpx.MockTransport(respond)

    monkeypatch.setattr(BundleSDK, "transport", transport)
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    await index(env)
    await configure(env[2])
    try:
        tid = await thread(env, buyer)
        for message in [MESSAGE, "就买这套，每样一件，送演示宿舍。"]:
            context = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()[
                "context"
            ]
            response = await env[0].post(
                f"/api/v1/agent/threads/{tid}/runs",
                headers=buyer,
                json={
                    "request_id": str(uuid4()),
                    "message": message,
                    "expected_context_version": context["version"],
                },
            )
            assert response.status_code == 201, response.text
        run = response.json()
        assert stages == [0, 1, 2], stages
        assert run["status"] == "WAITING_INPUT", run
        assert stages == [0, 1, 2]
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, run, cid)).json()
        assert done["status"] == "COMPLETED", done
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM order_items")["n"] == 4
        assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 4
    finally:
        await env[2].state.worker_close()
