"""Real PostgreSQL refund conservation, uniqueness, rollback and lock contracts."""

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import httpx
import pytest
from aftersales_helpers import (
    cancel_proposal,
    delivered_order,
    execute_cancel,
    execute_refund,
    merchant_headers,
    receive_case,
    received_case,
    refund_proposal,
    requested_case,
    return_proposal,
    review_case,
    submit_case,
)
from checkout_helpers import confirm, timed_proposal
from conftest import PASSWORD, row
from sqlalchemy import MetaData, Table, text
from sqlalchemy.exc import IntegrityError
from test_expiry_race import ORDER_LOCK, controlled_race
from test_lifecycle_http import LoseCommittedPaymentResponse, loopback_server


async def approved_refund(client, merchant, case):
    proposal = await refund_proposal(client, merchant, case)
    return proposal, await confirm(client, merchant, proposal)


def assert_refunded(db, order, case, product, before, proposal):
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "REFUNDED",
        "version": order["version"] + 1,
    }
    assert row(
        db, "SELECT status,version,restockable FROM aftersales_cases WHERE id=:id", id=case["id"]
    ) == {"status": "REFUNDED", "version": case["version"] + 1, "restockable": False}
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == before
    assert row(db, "SELECT count(*) n FROM refunds WHERE case_id=:id", id=case["id"])["n"] == 1
    assert (
        row(
            db,
            "SELECT count(*) n FROM business_events WHERE action_id=:id "
            "AND event_type='REFUND_SUCCEEDED'",
            id=proposal["proposal_id"],
        )["n"]
        == 1
    )
    assert (
        row(
            db,
            "SELECT count(*) n FROM idempotency_requests WHERE action_id=:id",
            id=proposal["proposal_id"],
        )["n"]
        == 1
    )


def assert_unconsumed(db, confirmation):
    assert (
        row(
            db,
            "SELECT consumed_at FROM confirmations WHERE id=:id",
            id=confirmation["confirmation_id"],
        )["consumed_at"]
        is None
    )


async def test_refund_full_payment_once_and_never_restocks(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    payment = row(db, "SELECT id,amount_cents FROM payments WHERE order_id=:id", id=order["id"])
    # A later catalog price is never an authority for the refund amount.
    with db.begin() as connection:
        connection.execute(text("UPDATE products SET price_cents=1 WHERE id=:id"), {"id": product})
    proposal, confirmation = await approved_refund(client, merchant, case)
    key = str(uuid4())
    response = await execute_refund(client, merchant, case, proposal, confirmation, key)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["action_type"] == "MOCK_REFUND"
    assert receipt["status"] == "SUCCEEDED" and receipt["order_status"] == "REFUNDED"
    assert receipt["amount_cents"] == order["total_cents"] and receipt["currency"] == "CNY"
    assert receipt["refund_id"] == receipt["resource_id"]
    assert receipt["case_id"] == case["id"] and receipt["order_id"] == order["id"]
    assert receipt["payment_id"] == str(payment["id"])
    assert receipt["amount_cents"] == payment["amount_cents"]
    assert receipt["action_id"] == proposal["proposal_id"] and receipt["created_at"]
    for retry_key in (key, str(uuid4())):
        replay = await execute_refund(client, merchant, case, proposal, confirmation, retry_key)
        assert replay.status_code == 200 and replay.json() == receipt
    recovered = await client.get(f"/api/v1/proposals/{proposal['proposal_id']}", headers=merchant)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["result"] == receipt
    assert recovered.json()["confirmation"]["consumed_at"]
    assert_refunded(db, order, case, product, before, proposal)


async def test_two_return_actions_create_only_one_active_case_under_real_lock(env, buyer, product):
    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    actions = []
    for _ in range(2):
        proposal = await return_proposal(client, buyer, order)
        actions.append((proposal, await confirm(client, buyer, proposal)))
    participants = [
        (
            f"return-{number}",
            lambda p=p, c=c: submit_case(client, buyer, p, c),
        )
        for number, (p, c) in enumerate(actions)
    ]
    results, _ = await controlled_race(env, ORDER_LOCK, {"id": order["id"]}, participants)
    assert [response.status_code for response in results] == [201, 409]
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE event_type='RETURN_REQUESTED'")["n"]
        == 1
    )
    assert_unconsumed(db, actions[1][1])
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "DELIVERED",
        "version": order["version"],
    }


