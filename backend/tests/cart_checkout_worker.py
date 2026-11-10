"""Test-only subprocess boundary: HTTP commit, then optional controlled SIGKILL."""

import asyncio
import json
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from agentmall.infra.config import Settings
from agentmall.main import create_app


def write_marker(path, result):
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(result))
    pending.replace(path)


async def main():
    task = json.loads(await asyncio.to_thread(Path(sys.argv[1]).read_text))
    app = create_app(Settings().model_copy(update={"db_schema": task["schema"]}))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login", json={"login": "buyer1", "password": "AgentMall-demo-2026!"}
            )
            assert login.status_code == 200
            response = await client.post(
                "/api/v1/orders",
                headers={
                    "Authorization": "Bearer " + login.json()["access_token"],
                    "Idempotency-Key": task["key"],
                },
                json={
                    "proposal_id": task["proposal_id"],
                    "confirmation_id": task["confirmation_id"],
                },
            )
            assert response.status_code in {200, 201}, response.text
            await asyncio.to_thread(
                write_marker,
                Path(task["marker"]),
                {"status": response.status_code, "body": response.json()},
            )
            if len(sys.argv) > 2:
                await asyncio.sleep(20)
    finally:
        await app.state.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
