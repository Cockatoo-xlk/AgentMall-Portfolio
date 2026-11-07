"""Independent official MCP Client. No model, login password or commerce execution.

uv run --project backend python scripts/mcp_demo.py --stdio --profile public
uv run --project backend python scripts/mcp_demo.py --url http://127.0.0.1:8038/mcp --profile buyer
Bearer credentials come only from AGENTMALL_MCP_TOKEN. Output never includes credentials.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


def local_url(value):
    try:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path != "/mcp"
            or url.port is None
            or not 1024 <= url.port <= 65535
        ):
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Use http://127.0.0.1:<port>/mcp without credentials/query"
        ) from None
    return value


async def inspect_client(client, profile, draft_request_id=None):
    tools = (await client.list_tools()).tools
    names = {t.name for t in tools}
    receipts = []

    async def call(name, args, expected_error=None):
        value = await client.call_tool(name, args, read_timeout_seconds=6)
        result = value.structured_content
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("ok"), bool)
            or value.is_error == result["ok"]
        ):
            raise ValueError("Invalid result")
        receipts.append(
            {
                "tool": name,
                "ok": result["ok"],
                "data": result.get("data"),
                "error": result.get("error"),
            }
        )
        if expected_error is not None:
            if result.get("error", {}).get("code") != expected_error:
                raise ValueError("Unexpected permission result")
        elif not result["ok"]:
            raise ValueError("Domain read failed")
        return result

    for query, category in [
        ("手机", "smartphone"),
        ("显示器", "monitor"),
        ("骑行", "cycling"),
    ]:
        result = await call(
            "search_products",
            {
                "query": query,
                "category": category,
                "max_price_cents": 300000,
                "limit": 2,
            },
        )
        if not result["ok"]:
            raise ValueError("Product read failed")
        if result["data"]["items"]:
            await call("get_product", {"product_id": result["data"]["items"][0]["id"]})
    if profile == "buyer":
        if "list_my_orders" not in names:
            raise ValueError("Buyer authentication required")
        orders = await call("list_my_orders", {"limit": 3})
        if orders["ok"] and orders["data"]["items"]:
            oid = orders["data"]["items"][0]["id"]
            await call("get_my_order", {"order_id": oid})
            await call(
                "check_return_eligibility",
                {"order_id": oid, "reason_code": "QUALITY_ISSUE"},
            )
    if profile == "merchant":
        if "list_merchant_catalog" not in names:
            raise ValueError("Merchant authentication required")
        await call("list_merchant_catalog", {"limit": 3})
        await call("list_merchant_after_sales", {"limit": 3})
        if draft_request_id:
            body = {
                "request_id": str(draft_request_id),
                "data": {
                    "name": "合成MCP客户端 N27 显示器",
                    "category": "monitor",
                    "description": "27英寸IPS显示器；合成演示资料。",
                    "price_cents": 99900,
                    "on_hand": 5,
                    "attributes": {"screen_inches": "27", "panel": "IPS"},
                },
            }
            first = await call("create_product_draft", body)
            replay = await call("create_product_draft", body)
            if not first["ok"] or first != replay or first["data"]["status"] != "DRAFT":
                raise ValueError("Draft replay failed")
    else:
        denied = await call("list_merchant_catalog", {}, expected_error="FORBIDDEN")
        if denied.get("error", {}).get("code") != "FORBIDDEN":
            raise ValueError("Permission boundary failed")
    return {
        "status": "INDEPENDENT_MCP_CLIENT_COMPLETED",
        "protocol_version": client.protocol_version,
        "profile_requested": profile,
        "identity_authority": "validated by server, never profile argument",
        "tools": sorted(names),
        "calls": receipts,
        "provider_requests": 0,
        "remote_auth": "REMOTE_AUTH_NOT_IMPLEMENTED",
    }


async def run(args):
    async with asyncio.timeout(30):
        token = (
            None if args.profile == "public" else os.environ.get("AGENTMALL_MCP_TOKEN")
        )
        if args.profile != "public" and not token:
            raise ValueError("MCP bearer credential required")
        if args.stdio:
            allowed = [
                "PATH",
                "HOME",
                "LANG",
                "SYSTEMROOT",
                "AGENTMALL_DATABASE_URL",
                "AGENTMALL_TEST_DATABASE_URL",
                "AGENTMALL_JWT_SECRET",
                "AGENTMALL_DB_SCHEMA",
                "AGENTMALL_STOREFRONT_ID",
                "AGENTMALL_JWT_ISSUER",
                "AGENTMALL_JWT_AUDIENCE",
            ]
            env = {k: os.environ[k] for k in allowed if k in os.environ}
            if token:
                env["AGENTMALL_MCP_TOKEN"] = token
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "agentmall.mcp_gateway", "--transport", "stdio"],
                env=env,
                cwd=ROOT,
            )
            async with Client(
                params, mode="auto", cache=None, read_timeout_seconds=8
            ) as client:
                return await inspect_client(client, args.profile, args.draft_request_id)
        async with (
            httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + token} if token else {},
                trust_env=False,
                timeout=8,
            ) as http,
            Client(
                streamable_http_client(args.url, http_client=http),
                mode="auto",
                cache=None,
            ) as client,
        ):
            return await inspect_client(client, args.profile, args.draft_request_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--url", type=local_url, default="http://127.0.0.1:8038/mcp")
    parser.add_argument(
        "--profile", choices=["public", "buyer", "merchant"], default="public"
    )
    parser.add_argument(
        "--draft-request-id",
        type=UUID,
        help="Explicit opt-in to create/replay one synthetic DRAFT; merchant only",
    )
    args = parser.parse_args()
    if args.draft_request_id and args.profile != "merchant":
        parser.error("Draft opt-in requires merchant profile and authentication")
    try:
        result = asyncio.run(run(args))
    except Exception:  # noqa: BLE001 - CLI must not expose credential-bearing transport errors.
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": "MCP_CLIENT_CALL_FAILED",
                    "diagnostics": "No credentials or private transport exception prose is printed.",
                }
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
