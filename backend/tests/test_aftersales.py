"""T06 deterministic policies and real PostgreSQL authorization/state contracts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from aftersales_helpers import (
    cancel_proposal,
    delivered_order,
    execute_cancel,
    execute_refund,
    merchant_headers,
    received_case,
    refund_proposal,
    requested_case,
    return_proposal,
    review_case,
    submit_case,
)
from checkout_helpers import confirm
from conftest import ROOT, row
from lifecycle_helpers import create_order
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agentmall.aftersales.policy import evaluate_eligibility
from agentmall.aftersales.service import check_eligibility
from agentmall.identity.service import ActorContext


async def test_unpaid_order_eligibility_is_structured(env, buyer, product):
    client, _, _, _ = env
    order = await create_order(client, buyer, product)
    response = await client.get(
        f"/api/v1/orders/{order['id']}/after-sales-eligibility",
        headers=buyer,
        params={"reason_code": "QUALITY_ISSUE"},
    )
    assert response.status_code == 200
    assert response.json()["eligible"] is False
    assert "NOT_PAID" in response.json()["reason_codes"]


async def test_ineligible_order_cannot_prepare_return(env, buyer, product):
    client, _, _, _ = env
    order = await create_order(client, buyer, product)
    response = await client.post(
        "/api/v1/after-sales/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={
            "request_id": str(uuid4()),
            "order_id": order["id"],
            "expected_version": 1,
            "reason_code": "QUALITY_ISSUE",
            "description": "合成故障",
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "delta,eligible", [(timedelta(days=7), True), (timedelta(days=7, microseconds=1), False)]
)
def test_fixed_utc_policy_seven_day_boundary(delta, eligible):
    delivered = datetime(2026, 10, 20, 2, tzinfo=UTC)
    result = evaluate_eligibility(
        status="DELIVERED",
        delivered_at=delivered,
        policy_version="demo-v1",
        has_payment=True,
        has_active_case=False,
        reason_code="QUALITY_ISSUE",
        now=delivered + delta,
    )
    assert result.eligible is eligible
    assert result.requires_human is (not eligible)
    assert result.reason_codes == ([] if eligible else ["OUTSIDE_RETURN_WINDOW"])


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"status": "PAID", "delivered_at": None}, "NOT_DELIVERED"),
        ({"has_payment": False}, "NOT_PAID"),
        ({"status": "REFUNDED"}, "ALREADY_REFUNDED"),
        ({"has_active_case": True}, "ACTIVE_CASE_EXISTS"),
        ({"policy_version": "unknown-v9"}, "UNSUPPORTED_POLICY"),
        ({"reason_code": "QUALITY_DISPUTE"}, "REQUIRES_HUMAN_REVIEW"),
    ],
)
def test_fixed_policy_rejects_unsafe_facts(change, reason):
    facts = dict(
        status="DELIVERED",
        delivered_at=datetime(2026, 10, 20, tzinfo=UTC),
        policy_version="demo-v1",
        has_payment=True,
        has_active_case=False,
        reason_code="QUALITY_ISSUE",
        now=datetime(2026, 10, 21, tzinfo=UTC),
    )
    result = evaluate_eligibility(**{**facts, **change})
    assert not result.eligible and reason in result.reason_codes


async def test_pg_eligibility_binds_snapshot_owner_and_fixed_logical_clock(
    env, buyer, buyer2, product
):
    client, _, app, _ = env
    order = await delivered_order(client, buyer, product)
    actor = ActorContext(UUID(order["user_id"]), "buyer", UUID(order["store_id"]))
    boundary = datetime.fromisoformat(order["delivered_at"]) + timedelta(days=7)
    async with app.state.sessions.begin() as session:
        exact = await check_eligibility(
            session, actor, UUID(order["id"]), "QUALITY_ISSUE", now=boundary
        )
        late = await check_eligibility(
            session,
            actor,
            UUID(order["id"]),
            "QUALITY_ISSUE",
            now=boundary + timedelta(microseconds=1),
        )
    assert exact.eligible and not late.eligible and late.requires_human
    path = f"/api/v1/orders/{order['id']}/after-sales-eligibility"
    assert (await client.get(path, headers=buyer)).json()["eligible"]
    assert (await client.get(path, headers=buyer2)).status_code == 404
    merchant = await merchant_headers(client)
    assert (await client.get(path, headers=merchant)).status_code == 403
    assert (
        await client.get(path, headers=buyer, params={"reason_code": "invented"})
    ).status_code == 422


async def test_request_replay_requires_confirmation_and_keeps_order_delivered(
    env, buyer, buyer2, product
):
    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    body = dict(
        request_id=str(uuid4()),
        order_id=order["id"],
        expected_version=4,
        reason_code="QUALITY_ISSUE",
        description="Synthetic fault",
    )
    key = str(uuid4())
    proposal = await return_proposal(client, buyer, order, key=key, body=body)
    for k in (key, str(uuid4())):
        r = await client.post(
            "/api/v1/after-sales/proposals", headers={**buyer, "Idempotency-Key": k}, json=body
        )
        assert r.status_code == 200 and r.json() == proposal
    changed = await client.post(
        "/api/v1/after-sales/proposals",
        headers={**buyer, "Idempotency-Key": key},
        json={**body, "description": "Changed"},
    )
    assert changed.status_code == 409
    missing = await submit_case(client, buyer, proposal, {"confirmation_id": str(uuid4())})
    assert missing.status_code == 404
    confirmation = await confirm(client, buyer, proposal)
    assert (await submit_case(client, buyer2, proposal, confirmation)).status_code == 404
    execute_key = str(uuid4())
    created = await submit_case(client, buyer, proposal, confirmation, execute_key)
    assert created.status_code == 201
    for k in (execute_key, str(uuid4())):
        replay = await submit_case(client, buyer, proposal, confirmation, k)
        assert replay.status_code == 200 and replay.json() == created.json()
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert (
        row(db, "SELECT status FROM orders WHERE id=:id", id=order["id"])["status"] == "DELIVERED"
    )
    caseid = created.json()["case_id"]
    assert (await client.get(f"/api/v1/after-sales/{caseid}", headers=buyer2)).status_code == 404
    assert not (
        await client.get(f"/api/v1/orders/{order['id']}/after-sales-eligibility", headers=buyer)
    ).json()["eligible"]


async def test_cancelled_and_rejected_cases_allow_new_confirmed_request(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await requested_case(client, buyer, order)
    p = await cancel_proposal(client, buyer, case)
    r = await execute_cancel(client, buyer, case, p)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    second = await requested_case(client, buyer, order)
    denied = await review_case(client, merchant, second, decision="reject")
    assert denied.status_code == 200 and denied.json()["status"] == "REJECTED"
    assert (
        await client.post(
            f"/api/v1/merchant/after-sales/{second['id']}/receive",
            headers=merchant,
            json={"expected_version": 2},
        )
    ).status_code == 409
    third = await requested_case(client, buyer, order)
    assert len({case["id"], second["id"], third["id"]}) == 3
    assert (
        row(
            db,
            "SELECT count(*) n FROM aftersales_cases WHERE status NOT IN ('CANCELLED','REJECTED')",
        )["n"]
        == 1
    )


async def test_role_changes_cannot_reuse_buyer_or_merchant_proposal(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    p = await return_proposal(client, buyer, order)
    assert (
        await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=merchant)
    ).status_code == 404
    with db.begin() as c:
        c.execute(
            text("UPDATE users SET role='merchant',store_id=:store WHERE id=:id"),
            {"store": order["store_id"], "id": order["user_id"]},
        )
    assert (
        await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=buyer)
    ).status_code == 404
    with db.begin() as c:
        c.execute(
            text("UPDATE users SET role='buyer',store_id=NULL WHERE id=:id"),
            {"id": order["user_id"]},
        )
    case = await received_case(client, buyer, order, merchant)
    refundp = await refund_proposal(client, merchant, case)
    assert (
        await client.get(f"/api/v1/proposals/{refundp['proposal_id']}", headers=buyer)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/proposals/{refundp['proposal_id']}/confirmations",
            headers=buyer,
            json={"decision": "approve"},
        )
    ).status_code == 404
    with db.begin() as c:
        c.execute(text("UPDATE users SET role='buyer',store_id=NULL WHERE login='merchant'"))
    assert (
        await client.get(f"/api/v1/proposals/{refundp['proposal_id']}", headers=merchant)
    ).status_code == 404
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0


async def test_refunded_order_cannot_reapply(env, buyer, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    p = await refund_proposal(client, merchant, case)
    assert (await execute_refund(client, merchant, case, p)).status_code == 201
    eligibility = (
        await client.get(f"/api/v1/orders/{order['id']}/after-sales-eligibility", headers=buyer)
    ).json()
    assert not eligibility["eligible"] and "ALREADY_REFUNDED" in eligibility["reason_codes"]
    assert row(db, "SELECT status FROM orders WHERE id=:id", id=order["id"])["status"] == "REFUNDED"


async def test_0004_preserves_0003_payment_and_history_and_refuses_lossy_downgrade(
    env, buyer, product
):
    from alembic import command
    from alembic.config import Config

    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    cfg = Config(str(ROOT / "backend/alembic.ini"))

    def snapshots():
        return row(
            db,
            "SELECT (SELECT jsonb_agg(to_jsonb(o)) FROM orders o) orders, "
            "(SELECT jsonb_agg(to_jsonb(p)) FROM payments p) payments, "
            "(SELECT jsonb_agg(to_jsonb(i) ORDER BY id) FROM idempotency_requests i) receipts",
        )

    before = snapshots()
    with db.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0003")
    assert row(db, "SELECT version_num FROM alembic_version")["version_num"] == "0003"
    with db.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "head")
        command.check(cfg)
    assert snapshots() == before
    case = await received_case(client, buyer, order, merchant)
    p = await refund_proposal(client, merchant, case)
    assert (await execute_refund(client, merchant, case, p)).status_code == 201
    with pytest.raises(DBAPIError), db.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0003")
    assert row(db, "SELECT version_num FROM alembic_version")["version_num"] == "0008"
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 1


def rewrite_owned_order(db, order_id, **updates):
    assert set(updates) <= {"policy_version", "delivered_at"}
    with db.begin() as conn:
        assert conn.scalar(text("SELECT current_database()")) == "agentmall_test"
        schema = conn.scalar(text("SELECT current_schema()"))
        assert schema.startswith("test_") and len(schema) == 37
        conn.execute(text("ALTER TABLE orders DISABLE TRIGGER immutable_snapshot"))
        columns = ",".join(f"{name}=:{name}" for name in updates)
        conn.execute(text(f"UPDATE orders SET {columns} WHERE id=:id"), {"id": order_id, **updates})
        conn.execute(text("ALTER TABLE orders ENABLE TRIGGER immutable_snapshot"))


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("unknown_policy", "UNSUPPORTED_POLICY"),
        ("late", "OUTSIDE_RETURN_WINDOW"),
        ("missing_delivery", "MISSING_DELIVERY_TIME"),
    ],
)
async def test_pg_policy_facts_block_proposals_without_side_effects(
    env, buyer, product, condition, reason
):
    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    if condition == "unknown_policy":
        rewrite_owned_order(db, order["id"], policy_version="unsupported-v2")
    elif condition == "late":
        rewrite_owned_order(db, order["id"], delivered_at=datetime.now(UTC) - timedelta(days=8))
    else:
        rewrite_owned_order(db, order["id"], delivered_at=None)
    result = await client.get(
        f"/api/v1/orders/{order['id']}/after-sales-eligibility", headers=buyer
    )
    assert result.status_code == 200 and reason in result.json()["reason_codes"]
    response = await client.post(
        "/api/v1/after-sales/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={
            "order_id": order["id"],
            "expected_version": 4,
            "request_id": str(uuid4()),
            "reason_code": "QUALITY_ISSUE",
            "description": "Synthetic",
        },
    )
    assert response.status_code == 409
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert (
        row(db, "SELECT count(*) n FROM action_proposals WHERE action_type='RETURN_REQUEST'")["n"]
        == 0
    )


async def test_real_pg_clock_rechecks_seven_days_after_order_lock(env, buyer, product):
    from test_expiry_race import ORDER_LOCK, controlled_race

    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    boundary = row(db, "SELECT clock_timestamp() now")["now"] + timedelta(seconds=1)
    rewrite_owned_order(db, order["id"], delivered_at=boundary - timedelta(days=7))
    proposal = await return_proposal(client, buyer, order)
    confirmation = await confirm(client, buyer, proposal)
    results, released = await controlled_race(
        env,
        ORDER_LOCK,
        {"id": order["id"]},
        [
            ("apply_after_seven_days", lambda: submit_case(client, buyer, proposal, confirmation)),
        ],
        release_after=boundary,
    )
    assert released >= boundary
    assert results[0].status_code == 409
    assert results[0].json()["code"] == "AFTERSALES_INELIGIBLE"
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert (
        row(
            db,
            "SELECT consumed_at FROM confirmations WHERE id=:id",
            id=confirmation["confirmation_id"],
        )["consumed_at"]
        is None
    )


async def test_database_rejects_ticket_without_verified_scope(env):
    from sqlalchemy.exc import IntegrityError

    _, db, _, settings = env
    with pytest.raises(IntegrityError) as error, db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO support_tickets(id,user_id,store_id,request_id,request_hash,"
                "blocked_action_types,reason,summary,status) "
                "SELECT :id,id,:store,:request,:hash,'[]'::jsonb,'EXPLANATION','Synthetic','OPEN' "
                "FROM users WHERE login='buyer1'"
            ),
            {"id": uuid4(), "store": settings.storefront_id, "request": uuid4(), "hash": "0" * 64},
        )

    assert error.value.orig.sqlstate == "23514"
    assert error.value.orig.diag.constraint_name == "ck_ticket_scope"
