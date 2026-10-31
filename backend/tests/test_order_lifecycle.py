"""T05 real PostgreSQL lifecycle, authorization, replay and rollback contracts."""

from uuid import uuid4

import pytest
from checkout_helpers import confirm
from conftest import PASSWORD, row
from httpx import ASGITransport, AsyncClient
from lifecycle_helpers import create_order, execute_action, prepare_action, timed_order
from sqlalchemy import text


def facts(db, order_id, product):
    return row(
        db,
        "SELECT status,version,paid_at,shipped_at,delivered_at FROM orders WHERE id=:id",
        id=order_id,
    ), row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)


async def action(client, buyer, order, kind):
    p = await prepare_action(client, buyer, order, kind)
    return p, await confirm(client, buyer, p)


async def merchant_auth(client):
    r = await client.post("/api/v1/auth/login", json={"login": "merchant", "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["access_token"]}


async def test_payment_success_receipt_replays_and_consumes_stock_once(env, buyer, product):
    client, db, _, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    p, c = await action(client, buyer, order, "payment")
    key = str(uuid4())
    response = await execute_action(client, buyer, order, p, c, "payment", key)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["status"] == "SUCCEEDED" and receipt["order_status"] == "PAID"
    assert receipt["total_cents"] == order["total_cents"] and receipt["payment_id"]
    for repeat_key in (key, str(uuid4())):
        retry = await execute_action(client, buyer, order, p, c, "payment", repeat_key)
        assert retry.status_code == 200 and retry.json() == receipt
    state, stock = facts(db, order["id"], product)
    assert (state["status"], state["version"]) == ("PAID", 2)
    assert state["paid_at"] and stock == {"on_hand": 18, "reserved": 0}
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 1
    payment = row(db, "SELECT * FROM payments")
    assert (
        str(payment["order_id"]) == order["id"] and payment["amount_cents"] == order["total_cents"]
    )
    assert payment["provider"] == "mock" and payment["status"] == "SUCCEEDED"
    recovered = (await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=buyer)).json()
    assert recovered["result"] == receipt and recovered["confirmation"]["consumed_at"]
    bad = await execute_action(
        client, buyer, order, p, {"confirmation_id": str(uuid4())}, "payment", key
    )
    assert bad.status_code == 409
    new = await client.post(
        f"/api/v1/orders/{order['id']}/payment-proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"request_id": str(uuid4()), "expected_version": 2},
    )
    assert new.status_code == 409


async def test_declined_is_completed_and_configuration_change_cannot_rewrite_it(
    env, buyer, product
):
    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    p, c = await action(client, buyer, order, "payment")
    from agentmall.payments.service import MockPaymentAdapter

    app.state.mock_payment_adapter = MockPaymentAdapter("DECLINED")
    key = str(uuid4())
    declined = await execute_action(client, buyer, order, p, c, "payment", key)
    assert declined.status_code == 200 and declined.json()["status"] == "DECLINED"
    app.state.mock_payment_adapter = MockPaymentAdapter("SUCCEEDED")
    for retry_key in (key, str(uuid4())):
        assert (
            await execute_action(client, buyer, order, p, c, "payment", retry_key)
        ).json() == declined.json()
    state, stock = facts(db, order["id"], product)
    assert state["status"] == "PENDING_PAYMENT" and stock == {"on_hand": 20, "reserved": 1}
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 0
    assert row(db, "SELECT consumed_at FROM confirmations WHERE id=:id", id=c["confirmation_id"])[
        "consumed_at"
    ]
    newp, newc = await action(client, buyer, order, "payment")
    assert (await execute_action(client, buyer, order, newp, newc, "payment")).json()[
        "status"
    ] == "SUCCEEDED"
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 1


@pytest.mark.parametrize("kind", ["payment", "cancel"])
async def test_expired_action_persists_receipt_and_never_releases_twice(env, buyer, product, kind):
    client, db, _, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    p, c = await action(client, buyer, order, kind)
    timed_order(db, order["id"], -1)
    expired = await execute_action(client, buyer, order, p, c, kind)
    assert expired.status_code == 200 and expired.json()["status"] == "EXPIRED"
    retry = await execute_action(client, buyer, order, p, c, kind)
    assert retry.json() == expired.json()
    state, stock = facts(db, order["id"], product)
    assert state["status"] == "EXPIRED" and state["version"] == 2
    assert stock == {"on_hand": 20, "reserved": 0}
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 0
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE event_type='ORDER_EXPIRED'")["n"] == 1
    )


