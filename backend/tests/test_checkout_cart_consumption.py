"""Real PostgreSQL cart consumption, rollback and concurrent-edit regression."""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from checkout_helpers import confirm, counts, execute, prepare, request_body, timed_proposal
from conftest import ROOT, row
from httpx import ASGITransport, AsyncClient, ReadError
from sqlalchemy import MetaData, Table, text
from sqlalchemy.exc import IntegrityError
from test_checkout import DropOrderResponse
from test_order_concurrency import contend


async def cart_quote(env, buyer, product):
    client = env[0]
    cart = (await client.get("/api/v1/cart", headers=buyer)).json()
    cart = (
        await client.put(
            f"/api/v1/cart/items/{product}",
            headers=buyer,
            json={"quantity": 1, "expected_version": cart["version"]},
        )
    ).json()
    body = {
        "request_id": str(uuid4()),
        "proposal_slot": "web_cart",
        "address_label": "demo_dorm",
        "cart_id": cart["id"],
        "expected_cart_version": cart["version"],
    }
    return cart, await prepare(client, buyer, body=body)


def state(db, cart_id):
    with db.connect() as c:
        version = c.scalar(text("SELECT version FROM carts WHERE id=:id"), {"id": cart_id})
        items = c.execute(
            text(
                "SELECT product_id::text,quantity FROM cart_items "
                "WHERE cart_id=:id ORDER BY product_id"
            ),
            {"id": cart_id},
        ).all()
        return {"version": version, "items": [tuple(r) for r in items]}


async def test_cart_source_is_server_verified_hash_bound_and_immutable(env, buyer, product):
    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    expected = {
        "cart_id": cart["id"],
        "user_id": cart["user_id"],
        "store_id": cart["store_id"],
        "version": 1,
    }
    assert p["canonical_payload"].get("cart_source") == expected
    again = (await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=buyer)).json()
    assert again == p
    with pytest.raises(IntegrityError), db.begin() as c:
        c.execute(
            text(
                "UPDATE action_proposals SET canonical_payload=jsonb_set("
                "canonical_payload, '{cart_source,version}', '999') WHERE id=:id"
            ),
            {"id": p["proposal_id"]},
        )


async def test_success_consumes_once_at_reservation_and_replay_preserves_readded_item(
    env, buyer, product
):
    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(client, buyer, p)
    key = str(uuid4())
    response = await execute(client, buyer, p, c, key)
    assert response.status_code == 201, response.text
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    assert response.json().get("cart_consumption") == "CONSUMED"
    assert row(db, "SELECT status FROM orders")["status"] == "PENDING_PAYMENT"
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 1
    update = await client.put(
        f"/api/v1/cart/items/{product}", headers=buyer, json={"quantity": 2, "expected_version": 2}
    )
    assert update.status_code == 200
    for replay_key in [key, str(uuid4())]:
        repeated = await execute(client, buyer, p, c, replay_key)
        assert repeated.status_code == 200 and repeated.json() == response.json()
    assert state(db, cart["id"]) == {"version": 3, "items": [(product, 2)]}
    assert counts(db)["orders"] == counts(db)["business_events"] == 1


@pytest.mark.parametrize("change", ["add_b", "modify_a", "remove_readd_a"])
async def test_changed_cart_is_preserved_while_original_snapshot_still_orders(
    env, buyer, product, change
):
    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    other = str(
        row(db, "SELECT id FROM products WHERE id<>:id AND active ORDER BY id LIMIT 1", id=product)[
            "id"
        ]
    )
    target = other if change == "add_b" else product
    if change == "remove_readd_a":
        r = await client.request(
            "DELETE", f"/api/v1/cart/items/{product}", headers=buyer, json={"expected_version": 1}
        )
        assert r.status_code == 200
    version = 2 if change == "remove_readd_a" else 1
    r = await client.put(
        f"/api/v1/cart/items/{target}",
        headers=buyer,
        json={"quantity": 2, "expected_version": version},
    )
    assert r.status_code == 200
    before = state(db, cart["id"])
    receipt = await execute(client, buyer, p, await confirm(client, buyer, p))
    assert receipt.status_code == 201, receipt.text
    assert receipt.json().get("cart_consumption") == "SKIPPED_CART_CHANGED"
    assert state(db, cart["id"]) == before
    assert row(db, "SELECT quantity FROM order_items")["quantity"] == 1
    assert (await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=buyer)).json()[
        "canonical_payload"
    ] == p["canonical_payload"]


