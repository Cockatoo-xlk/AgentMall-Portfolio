"""Owned SIGKILL target: context+Run committed, activation not begun. Offline only."""

import asyncio
import json
import sys
from pathlib import Path

from web_e2e_server import offline_boundary


async def main():
    from httpx import ASGITransport, AsyncClient
    from multiagent_helpers import make_models, route

    from agentmall.agents import run_service
    from agentmall.infra.config import Settings
    from agentmall.main import create_app

    task = json.loads(await asyncio.to_thread(Path(sys.argv[1]).read_text))
    assert task["schema"].startswith("test_") and task["checkpoint"].startswith("cp_")
    base = Settings()
    app = create_app(
        base.model_copy(
            update={
                "database_url": base.test_database_url,
                "db_schema": task["schema"],
                "checkpoint_schema": task["checkpoint"],
            }
        )
    )
    app.state.multi_models = make_models(supervisor=[route("finish")])

    async def pause(*args, **kwargs):
        await asyncio.to_thread(
            Path(task["marker"]).write_text, "context-and-run-committed-before-activation"
        )
        await asyncio.Event().wait()

    run_service.activate = pause
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login", json={"login": "buyer1", "password": "AgentMall-demo-2026!"}
            )
            response = await client.post(
                f"/api/v1/agent/threads/{task['thread']}/runs",
                headers={"Authorization": "Bearer " + login.json()["access_token"]},
                json=task["body"],
            )
            raise AssertionError(f"pause was not reached: {response.status_code}")
    finally:
        await app.state.engine.dispose()


if __name__ == "__main__":
    with offline_boundary():
        asyncio.run(main())
