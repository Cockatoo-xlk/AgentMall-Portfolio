"""Explicit Live container entry. Contains no test routes or model fixtures."""

import asyncio
import sys

from playground_proxy import serve_child

if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(
            serve_child([sys.executable, "-m", "agentmall.playground", *sys.argv[1:]])
        )
    )