async def test_explicit_sku_and_cart_like_slot_never_consumes_cart(env, buyer, product):
    client, db, _, _ = env
    cart, _ = await cart_quote(env, buyer, product)
    p = await prepare(client, buyer, body=request_body(product, proposal_slot="web_cart"))
    assert "cart_source" not in p["canonical_payload"]
    response = await execute(client, buyer, p, await confirm(client, buyer, p))
    assert response.status_code == 201
    assert response.json().get("cart_consumption") == "NOT_APPLICABLE"
    assert state(db, cart["id"]) == {"version": 1, "items": [(product, 1)]}


async def test_legacy_proposal_without_provenance_is_compatible_but_does_not_consume(
    env, buyer, product
):
    import hashlib

    client, db, _, _ = env
    cart, original = await cart_quote(env, buyer, product)
    table = Table("action_proposals", MetaData(), autoload_with=db)
    with db.begin() as connection:
        data = dict(
            connection.execute(table.select().where(table.c.id == original["proposal_id"]))
            .mappings()
            .one()
        )
        payload = {k: v for k, v in data["canonical_payload"].items() if k != "cart_source"}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        data.update(
            id=uuid4(), origin_request_id=uuid4(), canonical_payload=payload, payload_hash=digest
        )
        connection.execute(table.insert().values(**data))
    p = {**original, "proposal_id": str(data["id"])}
    receipt = await execute(client, buyer, p, await confirm(client, buyer, p))
    assert receipt.status_code == 201
    assert receipt.json().get("cart_consumption") == "NOT_APPLICABLE"
    assert state(db, cart["id"]) == {"version": 1, "items": [(product, 1)]}


@pytest.mark.parametrize("reason", ["reject", "expired", "stock", "catalog_changed"])
async def test_unsuccessful_checkout_never_consumes_cart(env, buyer, product, reason):
    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    if reason == "expired":
        p = timed_proposal(db, p, -1)
        r = await client.post(
            f"/api/v1/proposals/{p['proposal_id']}/confirmations",
            headers=buyer,
            json={"decision": "approve"},
        )
        assert r.status_code == 409
    else:
        c = await confirm(client, buyer, p, "reject" if reason == "reject" else "approve")
        if reason in {"stock", "catalog_changed"}:
            with db.begin() as connection:
                change = "on_hand=0" if reason == "stock" else "catalog_version=catalog_version+1"
                connection.execute(
                    text(f"UPDATE products SET {change} WHERE id=:id"), {"id": product}
                )
        r = await execute(client, buyer, p, c)
        assert r.status_code == 409
    assert state(db, cart["id"]) == {"version": 1, "items": [(product, 1)]}
    assert counts(db)["orders"] == counts(db)["business_events"] == 0
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0
    assert row(db, "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL")["n"] == 0


async def test_fault_after_cart_deletion_rolls_back_cart_and_every_business_effect(
    env, buyer, product, monkeypatch
):
    from agentmall.orders import service

    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(client, buyer, p)
    before = counts(db)
    original = service.write_order_event
    observed = []

    async def fail(session, *args):
        observed.append(
            (
                await session.execute(
                    text(
                        "SELECT version,(SELECT count(*) FROM cart_items "
                        "WHERE cart_id=carts.id) n FROM carts WHERE id=:id"
                    ),
                    {"id": cart["id"]},
                )
            ).one()
        )
        await original(session, *args)
        raise RuntimeError("cart consumption precommit fault")

    monkeypatch.setattr(service, "write_order_event", fail)
    key = str(uuid4())
    with pytest.raises(RuntimeError, match="cart consumption precommit fault"):
        await execute(client, buyer, p, c, key)
    assert counts(db) == before
    assert state(db, cart["id"]) == {"version": 1, "items": [(product, 1)]}
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0
    assert (
        row(db, "SELECT consumed_at FROM confirmations WHERE id=:id", id=c["confirmation_id"])[
            "consumed_at"
        ]
        is None
    )
    assert [tuple(x) for x in observed] == [(2, 0)]
    monkeypatch.setattr(service, "write_order_event", original)
    assert (await execute(client, buyer, p, c, key)).status_code == 201
    assert state(db, cart["id"]) == {"version": 2, "items": []}


