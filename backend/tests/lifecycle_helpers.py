from datetime import timedelta
from uuid import uuid4

from checkout_helpers import confirm, execute, prepare, request_body
from sqlalchemy import text


async def create_order(client, auth, product, quantity=1, items=None):
    body = request_body(product, quantity)
    if items is not None:
        body["items"] = items
    proposal = await prepare(client, auth, body=body)
    confirmation = await confirm(client, auth, proposal)
    response = await execute(client, auth, proposal, confirmation)
    assert response.status_code == 201, response.text
    response = await client.get(f"/api/v1/orders/{response.json()['order_id']}", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


async def prepare_action(client, auth, order, kind, key=None, body=None):
    assert kind in {"payment", "cancel"}
    response = await client.post(
        f"/api/v1/orders/{order['id']}/{kind}-proposals",
        headers={**auth, "Idempotency-Key": key or str(uuid4())},
        json=body
        if body is not None
        else {
            "request_id": str(uuid4()),
            "proposal_slot": kind,
            "expected_version": order["version"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def execute_action(client, auth, order, proposal, confirmation, kind, key=None):
    assert kind in {"payment", "cancel"}
    endpoint = "mock-payments" if kind == "payment" else "cancel"
    return await client.post(
        f"/api/v1/orders/{order['id']}/{endpoint}",
        headers={**auth, "Idempotency-Key": key or str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
    )


def timed_order(db, order_id, seconds):
    """Retimestamp only this test's owned order, restoring its immutable guard atomically."""
    with db.begin() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        assert schema.startswith("test_") and len(schema) == 37
        assert connection.scalar(text("SELECT current_database()")) == "agentmall_test"
        connection.execute(text("ALTER TABLE orders DISABLE TRIGGER immutable_snapshot"))
        expires_at = connection.scalar(text("SELECT clock_timestamp()")) + timedelta(
            seconds=seconds
        )
        result = connection.execute(
            text("UPDATE orders SET expires_at=:expires_at WHERE id=:order_id"),
            {"expires_at": expires_at, "order_id": order_id},
        )
        assert result.rowcount == 1
        connection.execute(text("ALTER TABLE orders ENABLE TRIGGER immutable_snapshot"))
    return expires_at
