import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from checkout_helpers import confirm
from conftest import row
from lifecycle_helpers import create_order, execute_action, prepare_action, timed_order
from sqlalchemy import text


@pytest.mark.parametrize("kind", ["payment", "cancel"])
async def test_lifecycle_race_action_proposals_exist(env, buyer, product, kind):
    client, _, _, _ = env
    order = await create_order(client, buyer, product)
    proposal = await prepare_action(client, buyer, order, kind)
    assert proposal["proposal_id"]


async def expire(app, order):
    from agentmall.orders.lifecycle import expire_order

    async with app.state.sessions.begin() as session:
        return await expire_order(session, UUID(order["id"]))


async def approved_action(client, buyer, order, kind):
    proposal = await prepare_action(client, buyer, order, kind)
    confirmation = await confirm(client, buyer, proposal)
    return proposal, confirmation


async def wait_for_blocked(db, schema, blocker_pid, tasks):
    """Prove every active participant is transitively blocked by our independent PG session."""
    deadline = asyncio.get_running_loop().time() + 2
    while True:
        with db.connect() as connection:
            waiters = (
                connection.execute(
                    text(
                        "SELECT pid,pg_blocking_pids(pid) AS blockers,wait_event,query "
                        "FROM pg_stat_activity WHERE application_name=:name "
                        "AND state='active' AND wait_event_type='Lock'"
                    ),
                    {"name": f"agentmall:{schema}"},
                )
                .mappings()
                .all()
            )
        graph = {entry["pid"]: entry["blockers"] for entry in waiters}

        def reaches_blocker(pid, seen=frozenset(), graph=graph):
            if pid == blocker_pid:
                return True
            if pid in seen:
                return False
            return any(reaches_blocker(parent, seen | {pid}) for parent in graph.get(pid, []))

        if len(waiters) == len(tasks) and all(reaches_blocker(pid) for pid in graph):
            evidence = [{"pid": entry["pid"], "blockers": entry["blockers"]} for entry in waiters]
            print("PG lifecycle lock evidence:", {"blocker": blocker_pid, "waiters": evidence})
            return evidence
        for task in tasks:
            assert not task.done(), f"Participant finished before lock barrier: {task.result()!r}"
        assert asyncio.get_running_loop().time() < deadline, (
            f"Expected {len(tasks)} real PG waiters rooted at {blocker_pid}; observed {waiters}"
        )
        await asyncio.sleep(0.01)


async def controlled_race(env, lock_sql, params, participants, release_after=None):
    """Queue participants in explicit order; always release and drain, including failed barriers."""
    _, db, _, settings = env
    tasks = []
    barrier_failure = None
    released_at = None
    with db.connect() as blocker:
        transaction = blocker.begin()
        try:
            blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
            blocker.execute(text(lock_sql), params)
            for label, participant in participants:
                tasks.append(asyncio.create_task(participant(), name=label))
                await wait_for_blocked(db, settings.db_schema, blocker_pid, tasks)
            if release_after is not None:
                assert row(db, "SELECT clock_timestamp() AS now")["now"] < release_after, (
                    "Participants must reach their real lock waits before the expiry boundary"
                )
                deadline = asyncio.get_running_loop().time() + 2
                while row(db, "SELECT clock_timestamp() AS now")["now"] < release_after:  # noqa: ASYNC110
                    assert asyncio.get_running_loop().time() < deadline, "Expiry barrier timed out"
                    await asyncio.sleep(0.01)
            released_at = row(db, "SELECT clock_timestamp() AS now")["now"]
        except BaseException as error:
            barrier_failure = error
        finally:
            transaction.rollback()
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=5
                )
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
    if barrier_failure is not None:
        raise barrier_failure
    for result in results:
        if isinstance(result, BaseException):
            raise result
    print(
        "PG lifecycle race outcome:",
        {
            "release_at": released_at.isoformat(),
            "outcomes": {
                name: result.model_dump(mode="json")
                if hasattr(result, "model_dump")
                else result.json()
                for (name, _), result in zip(participants, results, strict=True)
            },
        },
    )
    return results, released_at


def stock(db, product):
    return dict(row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product))


def assert_final(db, order, product, before, status, quantity=1):
    persisted = row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"])
    assert persisted == {"status": status, "version": order["version"] + 1}
    assert stock(db, product) == {
        "on_hand": before["on_hand"] - (quantity if status == "PAID" else 0),
        "reserved": before["reserved"] - quantity,
    }
    assert row(
        db,
        "SELECT count(*) AS n FROM payments WHERE order_id=:id AND status='SUCCEEDED'",
        id=order["id"],
    )["n"] == (1 if status == "PAID" else 0)
    assert (
        row(
            db,
            "SELECT count(*) AS n FROM business_events WHERE aggregate_id=:id "
            "AND event_type IN ('ORDER_PAID','ORDER_CANCELLED','ORDER_EXPIRED')",
            id=order["id"],
        )["n"]
        == 1
    )