async def test_lost_http_response_recovers_one_cart_consumption_in_fresh_app(env, buyer, product):
    from agentmall.main import create_app

    _, db, app, settings = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(env[0], buyer, p)
    key = str(uuid4())
    async with AsyncClient(transport=DropOrderResponse(app=app), base_url="http://test") as lossy:
        with pytest.raises(ReadError):
            await execute(lossy, buyer, p, c, key)
    fresh = create_app(settings)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=fresh), base_url="http://test"
        ) as rebooted:
            receipt = await execute(rebooted, buyer, p, c, key)
            assert receipt.status_code == 200
            assert receipt.json().get("cart_consumption") == "CONSUMED"
    finally:
        await fresh.state.engine.dispose()
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    assert counts(db)["orders"] == counts(db)["business_events"] == 1


async def test_other_user_store_and_forged_cart_source_cannot_consume(env, buyer, buyer2, product):
    client, db, app, settings = env
    cart, p = await cart_quote(env, buyer, product)
    before = counts(db)
    c = await confirm(client, buyer, p)
    assert (await execute(client, buyer2, p, c)).status_code == 404
    body = request_body(product, cart_source={"cart_id": cart["id"], "version": 1})
    response = await client.post(
        "/api/v1/checkout/proposals", headers={**buyer, "Idempotency-Key": str(uuid4())}, json=body
    )
    assert response.status_code == 422
    app.state.settings = settings.model_copy(update={"storefront_id": uuid4()})
    assert (await execute(client, buyer, p, c)).status_code == 404
    app.state.settings = settings
    assert state(db, cart["id"]) == {"version": 1, "items": [(product, 1)]}
    assert counts(db) == before


@pytest.mark.parametrize("same_key", [True, False])
async def test_concurrent_replay_waits_on_cart_and_consumes_at_most_once(
    env, buyer, product, same_key
):
    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(client, buyer, p)
    k = str(uuid4())
    results, _ = await contend(
        env,
        "SELECT id FROM carts WHERE id=:id FOR UPDATE",
        {"id": cart["id"]},
        [
            execute(client, buyer, p, c, k),
            execute(client, buyer, p, c, k if same_key else str(uuid4())),
        ],
    )
    assert sorted(r.status_code for r in results) == [200, 201]
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    assert results[0].json() == results[1].json()
    assert counts(db)["orders"] == counts(db)["business_events"] == 1


async def test_cart_edit_wins_real_row_lock_then_checkout_preserves_changed_cart(
    env, buyer, product
):
    from test_order_concurrency import wait_for_waiters

    client, db, _, settings = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(client, buyer, p)
    with db.begin() as editor:
        editor.execute(text("SELECT id FROM carts WHERE id=:id FOR UPDATE"), {"id": cart["id"]})
        task = asyncio.create_task(execute(client, buyer, p, c))
        try:
            await wait_for_waiters(db, settings.db_schema, 1)
            editor.execute(
                text("UPDATE cart_items SET quantity=2 WHERE cart_id=:id"), {"id": cart["id"]}
            )
            editor.execute(
                text("UPDATE carts SET version=version+1 WHERE id=:id"), {"id": cart["id"]}
            )
            editor.commit()
        finally:
            if editor.in_transaction():
                editor.rollback()
            response = await task
    assert response.status_code == 201
    assert response.json().get("cart_consumption") == "SKIPPED_CART_CHANGED"
    assert state(db, cart["id"]) == {"version": 2, "items": [(product, 2)]}
    assert row(db, "SELECT quantity FROM order_items")["quantity"] == 1


async def test_expiry_crossing_cart_lock_rolls_back_provisional_deletion(env, buyer, product):
    from datetime import datetime

    client, db, _, _ = env
    cart, p = await cart_quote(env, buyer, product)
    p = timed_proposal(db, p, 1)
    c = await confirm(client, buyer, p)
    results, released = await contend(
        env,
        "SELECT id FROM carts WHERE id=:id FOR UPDATE",
        {"id": cart["id"]},
        [execute(client, buyer, p, c)],
        datetime.fromisoformat(p["expires_at"]),
    )
    assert results[0].status_code == 409
    assert results[0].json()["code"] == "STALE_PROPOSAL"
    assert released >= datetime.fromisoformat(p["expires_at"])
    assert state(db, cart["id"]) == {"version": 1, "items": [(product, 1)]}
    assert counts(db)["orders"] == 0