@pytest.mark.parametrize("first", ["review", "cancel"])
async def test_review_and_buyer_cancel_serialize_in_both_orders(env, buyer, product, first):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await requested_case(client, buyer, order)
    proposal = await cancel_proposal(client, buyer, case)
    confirmation = await confirm(client, buyer, proposal)
    calls = {
        "review": lambda: review_case(client, merchant, case),
        "cancel": lambda: execute_cancel(client, buyer, case, proposal, confirmation),
    }
    second = "cancel" if first == "review" else "review"
    results, _ = await controlled_race(
        env, ORDER_LOCK, {"id": order["id"]}, [(name, calls[name]) for name in (first, second)]
    )
    assert [response.status_code for response in results] == [200, 409]
    expected_status = "APPROVED" if first == "review" else "CANCELLED"
    assert row(db, "SELECT status,version FROM aftersales_cases WHERE id=:id", id=case["id"]) == {
        "status": expected_status,
        "version": case["version"] + 1,
    }
    assert (
        row(
            db,
            "SELECT count(*) n FROM business_events WHERE aggregate_id=:id "
            "AND event_type IN ('CASE_APPROVED','RETURN_CANCELLED')",
            id=case["id"],
        )["n"]
        == 1
    )
    if first == "review":
        assert_unconsumed(db, confirmation)
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0


@pytest.mark.parametrize("first", ["receive", "refund"])
async def test_repeat_receive_cannot_race_refund_into_duplicate_transition(
    env, buyer, product, first
):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal, confirmation = await approved_refund(client, merchant, case)
    calls = {
        "receive": lambda: receive_case(client, merchant, case),
        "refund": lambda: execute_refund(client, merchant, case, proposal, confirmation),
    }
    names = [first, "refund" if first == "receive" else "receive"]
    results, _ = await controlled_race(
        env, ORDER_LOCK, {"id": order["id"]}, [(name, calls[name]) for name in names]
    )
    assert dict(zip(names, [r.status_code for r in results], strict=True)) == {
        "receive": 409,
        "refund": 201,
    }
    assert_refunded(db, order, case, product, before, proposal)
    assert (
        row(
            db,
            "SELECT count(*) n FROM business_events WHERE aggregate_id=:id "
            "AND event_type='CASE_RECEIVED'",
            id=case["id"],
        )["n"]
        == 1
    )


@pytest.mark.parametrize("first", ["receive", "refund-proposal"])
async def test_receive_and_refund_preparation_validate_state_after_lock(env, buyer, product, first):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await requested_case(client, buyer, order)
    approved = await review_case(client, merchant, case)
    assert approved.status_code == 200, approved.text
    case = approved.json()
    calls = {
        "receive": lambda: receive_case(client, merchant, case),
        "refund-proposal": lambda: client.post(
            f"/api/v1/merchant/after-sales/{case['id']}/refund-proposals",
            headers={**merchant, "Idempotency-Key": str(uuid4())},
            json={"request_id": str(uuid4()), "expected_version": case["version"] + 1},
        ),
    }
    names = [first, "refund-proposal" if first == "receive" else "receive"]
    results, _ = await controlled_race(
        env, ORDER_LOCK, {"id": order["id"]}, [(name, calls[name]) for name in names]
    )
    assert dict(zip(names, [r.status_code for r in results], strict=True)) == {
        "receive": 200,
        "refund-proposal": 201 if first == "receive" else 409,
    }
    assert row(db, "SELECT status,version FROM aftersales_cases WHERE id=:id", id=case["id"]) == {
        "status": "RECEIVED",
        "version": case["version"] + 1,
    }
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0


async def test_two_distinct_refund_actions_cannot_refund_same_payment_twice(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    actions = [await approved_refund(client, merchant, case) for _ in range(2)]
    results, _ = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (f"refund-{number}", lambda p=p, c=c: execute_refund(client, merchant, case, p, c))
            for number, (p, c) in enumerate(actions)
        ],
    )
    assert [r.status_code for r in results] == [201, 409]
    assert_refunded(db, order, case, product, before, actions[0][0])
    assert_unconsumed(db, actions[1][1])
    assert (
        row(
            db,
            "SELECT count(*) n FROM idempotency_requests WHERE action_id=:id",
            id=actions[1][0]["proposal_id"],
        )["n"]
        == 0
    )


