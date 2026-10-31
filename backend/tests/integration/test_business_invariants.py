"""New T11 compositions, not copies of T02/T05/T06 two-request tests."""

from uuid import UUID, uuid4

import httpx
import pytest
from aftersales_helpers import (
    delivered_order,
    execute_refund,
    merchant_headers,
    received_case,
    refund_proposal,
)
from checkout_helpers import confirm, execute, prepare
from conftest import PASSWORD
from lifecycle_helpers import create_order, execute_action, prepare_action, timed_order
from sqlalchemy import text
from test_lifecycle_http import loopback_server

from agentmall.orders.lifecycle import expire_order

from .harness import DropResponse, race, scalar, verify
from .oracle import inspect_database


async def test_oracle_detects_check_valid_orphan_reservation(durable_env, buyer, product, evidence):
    import asyncio
    import json
    from copy import deepcopy

    from t09_helpers import confirm as graph_confirm
    from t09_helpers import purchase_models, resume, start, thread

    from .conftest import bounded

    env = durable_env
    evidence["case_id"] = "O01"
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def blocked_transaction():
        try:
            async with env[2].state.sessions.begin() as session:
                await session.execute(
                    text("UPDATE products SET reserved=1 WHERE id=:id"), {"id": product}
                )
                entered.set()
                await asyncio.Event().wait()
        finally:
            cleaned.set()

    with pytest.raises(TimeoutError):
        await bounded(blocked_transaction, seconds=0.2)()
    assert entered.is_set() and cleaned.is_set()
    assert scalar(env, "SELECT reserved FROM products WHERE id=:id", id=product) == 0
    evidence["deadline_probe"] = {"seconds": 0.2, "cancelled": True, "rollback_verified": True}
    assert inspect_database(env)["violations"] == []

    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET reserved=1 WHERE id=:id"), {"id": product})
    result = inspect_database(env)
    evidence["deliberate_invalid_state"] = result["violations"]
    assert [v["rule"] for v in result["violations"]] == ["RESERVATION_MISMATCH"]
    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET reserved=0 WHERE id=:id"), {"id": product})
    assert inspect_database(env)["violations"] == []

    # The oracle must not vacuously accept a completed Run with missing business output.
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    cid = await graph_confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    completed = await resume(env, buyer, tid, run, cid)
    assert completed.status_code == 200 and completed.json()["status"] == "COMPLETED"
    original = scalar(env, "SELECT result FROM agent_runs WHERE id=:id", id=run["id"])
    omitted = deepcopy(original)
    omitted["entity_refs"] = [r for r in omitted["entity_refs"] if r["kind"] != "order"]
    controls = []
    try:
        for corrupted, expected in [
            (None, "COMPLETED_RUN_RESULT_MISSING"),
            ({}, "COMPLETED_RUN_RESULT_MISSING"),
            (omitted, "RUN_COMMITTED_RECEIPT_MISSING"),
        ]:
            with env[1].begin() as conn:
                conn.execute(
                    text("UPDATE agent_runs SET result=CAST(:value AS jsonb) WHERE id=:id"),
                    {"value": json.dumps(corrupted), "id": run["id"]},
                )
            detected = inspect_database(env)["violations"]
            controls.append({"expected": expected, "observed": detected})
            assert expected in {v["rule"] for v in detected}
    finally:
        with env[1].begin() as conn:
            conn.execute(
                text("UPDATE agent_runs SET result=CAST(:value AS jsonb) WHERE id=:id"),
                {"value": json.dumps(original), "id": run["id"]},
            )
        evidence["completed_run_negative_controls"] = controls
    verify(env, evidence)

    # Missing refund audit is a violation even when financial rows and stock are correct.
    merchant = await merchant_headers(env[0])
    delivered = await delivered_order(env[0], buyer, product, merchant)
    case = await received_case(env[0], buyer, delivered, merchant)
    refund = await refund_proposal(env[0], merchant, case)
    approval = await confirm(env[0], merchant, refund)
    paid_back = await execute_refund(env[0], merchant, case, refund, approval)
    assert paid_back.status_code == 201
    from sqlalchemy import MetaData, Table

    table = Table("business_events", MetaData(), autoload_with=env[1])
    with env[1].begin() as conn:
        original_event = dict(
            conn.execute(table.select().where(table.c.action_id == refund["proposal_id"]))
            .mappings()
            .one()
        )
        conn.execute(table.delete().where(table.c.id == original_event["id"]))
    try:
        detected = inspect_database(env)["violations"]
        evidence["refund_event_negative_control"] = detected
        assert "REFUND_EVENT_MISSING" in {v["rule"] for v in detected}
    finally:
        with env[1].begin() as conn:
            conn.execute(table.insert().values(**original_event))
    verify(env, evidence)


