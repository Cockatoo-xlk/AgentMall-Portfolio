from uuid import uuid4

import pytest
from checkout_helpers import confirm, counts, execute, prepare, request_body, timed_proposal
from conftest import row
from httpx import ASGITransport, AsyncClient, ReadError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def test_checkout_snapshot_confirmation_receipt_and_queries(env, buyer, product):
    client, db, _, _ = env
    original = row(db, "SELECT * FROM products WHERE id=:id", id=product)
    p = await prepare(client, buyer, product, body=request_body(product, 2))
    assert p["status"] == "PENDING"
    payload = p["canonical_payload"]
    assert payload["total_cents"] == 2 * original["price_cents"]
    assert payload["items"][0]["quantity"] == 2
    assert payload["items"][0]["unit_price_cents"] == original["price_cents"]
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0
    c = await confirm(client, buyer, p)
    assert c["decision"] == "approve" and c["consumed_at"] is None
    assert counts(db)["orders"] == 0
    r = await execute(client, buyer, p, c)
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["status"] == "PENDING_PAYMENT"
    order = (await client.get("/api/v1/orders/" + receipt["order_id"], headers=buyer)).json()
    assert order["total_cents"] == payload["total_cents"]
    assert order["items"][0]["name_snapshot"] == original["name"]
    assert order["items"][0]["attributes_snapshot"] == original["attributes"]
    assert order["items"][0]["unit_price_cents"] == original["price_cents"]
    assert order["items"][0]["quantity"] == 2
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == {
        "on_hand": original["on_hand"],
        "reserved": 2,
    }
    assert counts(db)["orders"] == counts(db)["order_items"] == counts(db)["business_events"] == 1
    recovered = (await client.get("/api/v1/proposals/" + p["proposal_id"], headers=buyer)).json()
    assert recovered["status"] == "EXECUTED"
    assert recovered["result"] == receipt
    assert recovered["confirmation"]["consumed_at"] is not None
    page = await client.get("/api/v1/orders", headers=buyer)
    assert page.status_code == 200 and page.json()["items"][0] == order
    with db.begin() as conn:
        conn.execute(
            text("UPDATE products SET name='新名称',price_cents=1 WHERE id=:id"), {"id": product}
        )
    assert (
        await client.get("/api/v1/orders/" + receipt["order_id"], headers=buyer)
    ).json() == order


async def test_cart_source_is_snapshotted_and_cart_version_checked(env, buyer, product):
    client, db, _, _ = env
    cart = (await client.get("/api/v1/cart", headers=buyer)).json()
    await client.put(
        "/api/v1/cart/items/" + product,
        headers=buyer,
        json={"quantity": 3, "expected_version": cart["version"]},
    )
    body = {
        "request_id": str(uuid4()),
        "proposal_slot": "checkout",
        "address_label": "demo_home",
        "cart_id": cart["id"],
        "expected_cart_version": cart["version"] + 1,
    }
    p = await prepare(client, buyer, body=body)
    assert p["canonical_payload"]["items"][0]["quantity"] == 3
    await client.put(
        "/api/v1/cart/items/" + product,
        headers=buyer,
        json={"quantity": 1, "expected_version": cart["version"] + 1},
    )
    # Original request returns its immutable proposal despite a changed source cart.
    again = await prepare(client, buyer, body=body, expected=200)
    assert again["proposal_id"] == p["proposal_id"]
    c = await confirm(client, buyer, p)
    assert (await execute(client, buyer, p, c)).status_code == 201
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 3
    stale = await client.post(
        "/api/v1/checkout/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={**body, "request_id": str(uuid4())},
    )
    assert stale.status_code == 409