@pytest.mark.parametrize("same_key", [True, False])
async def test_same_refund_action_concurrent_keys_replay_one_receipt(env, buyer, product, same_key):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal, confirmation = await approved_refund(client, merchant, case)
    first_key = str(uuid4())
    keys = [first_key, first_key if same_key else str(uuid4())]
    results, _ = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (
                f"refund-{number}",
                lambda key=key: execute_refund(client, merchant, case, proposal, confirmation, key),
            )
            for number, key in enumerate(keys)
        ],
    )
    assert [r.status_code for r in results] == [201, 200]
    assert results[0].json() == results[1].json()
    assert_refunded(db, order, case, product, before, proposal)


@pytest.mark.parametrize("case_status", ["REQUESTED", "APPROVED"])
async def test_refund_before_receipt_has_no_business_side_effects(env, buyer, product, case_status):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await requested_case(client, buyer, order)
    if case_status == "APPROVED":
        approved = await review_case(client, merchant, case)
        assert approved.status_code == 200, approved.text
        case = approved.json()
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    response = await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/refund-proposals",
        headers={**merchant, "Idempotency-Key": str(uuid4())},
        json={"request_id": str(uuid4()), "expected_version": case["version"]},
    )
    assert response.status_code == 409, response.text
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert (
        row(db, "SELECT count(*) n FROM action_proposals WHERE action_type='MOCK_REFUND'")["n"] == 0
    )
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "DELIVERED",
        "version": order["version"],
    }
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == before


async def test_refund_requires_the_matching_explicit_approved_confirmation(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    proposal = await refund_proposal(client, merchant, case)
    missing = await execute_refund(
        client, merchant, case, proposal, {"confirmation_id": str(uuid4())}
    )
    assert missing.status_code == 404, missing.text
    rejected = await confirm(client, merchant, proposal, "reject")
    denial = await execute_refund(client, merchant, case, proposal, rejected)
    assert denial.status_code == 409, denial.text
    other_proposal, approval = await approved_refund(client, merchant, case)
    mismatched = await execute_refund(client, merchant, case, other_proposal, rejected)
    assert mismatched.status_code in {404, 409}, mismatched.text
    assert_unconsumed(db, approval)
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert row(db, "SELECT status,version FROM aftersales_cases WHERE id=:id", id=case["id"]) == {
        "status": "RECEIVED",
        "version": case["version"],
    }


async def test_refund_key_cannot_rebind_to_another_confirmation(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal, confirmation = await approved_refund(client, merchant, case)
    key = str(uuid4())
    result = await execute_refund(client, merchant, case, proposal, confirmation, key)
    assert result.status_code == 201, result.text
    conflicting = await execute_refund(
        client, merchant, case, proposal, {"confirmation_id": str(uuid4())}, key
    )
    assert conflicting.status_code == 409, conflicting.text
    replay = await execute_refund(client, merchant, case, proposal, confirmation, key)
    assert replay.status_code == 200 and replay.json() == result.json()
    assert_refunded(db, order, case, product, before, proposal)


async def test_refund_expiring_while_blocked_on_order_is_rejected_before_writes(
    env, buyer, product
):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal = timed_proposal(db, await refund_proposal(client, merchant, case), 1)
    confirmation = await confirm(client, merchant, proposal)
    results, _ = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            (
                "expiring-refund",
                lambda: execute_refund(client, merchant, case, proposal, confirmation),
            )
        ],
        release_after=datetime.fromisoformat(proposal["expires_at"]),
    )
    assert results[0].status_code == 409, results[0].text
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert_unconsumed(db, confirmation)
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "DELIVERED",
        "version": order["version"],
    }
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_cents", 1),
        ("payment_id", str(uuid4())),
        ("user_id", str(uuid4())),
        ("restockable", True),
    ],
)
async def test_refund_rejects_client_money_identity_and_inventory_controls(
    env, buyer, product, field, value
):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    response = await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/refund-proposals",
        headers={**merchant, "Idempotency-Key": str(uuid4())},
        json={"request_id": str(uuid4()), "expected_version": case["version"], field: value},
    )
    assert response.status_code == 422, response.text
    proposal, confirmation = await approved_refund(client, merchant, case)
    response = await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/refund",
        headers={**merchant, "Idempotency-Key": str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
            field: value,
        },
    )
    assert response.status_code == 422, response.text
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert_unconsumed(db, confirmation)