async def test_cancel_releases_only_reserved_and_replays(env, buyer, product):
    client, db, _, _ = env
    order = await create_order(client, buyer, product, quantity=3)
    p, c = await action(client, buyer, order, "cancel")
    cancelled = await execute_action(client, buyer, order, p, c, "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert (await execute_action(client, buyer, order, p, c, "cancel")).json() == cancelled.json()
    state, stock = facts(db, order["id"], product)
    assert state["status"] == "CANCELLED" and stock == {"on_hand": 20, "reserved": 0}
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE event_type='ORDER_CANCELLED'")["n"]
        == 1
    )


@pytest.mark.parametrize("kind", ["payment", "cancel"])
async def test_confirmation_owner_target_and_action_boundaries(env, buyer, buyer2, product, kind):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    other = await create_order(client, buyer, product)
    p = await prepare_action(client, buyer, order, kind)
    missing = await execute_action(client, buyer, order, p, {"confirmation_id": str(uuid4())}, kind)
    assert missing.status_code == 404
    c = await confirm(client, buyer, p)
    assert (await execute_action(client, buyer2, order, p, c, kind)).status_code == 404
    assert (await execute_action(client, buyer, other, p, c, kind)).status_code == 404
    opposite = "cancel" if kind == "payment" else "payment"
    assert (await execute_action(client, buyer, order, p, c, opposite)).status_code == 409
    checkout_path = await client.post(
        "/api/v1/orders",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"proposal_id": p["proposal_id"], "confirmation_id": c["confirmation_id"]},
    )
    assert checkout_path.status_code == 409
    rejected = await prepare_action(client, buyer, order, kind)
    rejection = await confirm(client, buyer, rejected, "reject")
    assert (
        await execute_action(client, buyer, order, rejected, rejection, kind)
    ).status_code == 409
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 0
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("payment_status", "SUCCEEDED"),
        ("approved", True),
        ("amount_cents", 1),
        ("user_id", str(uuid4())),
        ("role", "merchant"),
    ],
)
async def test_buyer_cannot_control_payment_outcome_or_identity(env, buyer, product, field, value):
    client, _, _, _ = env
    order = await create_order(client, buyer, product)
    proposal = await client.post(
        f"/api/v1/orders/{order['id']}/payment-proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"request_id": str(uuid4()), "expected_version": 1, field: value},
    )
    assert proposal.status_code == 422
    p, c = await action(client, buyer, order, "payment")
    r = await client.post(
        f"/api/v1/orders/{order['id']}/mock-payments",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={
            "proposal_id": p["proposal_id"],
            "confirmation_id": c["confirmation_id"],
            field: value,
        },
    )
    assert r.status_code == 422


async def test_proposal_request_identity_version_and_payload_are_stable(env, buyer, product):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    body = {"request_id": str(uuid4()), "expected_version": 1, "proposal_slot": "payment"}
    key = str(uuid4())
    p = await prepare_action(client, buyer, order, "payment", key, body)
    for retry_key in (key, str(uuid4())):
        retry = await client.post(
            f"/api/v1/orders/{order['id']}/payment-proposals",
            headers={**buyer, "Idempotency-Key": retry_key},
            json=body,
        )
        assert retry.status_code == 200 and retry.json() == p
    for bad_body in ({**body, "expected_version": 2}, {**body, "request_id": str(uuid4())}):
        r = await client.post(
            f"/api/v1/orders/{order['id']}/payment-proposals",
            headers={**buyer, "Idempotency-Key": key},
            json=bad_body,
        )
        assert r.status_code == 409
    stale = await client.post(
        f"/api/v1/orders/{order['id']}/cancel-proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"request_id": str(uuid4()), "expected_version": 0},
    )
    assert stale.status_code == 422
    stale = await client.post(
        f"/api/v1/orders/{order['id']}/cancel-proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"request_id": str(uuid4()), "expected_version": 2},
    )
    assert stale.status_code == 409
    assert (
        row(db, "SELECT count(*) n FROM action_proposals WHERE action_type='MOCK_PAYMENT'")["n"]
        == 1
    )