@pytest.mark.parametrize(
    "mutate",
    [
        {"items": []},
        {"items": None},
        {"quantity": 0},
        {"quantity": 11},
        {"quantity": True},
        {"quantity": 1.5},
        {"quantity": "2"},
        {"address_label": "real-address"},
        {"confirmed": True},
        {"user_id": str(uuid4())},
        {"store_id": str(uuid4())},
        {"price_cents": 1},
        {"cart_id": str(uuid4()), "expected_cart_version": 0},
    ],
)
async def test_invalid_checkout_inputs_rejected(client, buyer, product, mutate):
    body = request_body(product)
    if "quantity" in mutate:
        body["items"][0]["quantity"] = mutate["quantity"]
    else:
        body.update(mutate)
    r = await client.post(
        "/api/v1/checkout/proposals", headers={**buyer, "Idempotency-Key": str(uuid4())}, json=body
    )
    assert r.status_code == 422, r.text


async def test_normalization_retries_and_key_conflicts(env, buyer, product):
    client, db, _, _ = env
    body = request_body(product)
    body["items"] *= 2
    key = str(uuid4())
    p = await prepare(client, buyer, body=body, key=key)
    merged = {**body, "items": [{"product_id": product, "quantity": 2}]}
    p2 = await prepare(client, buyer, body=merged, key=key, expected=200)
    assert p2 == p
    assert (await prepare(client, buyer, body=merged, expected=200)) == p
    for headers, changed in [
        ({**buyer, "Idempotency-Key": key}, request_body(product, 3)),
        ({**buyer, "Idempotency-Key": str(uuid4())}, {**merged, "address_label": "demo_home"}),
    ]:
        r = await client.post("/api/v1/checkout/proposals", headers=headers, json=changed)
        assert r.status_code == 409
    assert row(db, "SELECT count(*) AS n FROM action_proposals")["n"] == 1
    overflow = request_body(product, 6)
    overflow["items"] *= 2
    r = await client.post(
        "/api/v1/checkout/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json=overflow,
    )
    assert r.status_code == 422


async def test_reject_and_confirmation_decision_immutable(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p, "reject")
    assert await confirm(client, buyer, p, "reject", expected=200) == c
    r = await client.post(
        f"/api/v1/proposals/{p['proposal_id']}/confirmations",
        headers=buyer,
        json={"decision": "approve"},
    )
    assert r.status_code == 409
    assert (await execute(client, buyer, p, c)).status_code == 409
    assert counts(db)["orders"] == 0


async def test_missing_and_mismatched_confirmations(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    r = await execute(client, buyer, p, {"confirmation_id": str(uuid4())})
    assert r.status_code == 404
    other = await prepare(client, buyer, product)
    wrong = await confirm(client, buyer, other)
    assert (await execute(client, buyer, p, wrong)).status_code == 404
    r = await client.post(
        "/api/v1/orders",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"proposal_id": p["proposal_id"], "confirmed": True},
    )
    assert r.status_code == 422 and counts(db)["orders"] == 0


async def test_expired_proposal_cannot_confirm_or_execute(env, buyer, product):
    client, db, _, _ = env
    p = timed_proposal(db, await prepare(client, buyer, product), -1)
    r = await client.post(
        f"/api/v1/proposals/{p['proposal_id']}/confirmations",
        headers=buyer,
        json={"decision": "approve"},
    )
    assert r.status_code == 409 and r.json()["code"] == "STALE_PROPOSAL"
    fetched = (await client.get("/api/v1/proposals/" + p["proposal_id"], headers=buyer)).json()
    assert fetched["status"] == "EXPIRED"
    assert counts(db)["orders"] == 0


@pytest.mark.parametrize(
    "change,code",
    [
        ("price_cents=price_cents+1", "STALE_PROPOSAL"),
        ("catalog_version=catalog_version+1", "STALE_PROPOSAL"),
        ("active=false", "STALE_PROPOSAL"),
        ("on_hand=0", "INSUFFICIENT_STOCK"),
    ],
)
async def test_revalidate_product_under_transaction(env, buyer, product, change, code):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    before = counts(db)
    with db.begin() as conn:
        conn.execute(text(f"UPDATE products SET {change} WHERE id=:id"), {"id": product})
    r = await execute(client, buyer, p, c)
    assert r.status_code == 409 and r.json()["code"] == code
    assert counts(db) == before
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0