async def test_cart_commit_then_sigkill_recovery_preserves_later_new_cart(
    env, buyer, product, tmp_path
):
    client, db, _, settings = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(client, buyer, p)
    task = {
        "schema": settings.db_schema,
        "proposal_id": p["proposal_id"],
        "confirmation_id": c["confirmation_id"],
        "key": str(uuid4()),
        "marker": str(tmp_path / "committed.json"),
    }
    config = tmp_path / "config.json"
    config.write_text(json.dumps(task))
    worker = ROOT / "backend/tests/cart_checkout_worker.py"
    with (tmp_path / "worker.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(worker),
            str(config),
            "pause",
            cwd=ROOT,
            env=dict(os.environ),
            stdout=log,
            stderr=log,
        )
        try:
            async with asyncio.timeout(12):
                while not await asyncio.to_thread(Path(task["marker"]).exists):
                    assert process.returncode is None, (tmp_path / "worker.log").read_text()
                    await asyncio.sleep(0.02)
            process.kill()
            assert await process.wait() == -9
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    first = json.loads(await asyncio.to_thread(Path(task["marker"]).read_text))
    assert first["status"] == 201
    update = await client.put(
        f"/api/v1/cart/items/{product}", headers=buyer, json={"quantity": 2, "expected_version": 2}
    )
    assert update.status_code == 200
    with (tmp_path / "replay.log").open("w") as log:
        restart = await asyncio.create_subprocess_exec(
            sys.executable,
            str(worker),
            str(config),
            cwd=ROOT,
            env=dict(os.environ),
            stdout=log,
            stderr=log,
        )
        try:
            assert await asyncio.wait_for(restart.wait(), 12) == 0
        finally:
            if restart.returncode is None:
                restart.kill()
                await restart.wait()
    replay = json.loads(await asyncio.to_thread(Path(task["marker"]).read_text))
    assert replay["status"] == 200 and replay["body"] == first["body"]
    assert state(db, cart["id"]) == {"version": 3, "items": [(product, 2)]}
    assert counts(db)["orders"] == counts(db)["business_events"] == 1
    print("CART_COMMIT_SIGKILL=-9 recovery=200 orders=1 cart_version=3 later_quantity=2")


@pytest.mark.parametrize("transition", ["paid", "declined", "cancelled", "expired"])
async def test_later_order_lifecycle_never_consumes_again_or_restores_cart(
    env, buyer, product, transition, monkeypatch
):
    from datetime import timedelta
    from uuid import UUID

    from lifecycle_helpers import execute_action, prepare_action

    from agentmall.orders import lifecycle
    from agentmall.payments.service import MockPaymentAdapter

    client, db, app, _ = env
    cart, p = await cart_quote(env, buyer, product)
    response = await execute(client, buyer, p, await confirm(client, buyer, p))
    assert response.status_code == 201
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    order = (
        await client.get(f"/api/v1/orders/{response.json()['order_id']}", headers=buyer)
    ).json()
    if transition == "expired":

        async def clock(session):
            return (await session.scalar(text("SELECT clock_timestamp()"))) + timedelta(minutes=16)

        monkeypatch.setattr(lifecycle, "database_now", clock)
        for _ in range(2):
            async with app.state.sessions.begin() as session:
                result = await lifecycle.expire_order(session, UUID(order["id"]))
        assert result.status == "EXPIRED" and result.changed is False
    else:
        kind = "cancel" if transition == "cancelled" else "payment"
        if transition == "declined":
            app.state.mock_payment_adapter = MockPaymentAdapter("DECLINED")
        action = await prepare_action(client, buyer, order, kind)
        approval = await confirm(client, buyer, action)
        key = str(uuid4())
        first = await execute_action(client, buyer, order, action, approval, kind, key)
        assert first.status_code in {200, 201}, first.text
        replay = await execute_action(client, buyer, order, action, approval, kind, key)
        assert replay.status_code == 200 and replay.json() == first.json()
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    assert counts(db)["orders"] == 1
    expected = {
        "paid": "PAID",
        "declined": "PENDING_PAYMENT",
        "cancelled": "CANCELLED",
        "expired": "EXPIRED",
    }[transition]
    assert row(db, "SELECT status FROM orders")["status"] == expected
    assert row(db, "SELECT count(*) n FROM payments")["n"] == (1 if transition == "paid" else 0)
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == (
        1 if transition == "declined" else 0
    )


