"""Trusted offline composition root for real Worker subprocess tests, never Live."""

import asyncio
import json
import os
import socket
from pathlib import Path

import httpx
from bundle_helpers import BundleSDK
from playground_helpers import SDKProgram
from retrieval_helpers import FixtureEncoder

from agentmall.infra.config import Settings
from agentmall.infra.llm import deepseek_model
from agentmall.main import create_app as base_app


async def configure(app, *, boundary=None):
    app.state.worker_execution_identity = "worker-sdk-fixture-v1"
    program = SDKProgram()
    bundle = BundleSDK()
    clients = []
    for role in ("supervisor", "shopping", "order", "aftersales", "single"):
        original = program.transport(role)

        async def transport(request, role=role, original=original):
            if boundary:
                await boundary("model_inflight")
            # Program is a replayable wire fixture, not a process-local call counter.
            body = json.loads(request.content)
            user = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            if (user.get("canonical_constraints") or user.get("constraints") or {}).get("bundle"):
                return await bundle.transport(role).handle_async_request(request)
            program.counts[role] = int(any(m["role"] == "tool" for m in body["messages"]))
            return await original.handle_async_request(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        clients.append(client)
        model = deepseek_model("synthetic-offline-worker-only", http_async_client=client)
        if role == "single":
            app.state.durable_single_model = model
        else:
            app.state.multi_models = {**(app.state.multi_models or {}), role: model}
    app.state.worker_execution_identity = "worker-sdk-fixture-v1"
    app.state.retrieval_encoder = FixtureEncoder()

    async def close():
        for client in clients:
            await client.aclose()

    app.state.worker_close = close
    return app


async def create_app():
    config = json.loads(
        await asyncio.to_thread(Path(os.environ["AGENTMALL_WORKER_TEST_CONFIG"]).read_text)
    )
    settings = Settings(
        database_url=Settings().test_database_url,
        db_schema=config["schema"],
        checkpoint_schema=config["checkpoint"],
    )
    assert settings.db_schema.startswith("test_") and settings.checkpoint_schema.startswith("cp_")
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise AssertionError("Offline worker forbids external sockets")
        return original_connect(sock, address)

    socket.socket.connect = local_only

    async def boundary(label):
        if config.get("boundary") == label:
            marker = Path(config["marker"])
            await asyncio.to_thread(marker.write_text, label)
            await asyncio.to_thread(marker.chmod, 0o600)
            while not marker.with_suffix(".release").exists():  # noqa: ASYNC110 - deterministic process fault gate
                await asyncio.sleep(0.025)

    app = await configure(base_app(settings), boundary=boundary)
    from agentmall.agents import durable_graph, run_service

    save = run_service.NodeStore.save

    async def save_boundary(self, key, output, trace):
        await save(self, key, output, trace)
        if key.startswith("supervisor:"):
            await boundary("journal_committed")
        if key.startswith("execute_confirmed:"):
            await boundary("execute_journal_committed")

    run_service.NodeStore.save = save_boundary
    execute = durable_graph.execute_confirmation

    async def execute_boundary(runtime, value):
        result = await execute(runtime, value)
        await boundary("business_committed")
        return result

    durable_graph.execute_confirmation = execute_boundary
    activate = run_service.activate

    async def activate_boundary(*args, **kwargs):
        result = await activate(*args, **kwargs)
        if result["status"] == "WAITING_INPUT":
            await boundary("waiting_committed")
        return result

    run_service.activate = activate_boundary
    recover = run_service.recover_receipts

    async def recover_boundary(runtime):
        result = await recover(runtime)
        await boundary("checkpoint_waiting")
        return result

    run_service.recover_receipts = recover_boundary
    if config.get("version_mismatch"):
        app.state.worker_execution_identity = "different-version"
    if config.get("advance_proposal_clock"):
        from datetime import timedelta

        from agentmall.actions import service as actions
        from agentmall.orders import service as orders

        original_now = actions.database_now

        async def later(session):
            return await original_now(session) + timedelta(hours=1)

        actions.database_now = later
        orders.database_now = later
    await boundary("before_claim")
    return app


async def serve_api(port):
    import uvicorn

    app = await create_app()
    await uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    ).serve()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Offline independent test API only")
    parser.add_argument("--api-port", type=int, required=True)
    asyncio.run(serve_api(parser.parse_args().api_port))