async def approved(client, auth, product):
    p = await prepare(client, auth, product)
    return p, await confirm(client, auth, p)


async def test_fifty_buyers_ten_units_bounded_contention(env, product, evidence):
    evidence["case_id"] = "B01"
    client, db, _, _ = env
    with db.begin() as c:
        c.execute(text("UPDATE products SET on_hand=10,reserved=0 WHERE id=:id"), {"id": product})
        for n in range(50):
            c.execute(
                text(
                    "INSERT INTO users(id,login,password_hash,role,disabled) "
                    "SELECT :id,:login,password_hash,'buyer',false FROM users WHERE login='buyer1'"
                ),
                {"id": uuid4(), "login": f"t11-buyer-{n}"},
            )
    evidence["initial"] = inspect_database(env)
    actions = []
    for n in range(50):
        login = await client.post(
            "/api/v1/auth/login", json={"login": f"t11-buyer-{n}", "password": PASSWORD}
        )
        assert login.status_code == 200
        auth = {"Authorization": "Bearer " + login.json()["access_token"]}
        p, c = await approved(client, auth, product)
        actions.append((auth, p, c, str(uuid4())))
    results = await race(
        env,
        evidence,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [(f"buyer-{n}", lambda a=a: execute(client, *a)) for n, a in enumerate(actions)],
    )
    success = [(a, r) for a, r in zip(actions, results, strict=True) if r.status_code == 201]
    refused = [
        r for r in results if r.status_code == 409 and r.json()["code"] == "INSUFFICIENT_STOCK"
    ]
    evidence["stock_results"] = {
        "requests": len(results),
        "created": len(success),
        "insufficient_stock": len(refused),
        "conflicts": sum(r.status_code == 409 for r in results) - len(refused),
        "timeouts": 0,
        "other_errors": len(results) - len(success) - len(refused),
    }
    assert len(success) == 10 and len(refused) == 40
    for action, result in success:
        replay = await execute(client, *action)
        assert replay.status_code == 200 and replay.json() == result.json()
    state = verify(env, evidence)
    assert state["counts"]["orders"] == state["counts"]["business_events"] == 10
    assert state["inventory"][product]["on_hand"] == state["inventory"][product]["reserved"] == 10
    assert sum(c["consumed_at"] is not None for c in state["confirmations"]) == 10
    assert (
        scalar(
            env,
            "SELECT count(*) FROM confirmations c JOIN orders o ON o.proposal_id=c.proposal_id "
            "WHERE c.consumed_at IS NULL",
        )
        == 0
    )


