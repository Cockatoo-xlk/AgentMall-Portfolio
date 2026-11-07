"""python -m agentmall.mcp_gateway --transport stdio|http (localhost only)."""

import argparse
import asyncio
import logging
import os

import uvicorn
from mcp.server.stdio import stdio_server

from agentmall.infra.config import Settings
from agentmall.main import create_app
from agentmall.mcp_gateway.server import create_http_app, create_server
from agentmall.mcp_gateway.stdio import BoundedLines


async def stdio(app, token):
    try:
        server = create_server(app, stdio_token=token)
        async with stdio_server(stdin=BoundedLines()) as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await app.state.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Local AgentMall MCP; REMOTE_AUTH_NOT_IMPLEMENTED")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8038)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a local unprivileged port")
    logging.basicConfig(level=logging.CRITICAL)
    try:
        # Explicit business settings only. Do not load an arbitrary repository .env.
        app = create_app(Settings(_env_file=None))
        if args.transport == "stdio":
            asyncio.run(stdio(app, os.environ.get("AGENTMALL_MCP_TOKEN")))
        else:
            # HTTP never uses a process-global bearer identity for other clients.
            uvicorn.run(
                create_http_app(app, dispose_engine=True),
                host=args.host,
                port=args.port,
                proxy_headers=False,
                access_log=False,
                log_level="critical",
            )
    except Exception:
        raise SystemExit(
            "MCP gateway stopped; inspect private local configuration and domain state."
        ) from None


if __name__ == "__main__":
    main()