async def test_cross_user_and_store_authorization(env, buyer, buyer2, product):
    client, db, app, settings = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    assert (
        await client.get("/api/v1/proposals/" + p["proposal_id"], headers=buyer2)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/proposals/{p['proposal_id']}/confirmations",
            headers=buyer2,
            json={"decision": "approve"},
        )
    ).status_code == 404
    assert (await execute(client, buyer2, p, c)).status_code == 404
    r = await execute(client, buyer, p, c)
    assert r.status_code == 201
    oid = r.json()["order_id"]
    assert (await client.get("/api/v1/orders/" + oid, headers=buyer2)).status_code == 404
    assert (await client.get("/api/v1/orders", headers=buyer2)).json()["items"] == []
    app.state.settings = settings.model_copy(update={"storefront_id": uuid4()})
    assert (
        await client.get("/api/v1/proposals/" + p["proposal_id"], headers=buyer)
    ).status_code == 404
    assert (await execute(client, buyer, p, c)).status_code == 404
    assert (await client.get("/api/v1/orders/" + oid, headers=buyer)).status_code == 404
    assert (await client.get("/api/v1/orders", headers=buyer)).json()["items"] == []
    r = await client.post(
        "/api/v1/checkout/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json=request_body(product),
    )
    assert r.status_code == 404
    assert counts(db)["orders"] == 1


async def test_other_users_cart_and_empty_cart_rejected(client, buyer, buyer2):
    cart = (await client.get("/api/v1/cart", headers=buyer)).json()
    body = {
        "request_id": str(uuid4()),
        "proposal_slot": "checkout",
        "address_label": "demo_dorm",
        "cart_id": cart["id"],
        "expected_cart_version": cart["version"],
    }
    for actor, code in [(buyer2, 404), (buyer, 409)]:
        r = await client.post(
            "/api/v1/checkout/proposals",
            headers={**actor, "Idempotency-Key": str(uuid4())},
            json=body,
        )
        assert r.status_code == code


async def test_idempotency_execution_bindings_and_recovery(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    key = str(uuid4())
    first = await execute(client, buyer, p, c, key)
    assert first.status_code == 201
    for repeat_key in (key, str(uuid4())):
        r = await execute(client, buyer, p, c, repeat_key)
        assert r.status_code == 200 and r.json() == first.json()
    assert (
        await execute(client, buyer, p, {"confirmation_id": str(uuid4())}, key)
    ).status_code == 409
    other = await prepare(client, buyer, product)
    other_c = await confirm(client, buyer, other)
    assert (await execute(client, buyer, other, other_c, key)).status_code == 409
    assert counts(db)["orders"] == counts(db)["business_events"] == 1


class DropOrderResponse(ASGITransport):
    async def handle_async_request(self, request):
        r = await super().handle_async_request(request)
        if (
            request.url.path == "/api/v1/orders"
            and request.method == "POST"
            and r.status_code == 201
        ):
            await r.aclose()
            raise ReadError("lost committed order response", request=request)
        return r


async def test_committed_response_loss_replays_durable_receipt(env, buyer, product):
    client, db, app, settings = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    key = str(uuid4())
    async with AsyncClient(transport=DropOrderResponse(app=app), base_url="http://test") as lossy:
        with pytest.raises(ReadError):
            await execute(lossy, buyer, p, c, key)
    # A fresh app / connection pool proves replay is not process-local state.
    from agentmall.main import create_app

    fresh = create_app(settings)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=fresh), base_url="http://test"
        ) as rebooted:
            replay = await execute(rebooted, buyer, p, c, key)
            assert replay.status_code == 200
            recovered = (
                await rebooted.get("/api/v1/proposals/" + p["proposal_id"], headers=buyer)
            ).json()
            assert recovered["result"] == replay.json()
    finally:
        await fresh.state.engine.dispose()
    assert counts(db)["orders"] == counts(db)["order_items"] == counts(db)["business_events"] == 1