@pytest.mark.parametrize("mode", ["same_key", "different_keys", "conflicting_payload"])
async def test_twelve_checkout_replays_and_conflicts(env, buyer, product, evidence, mode):
    evidence["case_id"] = "B02_" + mode
    client = env[0]
    p, c = await approved(client, buyer, product)
    key = str(uuid4())
    calls = []
    for n in range(12):
        confirmation = (
            {"confirmation_id": str(uuid4())} if mode == "conflicting_payload" and n % 2 else c
        )
        k = str(uuid4()) if mode == "different_keys" else key
        calls.append((f"checkout-{n}", lambda c=confirmation, k=k: execute(client, buyer, p, c, k)))
    results = await race(
        env,
        evidence,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        calls,
        ordered=True,
    )
    assert results[0].status_code == 201
    for n, r in enumerate(results[1:], 1):
        if mode == "conflicting_payload" and n % 2:
            assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_CONFLICT"
        else:
            assert r.status_code == 200 and r.json() == results[0].json()
    replay = await execute(client, buyer, p, c, key if mode != "different_keys" else str(uuid4()))
    assert replay.status_code == 200 and replay.json() == results[0].json()
    state = verify(env, evidence)
    assert state["counts"]["orders"] == state["counts"]["business_events"] == 1
    assert (
        scalar(
            env,
            "SELECT count(*) FROM idempotency_requests WHERE action_id=:id",
            id=p["proposal_id"],
        )
        == 1
    )


async def maintenance(env, order):
    async with env[2].state.sessions.begin() as session:
        return await expire_order(session, UUID(order["id"]))


@pytest.mark.parametrize(
    "first,cross",
    [
        ("payment", False),
        ("cancel", False),
        ("payment", True),
        ("cancel", True),
        ("maintenance", True),
    ],
)
async def test_five_way_shared_stock_lifecycle(env, buyer, buyer2, product, evidence, first, cross):
    evidence["case_id"] = f"B03_{first}_{'expired' if cross else 'early'}"
    client, db, _, _ = env
    with db.begin() as c:
        c.execute(text("UPDATE products SET on_hand=20 WHERE id=:id"), {"id": product})
    evidence["initial"] = inspect_database(env)
    order = await create_order(client, buyer, product, quantity=2)
    peer = await create_order(client, buyer2, product, quantity=3)
    actions = {}
    for name in ("payment", "cancel"):
        p = await prepare_action(client, buyer, order, name)
        actions[name] = (p, await confirm(client, buyer, p))
    pp = await prepare_action(client, buyer2, peer, "payment")
    pc = await confirm(client, buyer2, pp)
    np, nc = await approved(client, buyer2, product)
    expiry = timed_order(db, order["id"], 1.8) if cross else None
    evidence["expires_at"] = expiry or order["expires_at"]
    functions = {
        "payment": lambda: execute_action(client, buyer, order, *actions["payment"], "payment"),
        "cancel": lambda: execute_action(client, buyer, order, *actions["cancel"], "cancel"),
        "maintenance": lambda: maintenance(env, order),
        "peer-payment": lambda: execute_action(client, buyer2, peer, pp, pc, "payment"),
        "new-checkout": lambda: execute(client, buyer2, np, nc),
    }
    # For maintenance-first, wait until expiry before queuing; it must lock products too.
    # Other crossing variants enter before expiry, and prove product-lock post-wait time.
    if first == "maintenance":
        from .harness import wait_clock

        await wait_clock(env, expiry)
    order_names = [
        first,
        *[n for n in ("payment", "cancel", "maintenance") if n != first],
        "peer-payment",
        "new-checkout",
    ]
    results = await race(
        env,
        evidence,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [(n, functions[n]) for n in order_names],
        ordered=True,
        expires=expiry if cross and first != "maintenance" else None,
    )
    outcomes = dict(zip(order_names, results, strict=True))
    assert outcomes["peer-payment"].status_code == 201
    assert outcomes["new-checkout"].status_code == 201
    want = "EXPIRED" if cross else ("PAID" if first == "payment" else "CANCELLED")
    assert scalar(env, "SELECT status FROM orders WHERE id=:id", id=order["id"]) == want
    assert (
        scalar(
            env,
            "SELECT count(*) FROM business_events WHERE aggregate_id=:id AND event_type IN "
            "('ORDER_PAID','ORDER_CANCELLED','ORDER_EXPIRED')",
            id=order["id"],
        )
        == 1
    )
    state = verify(env, evidence)
    assert state["counts"]["payments"] == (2 if want == "PAID" else 1)
    assert state["inventory"][product] == {
        "on_hand": 15 if want == "PAID" else 17,
        "reserved": 1,
        "sold": 5 if want == "PAID" else 3,
    }
    if cross:
        assert all(
            not (hasattr(r, "json") and r.json().get("status") == "SUCCEEDED")
            for n, r in outcomes.items()
            if n in {"payment", "cancel"}
        )
    else:
        assert outcomes["cancel" if first == "payment" else "payment"].status_code == 409
    again = await maintenance(env, order)
    assert not again.changed
    verify(env, evidence)