ORDER_LOCK = "SELECT id FROM orders WHERE id=:id FOR UPDATE"
PRODUCT_LOCK = "SELECT id FROM products WHERE id=:id FOR UPDATE"


@pytest.mark.parametrize("kind,want", [("payment", "PAID"), ("cancel", "CANCELLED")])
async def test_same_action_different_keys_serialize_once(env, buyer, product, kind, want):
    client, db, _, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    before = stock(db, product)
    proposal, confirmation = await approved_action(client, buyer, order, kind)
    keys = [str(uuid4()), str(uuid4())]
    participants = [
        (
            f"{kind}-{number}",
            lambda key=key: execute_action(client, buyer, order, proposal, confirmation, kind, key),
        )
        for number, key in enumerate(keys)
    ]
    results, _ = await controlled_race(env, ORDER_LOCK, {"id": order["id"]}, participants)
    assert sorted(r.status_code for r in results) == (
        [200, 201] if kind == "payment" else [200, 200]
    )
    assert results[0].json() == results[1].json()
    for key in keys:
        replay = await execute_action(client, buyer, order, proposal, confirmation, kind, key)
        assert replay.status_code == 200 and replay.json() == results[0].json()
    assert_final(db, order, product, before, want, quantity=2)
    assert (
        row(
            db,
            "SELECT count(*) AS n FROM idempotency_requests WHERE action_id=:id",
            id=proposal["proposal_id"],
        )["n"]
        == 1
    )


@pytest.mark.parametrize("kind,want", [("payment", "PAID"), ("cancel", "CANCELLED")])
async def test_distinct_actions_on_same_order_cannot_transition_twice(
    env, buyer, product, kind, want
):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    before = stock(db, product)
    actions = [await approved_action(client, buyer, order, kind) for _ in range(2)]
    results, _ = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (
                f"{kind}-{number}",
                lambda action=action: execute_action(client, buyer, order, *action, kind),
            )
            for number, action in enumerate(actions)
        ],
    )
    assert [result.status_code for result in results] == [201 if kind == "payment" else 200, 409]
    assert_final(db, order, product, before, want)


async def test_concurrent_decline_is_durable_after_adapter_changes(env, buyer, product):
    from agentmall.payments.service import MockPaymentAdapter

    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    before = stock(db, product)
    app.state.mock_payment_adapter = MockPaymentAdapter("DECLINED")
    proposal, confirmation = await approved_action(client, buyer, order, "payment")
    keys = [str(uuid4()), str(uuid4())]
    results, _ = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (
                f"declined-{number}",
                lambda key=key: execute_action(
                    client, buyer, order, proposal, confirmation, "payment", key
                ),
            )
            for number, key in enumerate(keys)
        ],
    )
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json() == results[1].json() and results[0].json()["status"] == "DECLINED"
    assert stock(db, product) == before
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "PENDING_PAYMENT",
        "version": order["version"],
    }
    assert (
        row(
            db,
            "SELECT count(*) AS n FROM payments WHERE order_id=:id AND status='SUCCEEDED'",
            id=order["id"],
        )["n"]
        == 0
    )
    assert (
        row(
            db,
            "SELECT count(*) AS n FROM business_events WHERE aggregate_id=:id "
            "AND event_type='PAYMENT_DECLINED'",
            id=order["id"],
        )["n"]
        == 1
    )
    app.state.mock_payment_adapter = MockPaymentAdapter("SUCCEEDED")
    for key in [*keys, str(uuid4())]:
        replay = await execute_action(client, buyer, order, proposal, confirmation, "payment", key)
        assert replay.status_code == 200 and replay.json() == results[0].json()
    assert stock(db, product) == before
    fresh_proposal, fresh_confirmation = await approved_action(client, buyer, order, "payment")
    fresh = await execute_action(
        client, buyer, order, fresh_proposal, fresh_confirmation, "payment"
    )
    assert fresh.status_code == 201 and fresh.json()["status"] == "SUCCEEDED"
    assert_final(db, order, product, before, "PAID")


async def test_two_reclaimers_crossing_expiry_release_inventory_once(env, buyer, product):
    client, db, app, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    before = stock(db, product)
    expiry = timed_order(db, order["id"], 0.8)
    results, released = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [("expiry-1", lambda: expire(app, order)), ("expiry-2", lambda: expire(app, order))],
        release_after=expiry,
    )
    assert released >= expiry
    assert [result.status for result in results] == ["EXPIRED", "EXPIRED"]
    assert [result.changed for result in results] == [True, False]
    assert_final(db, order, product, before, "EXPIRED", quantity=2)