async def test_readd_item_fk_lock_and_checkout_have_one_safe_order(
    env, buyer, product, monkeypatch
):
    from test_order_concurrency import wait_for_waiters

    from agentmall.orders import service

    client, db, _, settings = env
    cart, p = await cart_quote(env, buyer, product)
    c = await confirm(client, buyer, p)
    removed = await client.request(
        "DELETE", f"/api/v1/cart/items/{product}", headers=buyer, json={"expected_version": 1}
    )
    assert removed.status_code == 200
    products_locked, allow_consumption = asyncio.Event(), asyncio.Event()
    original = service.consume_checkout_cart

    async def pause(*args, **kwargs):
        products_locked.set()
        await allow_consumption.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "consume_checkout_cart", pause)
    async with asyncio.timeout(12):
        checkout = asyncio.create_task(execute(client, buyer, p, c))
        addition = None
        try:
            await products_locked.wait()
            addition = asyncio.create_task(
                client.put(
                    f"/api/v1/cart/items/{product}",
                    headers=buyer,
                    json={"quantity": 2, "expected_version": 2},
                )
            )
            await wait_for_waiters(db, settings.db_schema, 1)
        finally:
            allow_consumption.set()
            results = await asyncio.gather(checkout, *([addition] if addition else []))
    assert [r.status_code for r in results] == [201, 200], [r.text for r in results]
    assert state(db, cart["id"]) == {"version": 3, "items": [(product, 2)]}
    assert counts(db)["orders"] == counts(db)["business_events"] == 1
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 1


async def test_same_origin_distinct_prepare_keys_and_execute_do_not_reverse_locks(
    env, buyer, product, monkeypatch
):
    from test_order_concurrency import wait_for_waiters

    from agentmall.actions import service

    client, db, _, settings = env
    cart, _ = await cart_quote(env, buyer, product)
    request_id, gate = uuid4(), uuid4().int % (2**63)
    body = {
        "request_id": str(request_id),
        "proposal_slot": "race",
        "address_label": "demo_dorm",
        "cart_id": cart["id"],
        "expected_cart_version": 1,
    }
    with db.begin() as conn:
        conn.execute(
            text(f"""
            CREATE FUNCTION p1_prepare_gate() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.origin_request_id = '{request_id}'::uuid THEN
              PERFORM pg_advisory_xact_lock({gate}); END IF; RETURN NEW; END $$;
            CREATE TRIGGER p1_prepare_gate BEFORE INSERT ON action_proposals
            FOR EACH ROW EXECUTE FUNCTION p1_prepare_gate();
        """)
        )
    second_holds_cart, allow_proposal_lock = asyncio.Event(), asyncio.Event()
    original, calls = service.get_proposal, 0

    async def pause(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            second_holds_cart.set()
            await allow_proposal_lock.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "get_proposal", pause)
    tasks = []
    async with asyncio.timeout(12):
        try:
            with db.begin() as blocker:
                blocker.execute(text("SELECT pg_advisory_xact_lock(:gate)"), {"gate": gate})
                tasks.append(
                    asyncio.create_task(
                        client.post(
                            "/api/v1/checkout/proposals",
                            headers={**buyer, "Idempotency-Key": str(uuid4())},
                            json=body,
                        )
                    )
                )
                await wait_for_waiters(db, settings.db_schema, 1)
                tasks.append(
                    asyncio.create_task(
                        client.post(
                            "/api/v1/checkout/proposals",
                            headers={**buyer, "Idempotency-Key": str(uuid4())},
                            json=body,
                        )
                    )
                )
                await wait_for_waiters(db, settings.db_schema, 2)
                blocker.rollback()
            first = await tasks[0]
            assert first.status_code == 201, first.text
            p = first.json()
            await second_holds_cart.wait()
            confirmation = await confirm(client, buyer, p)
            tasks.append(asyncio.create_task(execute(client, buyer, p, confirmation)))
            await wait_for_waiters(db, settings.db_schema, 1)
        finally:
            allow_proposal_lock.set()
            results = await asyncio.gather(*tasks)
    assert sorted(r.status_code for r in results[:2]) == [200, 201], [r.text for r in results]
    assert results[2].status_code == 201, results[2].text
    assert state(db, cart["id"]) == {"version": 2, "items": []}
    assert counts(db)["orders"] == counts(db)["business_events"] == 1
