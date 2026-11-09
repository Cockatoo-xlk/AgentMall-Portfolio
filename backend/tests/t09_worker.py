"""Controlled offline child. Parent kills only this PID after a durable boundary marker."""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from multiagent_helpers import ai, assessment_reads, call, final, make_models, payload, route

from agentmall.infra.config import Settings
from agentmall.main import create_app

# No provider credentials or external sockets are available to a child.
for name in list(os.environ):
    if any(s in name.upper() for s in ("OPENAI", "DEEPSEEK", "LANGSMITH", "LANGCHAIN")):
        del os.environ[name]
original_connect = socket.socket.connect


def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
        raise AssertionError("T09 child forbids external network")
    return original_connect(sock, address)


socket.socket.connect = local_connect


async def main():
    task = json.loads(await asyncio.to_thread(Path(sys.argv[1]).read_text))
    settings = Settings(
        db_schema=task["schema"],
        checkpoint_schema=task["checkpoint"],
        database_url=Settings().test_database_url,
    )
    assert settings.db_schema.startswith("test_")
    app = create_app(settings)
    if task.get("order"):
        from retrieval_helpers import FixtureEncoder

        from agentmall.retrieval.ingest import index_policies, load_policies

        # The separated readonly assessment requires a real public policy source.
        app.state.retrieval_encoder = FixtureEncoder()
        async with app.state.sessions.begin() as session:
            await index_policies(session, load_policies(), app.state.retrieval_encoder)
    marker = Path(task["marker"])

    async def boundary(label):
        if task.get("boundary") == label:
            await asyncio.to_thread(marker.write_text, label)
            await asyncio.Event().wait()

    def decide(messages):
        state = payload(messages)
        if task.get("return_replace"):
            # Stateless restart of the same fixture workflow: L3 creates the
            # replacement proposal only after the return decision, not before it.
            completed = {r["subtask_id"] for r in state["completed"]}
            if "replacement" not in completed:
                return route("shopping", "find_products", "replacement")(messages)
            if "new" not in completed:
                return route(
                    "order", "prepare_checkout", "new", depends=["replacement"], read_only=False
                )(messages)
            return route("finish")(messages)
        if task.get("order") and "return" not in {r["subtask_id"] for r in state["completed"]}:
            if "assessment" not in {r["subtask_id"] for r in state["completed"]}:
                return route("aftersales", "assess_return", "assessment")(messages)
            return route(
                "aftersales", "prepare_return", "return", depends=["assessment"], read_only=False
            )(messages)
        return (
            route("finish")(messages)
            if state["completed"]
            else route("aftersales", "prepare_return", "return", read_only=False)(messages)
            if task.get("order")
            else route("order", "prepare_checkout", "buy", read_only=False)(messages)
        )

    def purchase(messages):
        return ai(call("prepare_checkout", {"product_id": task["product"]}))

    app.state.multi_models = make_models(
        supervisor=[decide, decide, decide],
        order=[purchase],
        shopping=[ai(call("get_product", {"product_id": task["product"]})), final()],
        aftersales=[
            *assessment_reads(task["order"]),
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": task["order"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "按键故障",
                    },
                )
            ),
        ]
        if task.get("order")
        else [],
    )
    from agentmall.agents import durable_graph, run_service
    from agentmall.agents.specialist_tools import SpecialistTools

    original_execute = SpecialistTools._execute

    async def execute(self, name, args):
        if name == "prepare_checkout":
            await boundary("before_proposal")
        result = await original_execute(self, name, args)
        if name == "prepare_checkout":
            await boundary("proposal_committed")
        return result

    SpecialistTools._execute = execute
    original_confirm = durable_graph.execute_confirmation

    async def confirm(runtime, value):
        await boundary("confirmed_before_execute")
        result = await original_confirm(runtime, value)
        await boundary("business_committed")
        return result

    durable_graph.execute_confirmation = confirm
    original_save = run_service.NodeStore.save

    async def save(self, key, output, trace):
        await original_save(self, key, output, trace)
        if key.startswith("execute_confirmed:"):
            await boundary("node_journal_saved")

    run_service.NodeStore.save = save
    if task.get("boundary") == "checkpoint_saved":
        original_recover = run_service.recover_receipts

        async def recover(runtime):
            result = await original_recover(runtime)
            # Only the application final reconciliation uses this module binding.
            await boundary("checkpoint_saved")
            return result

        run_service.recover_receipts = recover
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login", json={"login": "buyer1", "password": "AgentMall-demo-2026!"}
            )
            assert login.status_code == 200, login.text
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            response = await client.post(task["path"], headers=headers, json=task["body"])
            await asyncio.to_thread(
                Path(task["output"]).write_text,
                json.dumps({"status": response.status_code, "body": response.json()}),
            )
    finally:
        await app.state.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