async def test_logistics_role_store_version_and_timeline(env, buyer, buyer2, product):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    merchant = await merchant_auth(client)
    url = f"/api/v1/merchant/orders/{order['id']}"
    assert (
        await client.post(url + "/ship", headers=merchant, json={"expected_version": 1})
    ).status_code == 409
    assert (
        await client.post(url + "/deliver", headers=merchant, json={"expected_version": 1})
    ).status_code == 409
    assert (
        await client.post(url + "/ship", headers=buyer, json={"expected_version": 1})
    ).status_code == 403
    p, c = await action(client, buyer, order, "payment")
    assert (await execute_action(client, buyer, order, p, c, "payment")).status_code == 201
    with db.begin() as conn:
        conn.execute(
            text("UPDATE users SET store_id=:store WHERE login='merchant'"), {"store": uuid4()}
        )
    assert (
        await client.post(url + "/ship", headers=merchant, json={"expected_version": 2})
    ).status_code == 404
    with db.begin() as conn:
        conn.execute(
            text("UPDATE users SET store_id=:store WHERE login='merchant'"),
            {"store": order["store_id"]},
        )
    shipped = await client.post(url + "/ship", headers=merchant, json={"expected_version": 2})
    assert shipped.status_code == 200 and shipped.json()["status"] == "SHIPPED"
    assert (
        await client.post(url + "/ship", headers=merchant, json={"expected_version": 2})
    ).status_code == 409
    delivered = await client.post(url + "/deliver", headers=merchant, json={"expected_version": 3})
    assert delivered.status_code == 200 and delivered.json()["status"] == "DELIVERED"
    assert (
        await client.post(url + "/deliver", headers=merchant, json={"expected_version": 4})
    ).status_code == 409
    timeline = await client.get(f"/api/v1/orders/{order['id']}/shipment", headers=buyer)
    assert timeline.status_code == 200
    assert [e["status"] for e in timeline.json()["events"]] == ["PAID", "SHIPPED", "DELIVERED"]
    assert (
        await client.get(f"/api/v1/orders/{order['id']}/shipment", headers=buyer2)
    ).status_code == 404
    state, stock = facts(db, order["id"], product)
    assert state["paid_at"] <= state["shipped_at"] <= state["delivered_at"]
    assert stock == {"on_hand": 19, "reserved": 0}
    filtered = await client.get("/api/v1/orders?status=DELIVERED", headers=buyer)
    assert filtered.status_code == 200 and len(filtered.json()["items"]) == 1


@pytest.mark.parametrize("kind,expected", [("payment", "SUCCEEDED"), ("cancel", "CANCELLED")])
async def test_rollback_after_business_writes_then_original_action_retry(
    env, buyer, product, monkeypatch, kind, expected
):
    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    p, c = await action(client, buyer, order, kind)
    from agentmall.orders import lifecycle
    from agentmall.payments import service

    service = service if kind == "payment" else lifecycle

    original = service.write_lifecycle_event

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic failure after real business event write")

    monkeypatch.setattr(service, "write_lifecycle_event", fail)
    key = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as faulty:
        r = await execute_action(faulty, buyer, order, p, c, kind, key)
    assert r.status_code == 500
    state, stock = facts(db, order["id"], product)
    assert state["status"] == "PENDING_PAYMENT" and stock == {"on_hand": 20, "reserved": 1}
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 0
    assert (
        row(db, "SELECT consumed_at FROM confirmations WHERE id=:id", id=c["confirmation_id"])[
            "consumed_at"
        ]
        is None
    )
    assert (
        row(
            db,
            "SELECT count(*) n FROM idempotency_requests WHERE action_id=:id",
            id=p["proposal_id"],
        )["n"]
        == 0
    )
    monkeypatch.setattr(service, "write_lifecycle_event", original)
    assert (await execute_action(client, buyer, order, p, c, kind, key)).json()[
        "status"
    ] == expected


