"""Offline E2E only: real API/PG/Checkpoint, Fixture or SDK MockTransport, no Live."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from playground_proxy import serve_child

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/tests"))
from web_e2e_server import FilteredEnvironment


async def main():
    from dotenv import dotenv_values

    if not Path("/.dockerenv").exists() or not os.environ.get(
        "AGENTMALL_CI_DB_PASSWORD"
    ):
        raise RuntimeError("New owned offline Compose runner required")
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "scripts/ci/bootstrap.py", "--port", "55433"],
        check=True,
    )
    os.environ.update(dotenv_values(ROOT / ".env.rag"))
    return await serve_child(
        [sys.executable, "backend/tests/web_e2e_server.py", "--port", "8001"],
        seconds=900,
    )


if __name__ == "__main__":
    with patch.object(os, "environ", FilteredEnvironment(os.environ)):
        raise SystemExit(asyncio.run(main()))
