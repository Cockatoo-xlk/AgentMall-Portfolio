import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from checkout_helpers import confirm, counts, execute, prepare, request_body, timed_proposal
from conftest import row
from sqlalchemy import text


async def wait_for_waiters(db, schema, n):
    deadline = asyncio.get_running_loop().time() + 2
    while True:
        with db.connect() as c:
            waiting = (
                c.execute(
                    text(
                        "SELECT pid,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity "
                        "WHERE application_name=:name AND wait_event_type='Lock'"
                    ),
                    {"name": f"agentmall:{schema}"},
                )
                .mappings()
                .all()
            )
        if len(waiting) == n and all(w["blockers"] for w in waiting):
            print("PG lock wait evidence:", [dict(w) for w in waiting])
            return
        assert asyncio.get_running_loop().time() < deadline, (
            "Expected real PostgreSQL lock contenders"
        )
        await asyncio.sleep(0.01)


async def contend(env, lock_sql, params, calls, release_after=None):
    _, db, _, settings = env
    with db.begin() as blocker:
        blocker.execute(text(lock_sql), params)
        print("blocker acquired")

        async def participant(number, call):
            print("participant", number, "started")
            result = await call
            print("participant", number, "finished", getattr(result, "status_code", "proposal"))
            return result

        tasks = [asyncio.create_task(participant(n, c)) for n, c in enumerate(calls)]
        try:
            await wait_for_waiters(db, settings.db_schema, len(tasks))
            if release_after:
                # Poll the authoritative database clock, not an in-process event.
                while row(db, "SELECT clock_timestamp() AS now")["now"] < release_after:  # noqa: ASYNC110
                    await asyncio.sleep(0.01)
            released_at = row(db, "SELECT clock_timestamp() AS now")["now"]
        finally:
            blocker.rollback()
            print("blocker released")
            results = await asyncio.gather(*tasks)
    return results, released_at


async def test_last_unit_two_buyers_real_lock_competition(env, buyer, buyer2, product):
    client, db, _, _ = env
    with db.begin() as c:
        c.execute(text("UPDATE products SET on_hand=1 WHERE id=:id"), {"id": product})
    p1 = await prepare(client, buyer, product)
    p2 = await prepare(client, buyer2, product)
    c1 = await confirm(client, buyer, p1)
    c2 = await confirm(client, buyer2, p2)
    results, _ = await contend(
        env,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [execute(client, buyer, p1, c1), execute(client, buyer2, p2, c2)],
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert next(r for r in results if r.status_code == 409).json()["code"] == "INSUFFICIENT_STOCK"
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == {
        "on_hand": 1,
        "reserved": 1,
    }
    assert counts(db)["orders"] == counts(db)["business_events"] == 1


async def test_same_key_concurrent_execution(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    key = str(uuid4())
    results, _ = await contend(
        env,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [execute(client, buyer, p, c, key), execute(client, buyer, p, c, key)],
    )
    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json() == results[1].json()
    assert counts(db)["orders"] == counts(db)["business_events"] == 1


async def test_same_proposal_different_keys_concurrent(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    keys = [str(uuid4()), str(uuid4())]
    results, _ = await contend(
        env,
        "SELECT id FROM action_proposals WHERE id=:id FOR UPDATE",
        {"id": p["proposal_id"]},
        [execute(client, buyer, p, c, k) for k in keys],
    )
    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json() == results[1].json()
    for key in keys:
        assert (await execute(client, buyer, p, c, key)).json() == results[0].json()
    assert counts(db)["orders"] == 1
    assert (
        row(
            db,
            "SELECT count(*) AS n FROM idempotency_requests WHERE action_id=:id",
            id=p["proposal_id"],
        )["n"]
        == 1
    )


async def test_concurrent_proposal_creation_same_request_distinct_keys(env, buyer, product):
    client, db, _, _ = env
    body = request_body(product)
    calls = [
        client.post(
            "/api/v1/checkout/proposals",
            headers={**buyer, "Idempotency-Key": str(uuid4())},
            json=body,
        )
        for _ in range(2)
    ]
    # Preparation intentionally does not lock inventory. A test-only BEFORE INSERT
    # trigger gates both contenders at the real proposal uniqueness boundary.
    gate = uuid4().int % (2**63)
    with db.begin() as connection:
        connection.execute(
            text(f"""
            CREATE FUNCTION test_proposal_gate() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM pg_advisory_xact_lock({gate}); RETURN NEW; END $$;
            CREATE TRIGGER test_gate BEFORE INSERT ON action_proposals
            FOR EACH ROW EXECUTE FUNCTION test_proposal_gate();
        """)
        )
    results, _ = await contend(env, "SELECT pg_advisory_xact_lock(:gate)", {"gate": gate}, calls)
    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json() == results[1].json()
    assert row(db, "SELECT count(*) AS n FROM action_proposals")["n"] == 1
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0


async def test_proposal_expiring_while_waiting_for_stock_lock_is_rejected(env, buyer, product):
    client, db, _, _ = env
    p = timed_proposal(db, await prepare(client, buyer, product), 1)
    c = await confirm(client, buyer, p)
    results, _ = await contend(
        env,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [execute(client, buyer, p, c)],
        datetime.fromisoformat(p["expires_at"]),
    )
    assert results[0].status_code == 409 and results[0].json()["code"] == "STALE_PROPOSAL"
    assert counts(db)["orders"] == 0
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0


async def test_order_expiration_uses_post_lock_clock(env, buyer, product):
    client, db, _, _ = env
    p = await prepare(client, buyer, product)
    c = await confirm(client, buyer, p)
    results, released = await contend(
        env,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [execute(client, buyer, p, c)],
    )
    assert results[0].status_code == 201
    persisted = row(
        db,
        "SELECT created_at,expires_at FROM orders WHERE id=:id",
        id=results[0].json()["order_id"],
    )
    assert persisted["created_at"] >= released
    assert persisted["expires_at"] >= released + timedelta(minutes=15)


async def test_multi_product_reversed_input_uses_stable_lock_order(env, buyer, buyer2, product):
    client, db, _, _ = env
    with db.connect() as c:
        ids = [str(i) for i in c.scalars(text("SELECT id FROM products ORDER BY id LIMIT 2"))]
    bodies = [
        request_body(product, items=[{"product_id": pid, "quantity": 1} for pid in order])
        for order in (ids, list(reversed(ids)))
    ]
    p1 = await prepare(client, buyer, body=bodies[0])
    p2 = await prepare(client, buyer2, body=bodies[1])
    c1 = await confirm(client, buyer, p1)
    c2 = await confirm(client, buyer2, p2)
    results, _ = await contend(
        env,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": ids[0]},
        [execute(client, buyer, p1, c1), execute(client, buyer2, p2, c2)],
    )
    assert [r.status_code for r in results] == [201, 201]
    assert counts(db)["orders"] == 2 and counts(db)["order_items"] == 4