@pytest.mark.parametrize("first,want", [("payment", "PAID"), ("cancel", "CANCELLED")])
async def test_payment_cancel_competition_has_one_transition(env, buyer, product, first, want):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    before = stock(db, product)
    actions = {
        kind: await approved_action(client, buyer, order, kind) for kind in ("payment", "cancel")
    }
    kinds = [first, "cancel" if first == "payment" else "payment"]
    participants = [
        (
            kind,
            lambda kind=kind: execute_action(client, buyer, order, *actions[kind], kind),
        )
        for kind in kinds
    ]
    results, released = await controlled_race(env, ORDER_LOCK, {"id": order["id"]}, participants)
    assert released < datetime.fromisoformat(order["expires_at"])
    assert results[0].status_code == (201 if first == "payment" else 200)
    assert results[1].status_code == 409
    assert_final(db, order, product, before, want)


@pytest.mark.parametrize("kind,want", [("payment", "PAID"), ("cancel", "CANCELLED")])
async def test_action_wins_before_expiry_then_reclaimer_is_noop(env, buyer, product, kind, want):
    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    before = stock(db, product)
    proposal, confirmation = await approved_action(client, buyer, order, kind)
    results, released = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (kind, lambda: execute_action(client, buyer, order, proposal, confirmation, kind)),
            ("expiry", lambda: expire(app, order)),
        ],
    )
    assert released < datetime.fromisoformat(order["expires_at"])
    assert results[0].status_code == (201 if kind == "payment" else 200)
    assert results[1].status == want and results[1].changed is False
    assert_final(db, order, product, before, want)


@pytest.mark.parametrize("kind", ["payment", "cancel"])
@pytest.mark.parametrize("first", ["action", "expiry"])
async def test_order_lock_wait_crosses_expiry_for_action_and_reclaimer(
    env, buyer, product, kind, first
):
    client, db, app, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    before = stock(db, product)
    expiry = timed_order(db, order["id"], 0.8)
    proposal, confirmation = await approved_action(client, buyer, order, kind)
    action = (kind, lambda: execute_action(client, buyer, order, proposal, confirmation, kind))
    reclaimer = ("expiry", lambda: expire(app, order))
    participants = [action, reclaimer] if first == "action" else [reclaimer, action]
    results, released = await controlled_race(
        env, ORDER_LOCK, {"id": order["id"]}, participants, release_after=expiry
    )
    assert released >= expiry
    action_result = results[0 if first == "action" else 1]
    expiry_result = results[1 if first == "action" else 0]
    assert action_result.status_code == 200 and action_result.json()["status"] == "EXPIRED"
    assert expiry_result.status == "EXPIRED" and expiry_result.changed is (first == "expiry")
    assert_final(db, order, product, before, "EXPIRED", quantity=2)
    again = await expire(app, order)
    assert again.status == "EXPIRED" and again.changed is False
    assert_final(db, order, product, before, "EXPIRED", quantity=2)


@pytest.mark.parametrize("kind", ["payment", "cancel"])
async def test_product_lock_wait_cannot_preserve_preexpiry_action_eligibility(
    env, buyer, product, kind
):
    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    before = stock(db, product)
    expiry = timed_order(db, order["id"], 0.8)
    proposal, confirmation = await approved_action(client, buyer, order, kind)
    results, released = await controlled_race(
        env,
        PRODUCT_LOCK,
        {"id": product},
        [
            (kind, lambda: execute_action(client, buyer, order, proposal, confirmation, kind)),
            ("expiry", lambda: expire(app, order)),
        ],
        release_after=expiry,
    )
    assert released >= expiry
    assert results[0].status_code == 200 and results[0].json()["status"] == "EXPIRED"
    assert results[1].status == "EXPIRED" and results[1].changed is False
    assert_final(db, order, product, before, "EXPIRED")


@pytest.mark.parametrize("first,want", [("payment", "PAID"), ("cancel", "CANCELLED")])
async def test_three_way_preexpiry_queue_has_one_legal_winner(env, buyer, product, first, want):
    client, db, app, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    before = stock(db, product)
    actions = {
        kind: await approved_action(client, buyer, order, kind) for kind in ("payment", "cancel")
    }
    second = "cancel" if first == "payment" else "payment"
    results, released = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (first, lambda: execute_action(client, buyer, order, *actions[first], first)),
            (second, lambda: execute_action(client, buyer, order, *actions[second], second)),
            ("expiry", lambda: expire(app, order)),
        ],
    )
    assert released < datetime.fromisoformat(order["expires_at"])
    assert results[0].status_code == (201 if first == "payment" else 200)
    assert results[1].status_code == 409
    assert results[2].status == want and results[2].changed is False
    assert_final(db, order, product, before, want, quantity=2)


