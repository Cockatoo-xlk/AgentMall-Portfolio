"""Owned, temporary Fixture demo. Run only in compose.ci.yaml's runner.

No production listener or historical schema is reused. Ctrl-C gracefully cleans
this process's API, Vite and temporary business/checkpoint schemas.
"""

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
KEY = {"X-E2E-Key": "agentmall-local-e2e"}
PASSWORD = "AgentMall-demo-2026!"  # Public synthetic demo identities only.


def require_free_ports(ports):
    sockets = []
    try:
        for port in ports:
            sock = socket.socket()
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
    finally:
        for sock in sockets:
            sock.close()


async def prepare_return(client):
    response = await client.get("/__test/health", headers=KEY)
    response.raise_for_status()
    status = response.json()
    if status.get("fixture_mode") != "fake-model-real-fastapi-postgresql":
        raise ValueError("Recognized owned Fixture API is required")
    if status.get("real_model_calls", 0) or status.get("provider_http_requests", 0):
        raise ValueError("Fixture API must have zero provider requests")

    async def post(path, body, headers=None):
        response = await client.post(
            "/api/v1" + path,
            json=body,
            headers={**(headers or {}), "Idempotency-Key": str(uuid4())},
        )
        response.raise_for_status()
        return response.json()

    async def get(path, headers):
        response = await client.get("/api/v1" + path, headers=headers)
        response.raise_for_status()
        return response.json()

    buyer = await post("/auth/login", {"login": "buyer1", "password": PASSWORD})
    buyer = {"Authorization": "Bearer " + buyer["access_token"]}
    products = await get("/products?category=keyboard", buyer)
    proposal = await post(
        "/checkout/proposals",
        {
            "request_id": str(uuid4()),
            "proposal_slot": "fixture_order",
            "address_label": "demo_dorm",
            "items": [{"product_id": products["items"][0]["id"], "quantity": 1}],
        },
        buyer,
    )
    confirmation = await post(
        f"/proposals/{proposal['proposal_id']}/confirmations",
        {"decision": "approve"},
        buyer,
    )
    receipt = await post(
        "/orders",
        {
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
        buyer,
    )
    order = await get(f"/orders/{receipt['order_id']}", buyer)
    proposal = await post(
        f"/orders/{order['id']}/payment-proposals",
        {
            "request_id": str(uuid4()),
            "expected_version": order["version"],
        },
        buyer,
    )
    confirmation = await post(
        f"/proposals/{proposal['proposal_id']}/confirmations",
        {"decision": "approve"},
        buyer,
    )
    await post(
        f"/orders/{order['id']}/mock-payments",
        {
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
        buyer,
    )
    order = await get(f"/orders/{order['id']}", buyer)
    merchant = await post("/auth/login", {"login": "merchant", "password": PASSWORD})
    merchant = {"Authorization": "Bearer " + merchant["access_token"]}
    for event in ("ship", "deliver"):
        order = await post(
            f"/merchant/orders/{order['id']}/{event}",
            {
                "expected_version": order["version"],
            },
            merchant,
        )
    assert order["status"] == "DELIVERED"
    return {"delivered_order_id": order["id"], "status": order["status"]}


def spawn(command, *, cwd, stream):
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=dict(os.environ),
    )


async def serve(args):
    import httpx
    from dotenv import dotenv_values

    require_free_ports([8001, 5174, 18001, 15174])
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "scripts/ci/bootstrap.py", "--port", "55433"],
        cwd=ROOT,
        check=True,
        env=dict(os.environ),
    )
    os.environ.update(dotenv_values(ROOT / ".env.rag"))
    os.environ.update(
        AGENTMALL_API_TARGET="http://127.0.0.1:8001",
        VITE_AGENT_MODE="fixture",
        AGENTMALL_DEMO_CATALOG_PROFILE=args.catalog_profile,
    )
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    processes, streams, proxies = [], [], []
    output = ROOT / ".t13/outputs"
    output.mkdir(parents=True, exist_ok=True)
    try:
        for name, command, cwd in (
            (
                "api",
                [sys.executable, "backend/tests/web_e2e_server.py", "--port", "8001"],
                ROOT,
            ),
            (
                "web",
                ["npm", "run", "dev", "--", "--port", "5174", "--strictPort"],
                ROOT / "frontend",
            ),
        ):
            stream = (output / f"demo-{name}-{time.time_ns()}.txt").open("xb")
            streams.append(stream)
            processes.append(
                await asyncio.to_thread(spawn, command, cwd=cwd, stream=stream)
            )
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8001", timeout=5
        ) as client:
            for _ in range(120):
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError(
                        "Owned demo process exited during startup; inspect local logs"
                    )
                try:
                    api = await client.get("/__test/health", headers=KEY)
                    web = await client.get("http://127.0.0.1:5174")
                    if api.is_success and web.is_success:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.5)
            else:
                raise TimeoutError("Owned demo did not become ready within 60 seconds")
            status = api.json()
            if args.prepare_return:
                status.update(await prepare_return(client))

            async def forward(reader, writer, port):
                other = None
                try:
                    remote, other = await asyncio.open_connection("127.0.0.1", port)

                    async def copy(source, destination):
                        try:
                            while data := await source.read(65536):
                                destination.write(data)
                                await destination.drain()
                        finally:
                            destination.close()

                    await asyncio.gather(copy(reader, other), copy(remote, writer))
                except (ConnectionError, OSError):
                    pass
                finally:
                    writer.close()
                    if other:
                        other.close()

            for proxy, port in ((18001, 8001), (15174, 5174)):

                async def handler(reader, writer, target=port):
                    await forward(reader, writer, target)

                proxies.append(await asyncio.start_server(handler, "0.0.0.0", proxy))
            print(
                json.dumps(
                    {
                        "demo": "FIXTURE_MODEL / REAL_FASTAPI / REAL_POSTGRES / REAL_CHECKPOINT",
                        "url": "http://127.0.0.1:5174",
                        **status,
                    }
                ),
                flush=True,
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=args.seconds)
            except TimeoutError:
                pass
            final = await client.get("/__test/health", headers=KEY)
            print(json.dumps({"demo_final": final.json()}), flush=True)
    finally:
        for proxy in proxies:
            proxy.close()
            await proxy.wait_closed()
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.to_thread(process.wait, 15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
        for stream in streams:
            stream.close()
        print(
            json.dumps({"owned_process_exit_codes": [p.returncode for p in processes]}),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-return", action="store_true")
    parser.add_argument(
        "--catalog-profile", choices=("legacy", "expanded"), default="expanded"
    )
    parser.add_argument("--seconds", type=int, default=900, choices=range(1, 3601))
    args = parser.parse_args()
    if not Path("/.dockerenv").exists() or not os.environ.get(
        "AGENTMALL_CI_DB_PASSWORD"
    ):
        raise SystemExit(
            "Run only via the owned compose.ci.yaml runner; no host database startup"
        )
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from unittest.mock import patch

    from web_e2e_server import FilteredEnvironment

    with patch.object(os, "environ", FilteredEnvironment(os.environ)):
        asyncio.run(serve(args))


if __name__ == "__main__":
    main()
