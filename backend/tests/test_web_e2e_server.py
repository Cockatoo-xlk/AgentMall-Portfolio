"""Test the local browser harness against real services and isolated PostgreSQL."""

import asyncio
import importlib
import importlib.util
import os
import signal
import socket
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from conftest import PASSWORD, guard_test_database
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

KEY = {"X-E2E-Key": "agentmall-local-e2e"}


def harness_module():
    assert importlib.util.find_spec("web_e2e_server") is not None, "E2E harness is missing"
    return importlib.import_module("web_e2e_server")


@pytest.fixture
async def harness():
    async with harness_module().isolated_app() as instance:
        async with AsyncClient(
            transport=ASGITransport(app=instance.app, client=("127.0.0.1", 43210)),
            base_url="http://127.0.0.1",
        ) as client:
            yield instance, client


async def login(client, name="buyer1"):
    response = await client.post("/api/v1/auth/login", json={"login": name, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


async def message(client, auth, request_id=None):
    return await client.post(
        "/api/v1/agent/messages",
        headers=auth,
        json={"request_id": request_id or str(uuid4()), "message": "买一把静音键盘，300元内"},
    )


async def facts(client):
    response = await client.get("/__test/facts", headers=KEY)
    assert response.status_code == 200, response.text
    return response.json()


async def test_control_routes_require_key_and_loopback(harness):
    instance, client = harness
    assert (await client.get("/__test/health")).status_code == 403
    assert (await client.get("/__test/health", headers={"X-E2E-Key": "wrong"})).status_code == 403
    health = await client.get("/__test/health", headers=KEY)
    assert health.status_code == 200
    assert health.json()["schema"] == instance.schema
    assert health.json()["fixture_mode"] == "fake-model-real-fastapi-postgresql"
    async with AsyncClient(
        transport=ASGITransport(app=instance.app, client=("203.0.113.1", 43210)),
        base_url="http://127.0.0.1",
    ) as remote:
        assert (await remote.get("/__test/health", headers=KEY)).status_code == 403
        assert (await remote.get("/api/v1/products")).status_code == 403


async def test_harness_fake_uses_real_tools_and_order_receipt(harness):
    _, client = harness
    auth = await login(client)
    request_id = str(uuid4())
    result = (await message(client, auth, request_id)).json()
    assert result["status"] == "proposal"
    proposal_id = result["proposal_refs"][0]
    before = await facts(client)
    assert (before["proposals"], before["orders"], before["reserved"]) == (1, 0, 0)
    assert [t["name"] for t in before["agent_traces"][0]["tools"]] == [
        "search_products",
        "prepare_checkout",
    ]
    confirmation = await client.post(
        f"/api/v1/proposals/{proposal_id}/confirmations",
        headers=auth,
        json={"decision": "approve"},
    )
    assert confirmation.status_code == 201
    order = await client.post(
        "/api/v1/orders",
        headers={**auth, "Idempotency-Key": "e2e-purchase"},
        json={
            "proposal_id": proposal_id,
            "confirmation_id": confirmation.json()["confirmation_id"],
        },
    )
    assert order.status_code == 201, order.text
    receipt = order.json()
    after = await facts(client)
    assert (after["orders"], after["reserved"], after["receipts"], after["events"]) == (1, 1, 1, 1)
    assert after["receipt_rows"][0]["result"] == receipt
    assert after["confirmation_rows"][0]["consumed_at"] is not None
    assert after["provider_http_requests"] == 0
    assert after["real_model_calls"] == 0
    await client.post("/__test/agent-mode", headers=KEY, json={"mode": "done"})
    assert (await message(client, auth, request_id)).json()["status"] == "done"
    assert (await message(client, auth)).json()["status"] == "blocked"


@pytest.mark.parametrize(
    "mode,status", [("needs_input", "needs_input"), ("blocked", "blocked"), ("error", "error")]
)
async def test_modes_have_no_purchase_effects(harness, mode, status):
    _, client = harness
    auth = await login(client)
    response = await client.post("/__test/agent-mode", headers=KEY, json={"mode": mode})
    assert response.status_code == 200
    assert (await message(client, auth)).json()["status"] == status
    state = await facts(client)
    assert (state["orders"], state["proposals"], state["reserved"]) == (0, 0, 0)


async def test_parallel_agent_requests_do_not_share_fake_steps(harness):
    _, client = harness
    auth = await login(client)
    responses = await asyncio.gather(message(client, auth), message(client, auth))
    assert all(r.json()["status"] == "proposal" for r in responses)
    ids = [r.json()["proposal_refs"][0] for r in responses]
    assert ids[0] != ids[1]
    state = await facts(client)
    assert state["proposals"] == 2 and state["orders"] == 0
    assert len(state["agent_traces"]) == 2


async def test_expire_preserves_snapshot_then_reset_restores_seed(harness):
    instance, client = harness
    auth = await login(client)
    proposal_id = (await message(client, auth)).json()["proposal_refs"][0]
    original = (await client.get(f"/api/v1/proposals/{proposal_id}", headers=auth)).json()
    assert (
        await client.post("/__test/expire", headers=KEY, json={"proposal_id": proposal_id})
    ).status_code == 200
    expired = (await client.get(f"/api/v1/proposals/{proposal_id}", headers=auth)).json()
    assert expired["status"] == "EXPIRED"
    assert expired["expires_at"] == original["expires_at"]
    assert expired["payload_hash"] == original["payload_hash"]
    rejected = await client.post(
        f"/api/v1/proposals/{proposal_id}/confirmations", headers=auth, json={"decision": "approve"}
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "STALE_PROPOSAL"
    assert (
        await client.post("/__test/disable-user", headers=KEY, json={"login": "buyer1"})
    ).status_code == 200
    assert (await message(client, auth)).status_code == 401
    assert (await client.post("/__test/reset", headers=KEY)).status_code == 200
    state = await facts(client)
    assert state["schema"] == instance.schema
    assert (state["orders"], state["proposals"], state["reserved"]) == (0, 0, 0)
    assert len(state["product_rows"]) == 12
    auth = await login(client)
    assert (await message(client, auth)).json()["status"] == "proposal"


async def test_owned_schema_is_removed_even_after_exception():
    schema = url = None
    with pytest.raises(RuntimeError, match="synthetic failure"):
        async with harness_module().isolated_app() as instance:
            schema = instance.schema
            url = guard_test_database(instance.settings.database_url.get_secret_value())
            raise RuntimeError("synthetic failure")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            assert not conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"),
                {"schema": schema},
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
async def test_cli_signal_shutdown_removes_its_schema(stop_signal):
    import json

    from agentmall.infra.config import Settings

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("web_e2e_server.py")),
        "--port",
        str(port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    schema = None
    engine = create_engine(guard_test_database(Settings().test_database_url.get_secret_value()))
    try:
        ready = json.loads(await asyncio.wait_for(process.stdout.readline(), 10))
        schema = ready["schema"]
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            async with asyncio.timeout(10):
                while True:
                    try:
                        if (await client.get("/__test/health", headers=KEY)).status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(0.05)
        process.send_signal(stop_signal)
        await asyncio.wait_for(process.wait(), 10)
        with engine.connect() as connection:
            assert not connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"),
                {"schema": schema},
            ), "CLI shutdown leaked its owned schema"
    finally:
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)
        # Also clean a red regression run, and only its child-created schema from the receipt.
        if schema is not None:
            import re

            assert re.fullmatch(r"test_[0-9a-f]{32}", schema)
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_provider_environment_is_not_read_and_external_transports_are_blocked(monkeypatch):
    class UnreadableProviders(dict):
        def __getitem__(self, key):
            assert "DEEPSEEK" not in key and "OPENAI" not in key
            return super().__getitem__(key)

    monkeypatch.setattr(
        os,
        "environ",
        UnreadableProviders(
            {
                "DEEPSEEK_API_KEY": "must-not-be-read",
                "OPENAI_API_KEY": "must-not-be-read",
                "LOCAL_VALUE": "allowed",
            }
        ),
    )
    with harness_module().offline_boundary() as boundary:
        assert os.environ.get("DEEPSEEK_API_KEY") is None
        assert os.environ.get("OPENAI_API_KEY") is None
        assert os.environ["LOCAL_VALUE"] == "allowed"
        assert "DEEPSEEK_API_KEY" not in dict(os.environ)
        with pytest.raises(RuntimeError, match="external network"):
            httpx.HTTPTransport().handle_request(httpx.Request("GET", "https://example.com"))
        with socket.socket() as sock, pytest.raises(RuntimeError, match="external network"):
            sock.connect(("203.0.113.1", 443))
        assert boundary.provider_http_requests == 0
        assert boundary.blocked_external_attempts == 2


async def test_normal_application_has_no_test_routes(env):
    assert (await env[0].get("/__test/health", headers=KEY)).status_code == 404


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.1", "example.com"])
def test_cli_rejects_non_loopback_bind(host):
    with pytest.raises(ValueError, match="loopback"):
        harness_module().validate_host(host)


async def test_payment_controls_are_loopback_keyed_and_reset_adapter(harness):
    instance, client = harness
    assert (
        await client.post("/__test/payment-mode", json={"result": "DECLINED"})
    ).status_code == 403
    assert (
        await client.post("/__test/payment-mode", headers=KEY, json={"result": "BAD"})
    ).status_code == 422
    assert (
        await client.post("/__test/payment-mode", headers=KEY, json={"result": "DECLINED"})
    ).status_code == 200
    assert instance.app.state.mock_payment_adapter.result == "DECLINED"
    assert (await facts(client))["payment_rows"] == []
    missing = await client.post(
        "/__test/order-condition",
        headers=KEY,
        json={"order_id": str(uuid4()), "condition": "expire"},
    )
    assert missing.status_code == 404
    await client.post("/__test/reset", headers=KEY, json={})
    assert instance.app.state.mock_payment_adapter.result == "SUCCEEDED"


async def test_payment_control_expiry_uses_real_db_and_domain_receipt(harness):
    from checkout_helpers import confirm
    from lifecycle_helpers import create_order, execute_action, prepare_action

    _, client = harness
    buyer = await login(client)
    products = (await client.get("/api/v1/products", headers=buyer)).json()["items"]
    order = await create_order(client, buyer, products[0]["id"])
    before = await facts(client)
    near = await client.post(
        "/__test/order-condition",
        headers=KEY,
        json={"order_id": order["id"], "condition": "near_expiry"},
    )
    assert near.status_code == 200
    proposal = await prepare_action(client, buyer, order, "payment")
    confirmation = await confirm(client, buyer, proposal)
    changed = await client.post(
        "/__test/order-condition",
        headers=KEY,
        json={"order_id": order["id"], "condition": "expire"},
    )
    assert changed.status_code == 200
    response = await execute_action(client, buyer, order, proposal, confirmation, "payment")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "EXPIRED"
    after = await facts(client)
    assert after["order_rows"][0]["status"] == "EXPIRED"
    assert after["payment_rows"] == []
    assert after["reserved"] == 0
    assert sum(p["on_hand"] for p in before["product_rows"]) == sum(
        p["on_hand"] for p in after["product_rows"]
    )
