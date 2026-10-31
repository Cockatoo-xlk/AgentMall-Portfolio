"""Real loopback HTTP and PostgreSQL; only response delivery is deliberately faulted."""

import asyncio
import socket
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
import uvicorn
from checkout_helpers import confirm
from conftest import PASSWORD, row
from lifecycle_helpers import create_order, execute_action, prepare_action


@asynccontextmanager
async def loopback_server(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        assert port not in {8000, 5173}
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_config=None,
                access_log=False,
                log_level="critical",
                lifespan="off",
                ws="none",
                timeout_graceful_shutdown=2,
            )
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                        raise AssertionError("Owned HTTP server failed to start")
                    await asyncio.sleep(0.01)
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
            ) as client:
                yield client
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except TimeoutError:
                server.force_exit = True
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise


class LoseCommittedPaymentResponse(httpx.AsyncBaseTransport):
    """Keep the real network/transaction, drop the received success before caller sees it."""

    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.committed_receipt = None

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        await response.aread()
        try:
            assert response.status_code == 201, response.text
            self.committed_receipt = response.json()
        finally:
            await response.aclose()
        raise httpx.ReadError(
            "Synthetic loss after consuming the committed response", request=request
        )

    async def aclose(self):
        await self.inner.aclose()


async def login(client, name):
    response = await client.post("/api/v1/auth/login", json={"login": name, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


async def test_real_http_payment_response_loss_recovery_cancel_and_delivery(env, product):
    _, db, app, _ = env
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    async with loopback_server(app) as client:
        buyer = await login(client, "buyer1")
        merchant = await login(client, "merchant")
        order = await create_order(client, buyer, product, quantity=2)
        proposal = await prepare_action(client, buyer, order, "payment")
        confirmation = await confirm(client, buyer, proposal)
        key = str(uuid4())
        transport = LoseCommittedPaymentResponse()
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=transport, trust_env=False, timeout=5
        ) as losing_client:
            with pytest.raises(httpx.ReadError, match="Synthetic loss"):
                await execute_action(
                    losing_client, buyer, order, proposal, confirmation, "payment", key
                )

        # This query uses a separate committed database connection before either retry.
        assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
            "status": "PAID",
            "version": 2,
        }
        recovered = await client.get(f"/api/v1/proposals/{proposal['proposal_id']}", headers=buyer)
        assert recovered.status_code == 200
        receipt = recovered.json()["result"]
        assert receipt == transport.committed_receipt and receipt["status"] == "SUCCEEDED"
        detail = await client.get(f"/api/v1/orders/{order['id']}", headers=buyer)
        assert detail.status_code == 200 and detail.json()["status"] == "PAID"
        for retry_key in (key, str(uuid4())):
            replay = await execute_action(
                client, buyer, order, proposal, confirmation, "payment", retry_key
            )
            assert replay.status_code == 200 and replay.json() == receipt
        assert (
            row(
                db,
                "SELECT count(*) AS n FROM payments WHERE order_id=:id AND status='SUCCEEDED'",
                id=order["id"],
            )["n"]
            == 1
        )
        assert (
            row(
                db,
                "SELECT count(*) AS n FROM business_events "
                "WHERE aggregate_id=:id AND event_type='ORDER_PAID'",
                id=order["id"],
            )["n"]
            == 1
        )
        assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == {
            "on_hand": before["on_hand"] - 2,
            "reserved": before["reserved"],
        }

        # The paid order continues through the real merchant and buyer HTTP boundaries.
        merchant_url = f"/api/v1/merchant/orders/{order['id']}"
        forbidden = await client.post(
            merchant_url + "/ship", headers=buyer, json={"expected_version": 2}
        )
        assert forbidden.status_code == 403
        shipped = await client.post(
            merchant_url + "/ship", headers=merchant, json={"expected_version": 2}
        )
        assert shipped.status_code == 200 and shipped.json()["status"] == "SHIPPED"
        delivered = await client.post(
            merchant_url + "/deliver", headers=merchant, json={"expected_version": 3}
        )
        assert delivered.status_code == 200 and delivered.json()["status"] == "DELIVERED"
        shipment = await client.get(f"/api/v1/orders/{order['id']}/shipment", headers=buyer)
        assert shipment.status_code == 200
        assert [event["status"] for event in shipment.json()["events"]] == [
            "PAID",
            "SHIPPED",
            "DELIVERED",
        ]

        cancelled_order = await create_order(client, buyer, product, quantity=3)
        cancellation = await prepare_action(client, buyer, cancelled_order, "cancel")
        approval = await confirm(client, buyer, cancellation)
        cancelled = await execute_action(
            client, buyer, cancelled_order, cancellation, approval, "cancel"
        )
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
        replay = await execute_action(
            client, buyer, cancelled_order, cancellation, approval, "cancel"
        )
        assert replay.status_code == 200 and replay.json() == cancelled.json()

    # HTTP shutdown and every lifecycle transition preserve the same inventory total.
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == {
        "on_hand": before["on_hand"] - 2,
        "reserved": before["reserved"],
    }
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "DELIVERED",
        "version": 4,
    }
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=cancelled_order["id"]) == {
        "status": "CANCELLED",
        "version": 2,
    }