@pytest.mark.parametrize("mode", ["same_key", "different_keys", "different_actions"])
async def test_twelve_refunds_response_loss_and_replay(env, buyer, product, evidence, mode):
    evidence["case_id"] = "B04_" + mode
    client = env[0]
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    stock = inspect_database(env)["inventory"]
    actions = []
    p = await refund_proposal(client, merchant, case)
    c = await confirm(client, merchant, p)
    key = str(uuid4())
    for n in range(12):
        if n and mode == "different_actions":
            p = await refund_proposal(client, merchant, case)
            c = await confirm(client, merchant, p)
        actions.append((p, c, key if mode == "same_key" else str(uuid4())))
    # All requests traverse a real loopback server; only first successful delivery is dropped.
    async with loopback_server(env[2]) as network:
        transport = DropResponse()
        async with httpx.AsyncClient(
            base_url=network.base_url, transport=transport, timeout=10
        ) as losing:

            async def lost_first():
                with pytest.raises(httpx.ReadError, match="T11 controlled"):
                    await execute_refund(losing, merchant, case, *actions[0])
                # A recorder surrogate is evidence of transport-observed success, not a new request.
                return httpx.Response(201, json=transport.receipt)

            calls = [("refund-0-lost-response", lost_first)] + [
                (f"refund-{n}", lambda a=a: execute_refund(network, merchant, case, *a))
                for n, a in enumerate(actions[1:], 1)
            ]
            results = await race(
                env,
                evidence,
                "SELECT id FROM orders WHERE id=:id FOR UPDATE",
                {"id": order["id"]},
                calls,
                ordered=True,
            )
        evidence["response_loss"] = {
            "kind": "CLIENT_DISCARDED_REAL_HTTP_RESPONSE",
            "original_receipt": transport.receipt,
        }
        assert results[0].status_code == 201
        for r in results[1:]:
            if mode == "different_actions":
                assert r.status_code == 409
            else:
                assert r.status_code == 200 and r.json() == transport.receipt
        found = await network.get(
            f"/api/v1/proposals/{actions[0][0]['proposal_id']}", headers=merchant
        )
        assert found.status_code == 200 and found.json()["result"] == transport.receipt
        replay = await execute_refund(network, merchant, case, *actions[0])
        assert replay.status_code == 200 and replay.json() == transport.receipt
    state = verify(env, evidence)
    assert state["counts"]["refunds"] == 1
    assert state["inventory"] == stock
    assert state["cases"][0]["status"] == state["orders"][0]["status"] == "REFUNDED"
    assert state["refunds"][0]["amount_cents"] == order["total_cents"]
    assert (
        scalar(
            env,
            "SELECT count(*) FROM business_events WHERE event_type='REFUND_SUCCEEDED' "
            "AND aggregate_id=:case AND action_id=:action",
            case=case["id"],
            action=actions[0][0]["proposal_id"],
        )
        == 1
    )
    if mode == "different_actions":
        assert (
            scalar(
                env,
                "SELECT count(*) FROM confirmations c JOIN action_proposals p ON "
                "p.id=c.proposal_id WHERE p.action_type='MOCK_REFUND' AND c.consumed_at IS NOT "
                "NULL",
            )
            == 1
        )