async def test_0003_upgrade_preserves_t02_orders_and_receipts(env, buyer, product):
    from alembic import command
    from alembic.config import Config
    from conftest import ROOT

    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    cfg = Config(str(ROOT / "backend/alembic.ini"))

    def snapshot():
        return row(
            db,
            "SELECT (to_jsonb(o)-ARRAY['paid_at','shipped_at','delivered_at']) order_row, "
            "(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM idempotency_requests i) receipts, "
            "(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM confirmations c) confirmations "
            "FROM orders o WHERE id=:id",
            id=order["id"],
        )

    before = snapshot()
    with db.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0002")
    assert row(db, "SELECT version_num FROM alembic_version")["version_num"] == "0002"
    with db.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        command.check(cfg)
    assert snapshot() == before
    p, c = await action(client, buyer, order, "payment")
    assert (await execute_action(client, buyer, order, p, c, "payment")).status_code == 201


@pytest.mark.parametrize("unique_column", ["order_id", "action_id"])
async def test_payment_database_uniqueness(env, buyer, product, unique_column):
    from sqlalchemy.exc import IntegrityError

    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    p, c = await action(client, buyer, order, "payment")
    await execute_action(client, buyer, order, p, c, "payment")
    other = await create_order(client, buyer, product)
    op, oc = await action(client, buyer, other, "payment")
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO payments(id,order_id,store_id,amount_cents,status,provider,action_id) "
                "SELECT :id,:order_id,store_id,amount_cents,status,provider,:action_id "
                "FROM payments LIMIT 1"
            ),
            {
                "id": uuid4(),
                "order_id": order["id"] if unique_column == "order_id" else other["id"],
                "action_id": p["proposal_id"]
                if unique_column == "action_id"
                else op["proposal_id"],
            },
        )
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 1


async def test_commit_ack_loss_is_not_declined_and_retries_original_receipt(
    env, buyer, product, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSessionTransaction

    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    p, c = await action(client, buyer, order, "payment")
    original = AsyncSessionTransaction.__aexit__

    async def lost_ack(self, *args):
        result = await original(self, *args)
        if row(db, "SELECT count(*) n FROM payments")["n"] == 1:
            raise ConnectionError("synthetic lost commit acknowledgement")
        return result

    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", lost_ack)
    key = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as faulty:
        r = await execute_action(faulty, buyer, order, p, c, "payment", key)
    assert r.status_code == 500
    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", original)
    recovered = (await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=buyer)).json()
    assert recovered["result"]["status"] == "SUCCEEDED"
    retry = await execute_action(client, buyer, order, p, c, "payment", key)
    assert retry.status_code == 200 and retry.json() == recovered["result"]
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 1
    assert facts(db, order["id"], product)[1] == {"on_hand": 19, "reserved": 0}


async def test_adapter_exception_is_not_a_completed_decline(env, buyer, product):
    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    p, c = await action(client, buyer, order, "payment")

    class Unavailable:
        def decide(self):
            raise ConnectionError("synthetic adapter failure")

    app.state.mock_payment_adapter = Unavailable()
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as faulty:
        r = await execute_action(faulty, buyer, order, p, c, "payment")
    assert r.status_code == 500
    assert (
        row(db, "SELECT consumed_at FROM confirmations WHERE id=:id", id=c["confirmation_id"])[
            "consumed_at"
        ]
        is None
    )
    assert row(db, "SELECT count(*) n FROM payments")["n"] == 0
    assert facts(db, order["id"], product)[1] == {"on_hand": 20, "reserved": 1}


async def test_agent_purchase_recovery_ignores_order_action_slot(env, buyer, product):
    client, _, _, _ = env
    order = await create_order(client, buyer, product)
    request_id = str(uuid4())
    proposal = await client.post(
        f"/api/v1/orders/{order['id']}/cancel-proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"request_id": request_id, "proposal_slot": "agent_purchase", "expected_version": 1},
    )
    assert proposal.status_code == 201
    response = await client.post(
        "/api/v1/agent/messages",
        headers=buyer,
        json={"request_id": request_id, "message": "查询原购买提案"},
    )
    assert response.status_code == 200
    assert response.json()["proposal_refs"] == []
    assert response.json()["status"] == "blocked"