async def test_cross_store_merchant_is_denied_while_real_refund_waits(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal, confirmation = await approved_refund(client, merchant, case)
    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,login,password_hash,role,store_id,disabled) "
                "SELECT :id,'other-merchant',password_hash,'merchant',:store,false "
                "FROM users WHERE login='merchant'"
            ),
            {"id": uuid4(), "store": uuid4()},
        )
    login = await client.post(
        "/api/v1/auth/login", json={"login": "other-merchant", "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    other = {"Authorization": "Bearer " + login.json()["access_token"]}
    denied = []

    async def concurrent_refunds():
        authorized = asyncio.create_task(
            execute_refund(client, merchant, case, proposal, confirmation)
        )
        try:
            denied.append(await execute_refund(client, other, case, proposal, confirmation))
            return await authorized
        finally:
            if not authorized.done():
                authorized.cancel()
                await asyncio.gather(authorized, return_exceptions=True)

    results, _ = await controlled_race(
        env, ORDER_LOCK, {"id": order["id"]}, [("authorized-and-foreign", concurrent_refunds)]
    )
    assert denied[0].status_code == 404, denied[0].text
    assert results[0].status_code == 201, results[0].text
    for suffix, payload in (
        (
            "review",
            {"decision": "approve", "reason": "Denied", "expected_version": case["version"]},
        ),
        ("receive", {"expected_version": case["version"]}),
        ("refund-proposals", {"request_id": str(uuid4()), "expected_version": case["version"]}),
    ):
        denied_response = await client.post(
            f"/api/v1/merchant/after-sales/{case['id']}/{suffix}",
            headers={**other, "Idempotency-Key": str(uuid4())},
            json=payload,
        )
        assert denied_response.status_code == 404, denied_response.text
    assert_refunded(db, order, case, product, before, proposal)


@pytest.mark.parametrize("unique_column", ["case_id", "payment_id", "action_id"])
async def test_refund_unique_constraints_reject_individual_duplicate_references(
    env, buyer, product, unique_column
):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    proposal, confirmation = await approved_refund(client, merchant, case)
    result = await execute_refund(client, merchant, case, proposal, confirmation)
    assert result.status_code == 201, result.text
    other_order = await delivered_order(client, buyer, product, merchant)
    other_case = await received_case(client, buyer, other_order, merchant)
    other_proposal, _ = await approved_refund(client, merchant, other_case)
    other_payment = row(db, "SELECT id FROM payments WHERE order_id=:id", id=other_order["id"])
    table = Table("refunds", MetaData(), autoload_with=db)
    with db.connect() as connection:
        original = dict(connection.execute(table.select()).mappings().one())
    duplicate = {
        **original,
        "id": uuid4(),
        "order_id": UUID(other_order["id"]),
        "case_id": UUID(other_case["id"]),
        "payment_id": other_payment["id"],
        "action_id": UUID(other_proposal["proposal_id"]),
        unique_column: original[unique_column],
    }
    with pytest.raises(IntegrityError) as caught, db.begin() as connection:
        connection.execute(table.insert().values(**duplicate))
    assert caught.value.orig.sqlstate == "23505"
    assert caught.value.orig.diag.constraint_name == "uq_refund_" + unique_column.removesuffix(
        "_id"
    )
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 1


async def test_precommit_fault_rolls_back_refund_and_original_action_is_retryable(
    env, buyer, product, monkeypatch
):
    from agentmall.aftersales import service

    client, db, app, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal, confirmation = await approved_refund(client, merchant, case)
    original = service.write_aftersales_event

    async def fail_after_real_writes(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic refund failure after business event flush")

    monkeypatch.setattr(service, "write_aftersales_event", fail_after_real_writes)
    key = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as faulty:
        result = await execute_refund(faulty, merchant, case, proposal, confirmation, key)
    assert result.status_code == 500, result.text
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert row(db, "SELECT status,version FROM orders WHERE id=:id", id=order["id"]) == {
        "status": "DELIVERED",
        "version": order["version"],
    }
    assert row(db, "SELECT status,version FROM aftersales_cases WHERE id=:id", id=case["id"]) == {
        "status": "RECEIVED",
        "version": case["version"],
    }
    assert (
        row(
            db,
            "SELECT count(*) n FROM business_events WHERE action_id=:id",
            id=proposal["proposal_id"],
        )["n"]
        == 0
    )
    assert (
        row(
            db,
            "SELECT count(*) n FROM idempotency_requests WHERE action_id=:id",
            id=proposal["proposal_id"],
        )["n"]
        == 0
    )
    assert_unconsumed(db, confirmation)
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == before
    monkeypatch.setattr(service, "write_aftersales_event", original)
    result = await execute_refund(client, merchant, case, proposal, confirmation, key)
    assert result.status_code == 201, result.text
    assert_refunded(db, order, case, product, before, proposal)


async def test_lost_commit_ack_replays_committed_refund_without_changing_money(
    env, buyer, product, monkeypatch
):
    from sqlalchemy.ext.asyncio import AsyncSessionTransaction

    client, db, app, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    proposal, confirmation = await approved_refund(client, merchant, case)
    original = AsyncSessionTransaction.__aexit__

    async def lost_ack(self, *args):
        result = await original(self, *args)
        if row(db, "SELECT count(*) n FROM refunds")["n"] == 1:
            raise ConnectionError("synthetic lost refund commit acknowledgement")
        return result

    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", lost_ack)
    key = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as faulty:
        result = await execute_refund(faulty, merchant, case, proposal, confirmation, key)
    assert result.status_code == 500, result.text
    monkeypatch.setattr(AsyncSessionTransaction, "__aexit__", original)
    assert_refunded(db, order, case, product, before, proposal)
    recovered = await client.get(f"/api/v1/proposals/{proposal['proposal_id']}", headers=merchant)
    assert recovered.status_code == 200, recovered.text
    receipt = recovered.json()["result"]
    assert receipt["status"] == "SUCCEEDED" and receipt["amount_cents"] == order["total_cents"]
    for retry_key in (key, str(uuid4())):
        replay = await execute_refund(client, merchant, case, proposal, confirmation, retry_key)
        assert replay.status_code == 200 and replay.json() == receipt
    assert_refunded(db, order, case, product, before, proposal)


async def test_real_http_refund_response_loss_recovers_same_committed_receipt(env, product):
    _, db, app, _ = env
    async with loopback_server(app) as client:
        login = await client.post(
            "/api/v1/auth/login", json={"login": "buyer1", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        buyer = {"Authorization": "Bearer " + login.json()["access_token"]}
        merchant = await merchant_headers(client)
        order = await delivered_order(client, buyer, product, merchant)
        case = await received_case(client, buyer, order, merchant)
        before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
        proposal, confirmation = await approved_refund(client, merchant, case)
        key = str(uuid4())
        # The existing transport drops any real committed 201 response, including refunds.
        transport = LoseCommittedPaymentResponse()
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=transport, trust_env=False, timeout=5
        ) as losing_client:
            with pytest.raises(httpx.ReadError, match="Synthetic loss"):
                await execute_refund(losing_client, merchant, case, proposal, confirmation, key)
        assert_refunded(db, order, case, product, before, proposal)
        recovered = await client.get(
            f"/api/v1/proposals/{proposal['proposal_id']}", headers=merchant
        )
        assert recovered.status_code == 200, recovered.text
        receipt = recovered.json()["result"]
        assert receipt == transport.committed_receipt
        for retry_key in (key, str(uuid4())):
            replay = await execute_refund(client, merchant, case, proposal, confirmation, retry_key)
            assert replay.status_code == 200 and replay.json() == receipt
        assert_refunded(db, order, case, product, before, proposal)