async def test_failure_after_reservation_rolls_back_everything(env, buyer, product, monkeypatch):
    from agentmall.orders import service

    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    before = counts(db)
    key = str(uuid4())
    original = service.write_order_event

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("fault before transaction commit")

    monkeypatch.setattr(service, "write_order_event", fail)
    with pytest.raises(RuntimeError, match="fault before transaction commit"):
        await execute(client, buyer, p, c, key)
    assert counts(db) == before
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0
    assert (
        row(db, "SELECT consumed_at FROM confirmations WHERE id=:id", id=c["confirmation_id"])[
            "consumed_at"
        ]
        is None
    )
    monkeypatch.setattr(service, "write_order_event", original)
    assert (await execute(client, buyer, p, c, key)).status_code == 201


async def test_proposal_and_order_snapshots_immutable_in_database(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    with pytest.raises(IntegrityError), db.begin() as conn:
        conn.execute(
            text("UPDATE action_proposals SET canonical_payload='{}'::jsonb WHERE id=:id"),
            {"id": p["proposal_id"]},
        )
    c = await confirm(client, buyer, p)
    r = await execute(client, buyer, p, c)
    assert r.status_code == 201
    with pytest.raises(IntegrityError), db.begin() as conn:
        conn.execute(
            text("UPDATE order_items SET unit_price_cents=0 WHERE order_id=:id"),
            {"id": r.json()["order_id"]},
        )


async def test_required_idempotency_key_and_merchant_denial(client, buyer, product):
    r = await client.post("/api/v1/checkout/proposals", headers=buyer, json=request_body(product))
    assert r.status_code == 422
    from conftest import PASSWORD

    login = await client.post(
        "/api/v1/auth/login", json={"login": "merchant", "password": PASSWORD}
    )
    merchant = {"Authorization": "Bearer " + login.json()["access_token"]}
    r = await client.post(
        "/api/v1/checkout/proposals",
        headers={**merchant, "Idempotency-Key": str(uuid4())},
        json=request_body(product),
    )
    assert r.status_code == 403
    assert (await client.get("/api/v1/orders", headers=merchant)).status_code == 403


async def test_success_replay_survives_expiry_and_catalog_changes(env, buyer, product):
    import asyncio
    from datetime import datetime

    client, db, _, _ = env
    p = timed_proposal(db, await prepare(client, buyer, product), 1)
    c = await confirm(client, buyer, p)
    key = str(uuid4())
    first = await execute(client, buyer, p, c, key)
    assert first.status_code == 201
    expiry = datetime.fromisoformat(p["expires_at"])
    while True:
        if row(db, "SELECT clock_timestamp() AS now")["now"] >= expiry:
            break
        await asyncio.sleep(0.01)
    with db.begin() as conn:
        conn.execute(
            text("UPDATE products SET active=false,price_cents=price_cents+1 WHERE id=:id"),
            {"id": product},
        )
    for replay_key in (key, str(uuid4())):
        replay = await execute(client, buyer, p, c, replay_key)
        assert replay.status_code == 200 and replay.json() == first.json()
    assert counts(db)["orders"] == 1


async def test_order_pagination_and_client_fields_cannot_set_amount(client, buyer, product):
    ids = set()
    for _ in range(2):
        p = await prepare(client, buyer, product)
        c = await confirm(client, buyer, p)
        r = await client.post(
            "/api/v1/orders",
            headers={**buyer, "Idempotency-Key": str(uuid4())},
            json={
                "proposal_id": p["proposal_id"],
                "confirmation_id": c["confirmation_id"],
                "total_cents": 1,
            },
        )
        assert r.status_code == 422
        r = await execute(client, buyer, p, c)
        assert r.status_code == 201
        ids.add(r.json()["order_id"])
    page1 = (await client.get("/api/v1/orders", headers=buyer, params={"limit": 1})).json()
    page2 = (
        await client.get(
            "/api/v1/orders", headers=buyer, params={"limit": 1, "cursor": page1["next_cursor"]}
        )
    ).json()
    assert {page1["items"][0]["id"], page2["items"][0]["id"]} == ids
    assert page2["next_cursor"] is None
    assert (
        await client.get("/api/v1/orders", headers=buyer, params={"user_id": str(uuid4())})
    ).status_code == 422