@pytest.mark.parametrize("first", ["payment", "cancel", "expiry"])
async def test_three_way_order_lock_wait_crosses_expiry(env, buyer, product, first):
    client, db, app, _ = env
    order = await create_order(client, buyer, product, quantity=2)
    before = stock(db, product)
    expiry = timed_order(db, order["id"], 0.8)
    actions = {
        kind: await approved_action(client, buyer, order, kind) for kind in ("payment", "cancel")
    }
    participants = {
        "payment": lambda: execute_action(client, buyer, order, *actions["payment"], "payment"),
        "cancel": lambda: execute_action(client, buyer, order, *actions["cancel"], "cancel"),
        "expiry": lambda: expire(app, order),
    }
    names = [first, *[name for name in participants if name != first]]
    results, released = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [(name, participants[name]) for name in names],
        release_after=expiry,
    )
    assert released >= expiry
    results = dict(zip(names, results, strict=True))
    for kind in ("payment", "cancel"):
        assert results[kind].status_code == 200 and results[kind].json()["status"] == "EXPIRED"
        replay = await execute_action(client, buyer, order, *actions[kind], kind)
        assert replay.status_code == 200 and replay.json() == results[kind].json()
    assert results["expiry"].status == "EXPIRED"
    assert results["expiry"].changed is (first == "expiry")
    assert_final(db, order, product, before, "EXPIRED", quantity=2)


async def test_different_users_orders_share_inventory_without_lost_update(
    env, buyer, buyer2, product
):
    client, db, _, _ = env
    order1 = await create_order(client, buyer, product, quantity=2)
    order2 = await create_order(client, buyer2, product, quantity=3)
    before = stock(db, product)
    action1 = await approved_action(client, buyer, order1, "payment")
    action2 = await approved_action(client, buyer2, order2, "payment")
    results, _ = await controlled_race(
        env,
        PRODUCT_LOCK,
        {"id": product},
        [
            ("buyer1", lambda: execute_action(client, buyer, order1, *action1, "payment")),
            ("buyer2", lambda: execute_action(client, buyer2, order2, *action2, "payment")),
        ],
    )
    assert [result.status_code for result in results] == [201, 201]
    assert stock(db, product) == {"on_hand": before["on_hand"] - 5, "reserved": 0}
    for order in (order1, order2):
        assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
            "status": "PAID",
            "version": order["version"] + 1,
        }
        assert (
            row(
                db,
                "SELECT count(*) AS n FROM payments WHERE order_id=:id AND status='SUCCEEDED'",
                id=order["id"],
            )["n"]
            == 1
        )


@pytest.mark.parametrize("second_kind", ["payment", "cancel"])
async def test_overlapping_multi_product_orders_use_stable_stock_lock_order(
    env, buyer, buyer2, product, second_kind
):
    client, db, _, _ = env
    with db.connect() as connection:
        ids = [
            str(i) for i in connection.scalars(text("SELECT id FROM products ORDER BY id LIMIT 2"))
        ]
    orders = [
        await create_order(
            client, auth, product, items=[{"product_id": pid, "quantity": 1} for pid in sequence]
        )
        for auth, sequence in ((buyer, ids), (buyer2, list(reversed(ids))))
    ]
    before = {pid: stock(db, pid) for pid in ids}
    action1 = await approved_action(client, buyer, orders[0], "payment")
    action2 = await approved_action(client, buyer2, orders[1], second_kind)
    results, _ = await controlled_race(
        env,
        PRODUCT_LOCK,
        {"id": ids[0]},
        [
            ("payment", lambda: execute_action(client, buyer, orders[0], *action1, "payment")),
            (
                f"buyer2-{second_kind}",
                lambda: execute_action(client, buyer2, orders[1], *action2, second_kind),
            ),
        ],
    )
    assert [result.status_code for result in results] == [
        201,
        201 if second_kind == "payment" else 200,
    ]
    for pid in ids:
        assert stock(db, pid) == {
            "on_hand": before[pid]["on_hand"] - (2 if second_kind == "payment" else 1),
            "reserved": 0,
        }
    for order, status in zip(
        orders, ("PAID", "PAID" if second_kind == "payment" else "CANCELLED"), strict=True
    ):
        assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
            "status": status,
            "version": order["version"] + 1,
        }
