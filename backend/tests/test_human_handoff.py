"""Real PostgreSQL support handoff: authorization, durable replay and scoped pauses."""

import asyncio
from uuid import uuid4

import pytest
from aftersales_helpers import (
    cancel_proposal,
    delivered_order,
    execute_cancel,
    execute_refund,
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
from lifecycle_helpers import create_order
from sqlalchemy import text
from test_expiry_race import ORDER_LOCK, controlled_race


async def merchant_auth(client):
    response = await client.post(
        "/api/v1/auth/login", json={"login": "merchant", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def ticket_body(order=None, **changes):
    scope = {"order_id": order["id"]} if order else {"conversation_scope": "after_sales_question"}
    return {
        "request_id": str(uuid4()),
        **scope,
        "reason": "POLICY_DISPUTE",
        "summary": "请解释此订单适用的售后政策。",
        **changes,
    }


async def create_ticket(client, actor, body, key=None):
    return await client.post(
        "/api/v1/support-tickets",
        headers={**actor, "Idempotency-Key": key or str(uuid4())},
        json=body,
    )


async def resolve_ticket(client, actor, ticket, **changes):
    return await client.post(
        f"/api/v1/merchant/tickets/{ticket['id']}/resolve",
        headers=actor,
        json={
            "expected_version": ticket["version"],
            "resolution": "RETRY_ALLOWED",
            "summary": "已解释，请重新按现行政策提交申请。",
            **changes,
        },
    )


async def claim_ticket(client, actor, ticket, **changes):
    return await client.post(
        f"/api/v1/merchant/tickets/{ticket['id']}/claim",
        headers=actor,
        json={"expected_version": ticket["version"], **changes},
    )


async def test_ticket_key_and_request_replay_are_durable_and_conflicts_are_atomic(
    env, buyer, product
):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    body, key = ticket_body(order), str(uuid4())
    response = await create_ticket(client, buyer, body, key)
    assert response.status_code == 201, response.text
    ticket = response.json()
    assert ticket["status"] == "OPEN" and ticket["version"] == 1
    assert ticket["order_id"] == order["id"] and ticket["case_id"] is None
    assert set(ticket["blocked_action_types"]) == {
        "RETURN_REQUEST",
        "RETURN_CANCEL",
        "MOCK_REFUND",
        "REVIEW_CASE",
        "RECEIVE_CASE",
    }
    for retry_key in (key, str(uuid4())):
        retry = await create_ticket(client, buyer, body, retry_key)
        assert retry.status_code == 200 and retry.json() == ticket
    for conflicting_key in (key, str(uuid4())):
        conflict = await create_ticket(
            client, buyer, {**body, "summary": "Changed dispute"}, conflicting_key
        )
        assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert row(db, "SELECT count(*) n FROM support_tickets")["n"] == 1
    assert (
        row(
            db,
            "SELECT count(*) n FROM idempotency_requests WHERE operation='create_support_ticket'",
        )["n"]
        == 2
    )
    event = row(db, "SELECT * FROM business_events WHERE aggregate_type='support_ticket'")
    assert str(event["aggregate_id"]) == ticket["id"] and event["event_type"] == "TICKET_OPENED"
    assert event["action_id"] is None and "summary" not in event["payload_summary"]
    retrieved = await client.get(f"/api/v1/support-tickets/{ticket['id']}", headers=buyer)
    assert retrieved.status_code == 200 and retrieved.json() == ticket


async def test_ticket_requires_owner_and_server_computes_scope(env, buyer, buyer2, product):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    other = await create_ticket(client, buyer2, ticket_body(order))
    assert other.status_code == 404, other.text
    merchant = await merchant_auth(client)
    assert (await create_ticket(client, merchant, ticket_body(order))).status_code == 403
    assert (await create_ticket(client, {}, ticket_body(order))).status_code == 401
    for forged in (
        {"blocked_action_types": []},
        {"user_id": str(uuid4())},
        {"store_id": str(uuid4())},
        {"status": "RESOLVED"},
        {"resolution": "RETRY_ALLOWED"},
        {"case_id": str(uuid4())},
        {"conversation_scope": "after_sales_question"},
    ):
        response = await create_ticket(client, buyer, ticket_body(order, **forged))
        assert response.status_code == 422, response.text
    assert row(db, "SELECT count(*) n FROM support_tickets")["n"] == 0
    assert (
        row(
            db,
            "SELECT count(*) n FROM idempotency_requests WHERE operation='create_support_ticket'",
        )["n"]
        == 0
    )


async def test_conversation_scope_pauses_no_order_and_resolve_has_one_event(env, buyer, buyer2):
    client, db, _, _ = env
    response = await create_ticket(client, buyer, ticket_body())
    assert response.status_code == 201, response.text
    ticket = response.json()
    assert ticket["blocked_action_types"] == []
    assert ticket["order_id"] is None and ticket["case_id"] is None
    assert (
        await client.get(f"/api/v1/support-tickets/{ticket['id']}", headers=buyer2)
    ).status_code == 404
    assert (await resolve_ticket(client, buyer, ticket)).status_code == 403
    merchant = await merchant_auth(client)
    assert (
        await client.get(f"/api/v1/support-tickets/{ticket['id']}", headers=merchant)
    ).status_code == 200
    resolved = await resolve_ticket(client, merchant, ticket)
    assert resolved.status_code == 200, resolved.text
    result = resolved.json()
    assert result["status"] == "RESOLVED" and result["version"] == 2
    assert result["resolution"] == "RETRY_ALLOWED" and result["resolved_at"]
    assert result["assigned_to"] and result["resolution_summary"]
    stale = await resolve_ticket(client, merchant, ticket)
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    repeated = await resolve_ticket(client, merchant, result)
    assert repeated.status_code == 409 and repeated.json()["code"] == "INVALID_TICKET_STATE"
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE aggregate_type='support_ticket'")["n"]
        == 2
    )


@pytest.mark.parametrize("scope", ["order", "conversation"])
@pytest.mark.parametrize("same_key", [False, True])
async def test_same_request_concurrently_creates_one_ticket(env, buyer, product, scope, same_key):
    client, db, _, _ = env
    order = await create_order(client, buyer, product) if scope == "order" else None
    body = ticket_body(order)
    key = str(uuid4()) if same_key else None
    responses = await asyncio.gather(
        create_ticket(client, buyer, body, key), create_ticket(client, buyer, body, key)
    )
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    assert row(db, "SELECT count(*) n FROM support_tickets")["n"] == 1
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE event_type='TICKET_OPENED'")["n"] == 1
    )


@pytest.mark.parametrize("status", ["OPEN", "IN_PROGRESS"])
async def test_active_ticket_blocks_disputed_action_without_blocking_catalog(
    env, buyer, product, status
):
    from agentmall.infra.errors import DomainError
    from agentmall.support.service import check_handoff

    client, db, app, _ = env
    order = await create_order(client, buyer, product)
    response = await create_ticket(client, buyer, ticket_body(order))
    assert response.status_code == 201, response.text
    ticket = response.json()
    if status == "IN_PROGRESS":
        merchant = await merchant_auth(client)
        claimed = await claim_ticket(client, merchant, ticket)
        assert claimed.status_code == 200, claimed.text
        ticket = claimed.json()
        assert ticket["status"] == "IN_PROGRESS" and ticket["version"] == 2
    for action in ("RETURN_REQUEST", "RETURN_CANCEL", "MOCK_REFUND", "REVIEW_CASE", "RECEIVE_CASE"):
        async with app.state.sessions.begin() as session:
            with pytest.raises(DomainError) as error:
                await check_handoff(session, order["id"], action)
            assert error.value.code == "HUMAN_HANDOFF_REQUIRED"
    async with app.state.sessions.begin() as session:
        await check_handoff(session, order["id"], "CHECKOUT")
        await check_handoff(session, uuid4(), "MOCK_REFUND")
    assert (await client.get("/api/v1/products", headers=buyer)).status_code == 200
    assert (await client.get(f"/api/v1/orders/{order['id']}", headers=buyer)).status_code == 200
    assert row(db, "SELECT status FROM orders WHERE id=:id", id=order["id"])["status"] == (
        "PENDING_PAYMENT"
    )


async def test_case_scope_derives_order_and_merchant_scope_uses_database(
    env, buyer, buyer2, product
):
    client, db, _, _ = env
    merchant = await merchant_auth(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await requested_case(client, buyer, order)
    body = {
        "request_id": str(uuid4()),
        "case_id": case["id"],
        "reason": "QUALITY_DISPUTE",
        "summary": "请人工复核此售后单。",
    }
    forbidden = await create_ticket(client, buyer2, body)
    assert forbidden.status_code == 404, forbidden.text
    response = await create_ticket(client, buyer, body)
    assert response.status_code == 201, response.text
    ticket = response.json()
    assert (ticket["case_id"], ticket["order_id"]) == (case["id"], order["id"])
    order_scope = await create_ticket(client, buyer, ticket_body(order))
    assert order_scope.status_code == 201 and order_scope.json()["case_id"] == case["id"]
    with db.begin() as connection:
        connection.execute(
            text("UPDATE users SET store_id=:store WHERE login='merchant'"), {"store": uuid4()}
        )
    assert (
        await client.get(f"/api/v1/support-tickets/{ticket['id']}", headers=merchant)
    ).status_code == 404
    assert (await resolve_ticket(client, merchant, ticket)).status_code == 404
    assert (
        row(db, "SELECT status FROM support_tickets WHERE id=:id", id=ticket["id"])["status"]
        == "OPEN"
    )


async def test_ticket_pauses_new_and_confirmed_return_without_consuming_confirmation(
    env, buyer, product
):
    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    proposal = await return_proposal(client, buyer, order)
    confirmation = await confirm(client, buyer, proposal)
    ticket_response = await create_ticket(client, buyer, ticket_body(order))
    assert ticket_response.status_code == 201, ticket_response.text
    new_proposal = await client.post(
        "/api/v1/after-sales/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={
            "request_id": str(uuid4()),
            "order_id": order["id"],
            "expected_version": order["version"],
            "reason_code": "QUALITY_ISSUE",
            "description": "Quality issue.",
        },
    )
    blocked = await submit_case(client, buyer, proposal, confirmation)
    for response in (new_proposal, blocked):
        assert response.status_code == 409 and response.json()["code"] == "HUMAN_HANDOFF_REQUIRED"
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert (
        row(
            db,
            "SELECT consumed_at FROM confirmations WHERE id=:id",
            id=confirmation["confirmation_id"],
        )["consumed_at"]
        is None
    )
    merchant = await merchant_auth(client)
    resolved = await resolve_ticket(client, merchant, ticket_response.json())
    assert resolved.status_code == 200, resolved.text
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    submitted = await submit_case(client, buyer, proposal, confirmation)
    assert submitted.status_code == 201, submitted.text


@pytest.mark.parametrize("first", ["ticket", "return"])
async def test_ticket_open_and_return_share_real_order_lock(env, buyer, product, first):
    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    proposal = await return_proposal(client, buyer, order)
    confirmation = await confirm(client, buyer, proposal)
    calls = {
        "ticket": lambda: create_ticket(client, buyer, ticket_body(order)),
        "return": lambda: submit_case(client, buyer, proposal, confirmation),
    }
    sequence = (first, "return" if first == "ticket" else "ticket")
    results, _ = await controlled_race(
        env, ORDER_LOCK, {"id": order["id"]}, [(name, calls[name]) for name in sequence]
    )
    responses = dict(zip(sequence, results, strict=True))
    assert responses["ticket"].status_code == 201, responses["ticket"].text
    if first == "ticket":
        assert responses["return"].status_code == 409
        assert responses["return"].json()["code"] == "HUMAN_HANDOFF_REQUIRED"
        assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    else:
        assert responses["return"].status_code == 201, responses["return"].text
        assert responses["ticket"].json()["case_id"] == responses["return"].json()["case_id"]
        assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(db, "SELECT count(*) n FROM support_tickets")["n"] == 1
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0


async def test_ticket_event_failure_rolls_back_ticket_and_idempotency_receipt(env, buyer):
    client, db, _, _ = env
    body, key = ticket_body(), str(uuid4())
    with db.begin() as connection:
        connection.execute(
            text("""
                CREATE FUNCTION fail_ticket_event() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.event_type = 'TICKET_OPENED' THEN
                        RAISE EXCEPTION 'test ticket event failure';
                    END IF;
                    RETURN NEW;
                END $$;
                CREATE TRIGGER fail_ticket_event BEFORE INSERT ON business_events
                FOR EACH ROW EXECUTE FUNCTION fail_ticket_event();
            """)
        )
    response = await create_ticket(client, buyer, body, key)
    assert response.status_code == 503 and response.json()["code"] == "DATABASE_UNAVAILABLE"
    for table in ("support_tickets", "idempotency_requests", "business_events"):
        assert row(db, f"SELECT count(*) n FROM {table}")["n"] == 0
    with db.begin() as connection:
        connection.execute(text("DROP TRIGGER fail_ticket_event ON business_events"))
    retry = await create_ticket(client, buyer, body, key)
    assert retry.status_code == 201, retry.text
    assert row(db, "SELECT count(*) n FROM support_tickets")["n"] == 1


@pytest.mark.parametrize("case_status", ["REQUESTED", "APPROVED", "RECEIVED"])
async def test_case_ticket_pauses_each_disputed_write_atomically(env, buyer, product, case_status):
    client, db, _, _ = env
    merchant = await merchant_auth(client)
    order = await delivered_order(client, buyer, product, merchant)
    if case_status == "RECEIVED":
        case = await received_case(client, buyer, order, merchant)
        proposal = await refund_proposal(client, merchant, case)
        confirmation = await confirm(client, merchant, proposal)
    else:
        case = await requested_case(client, buyer, order)
        if case_status == "APPROVED":
            reviewed = await review_case(client, merchant, case)
            assert reviewed.status_code == 200, reviewed.text
            case = reviewed.json()
        else:
            proposal = await cancel_proposal(client, buyer, case)
            confirmation = await confirm(client, buyer, proposal)
    response = await create_ticket(client, buyer, ticket_body(order))
    assert response.status_code == 201, response.text
    before = row(db, "SELECT count(*) n FROM business_events")["n"]
    responses = []
    if case_status == "REQUESTED":
        responses.append(await review_case(client, merchant, case))
        responses.append(await execute_cancel(client, buyer, case, proposal, confirmation))
        responses.append(
            await client.post(
                f"/api/v1/after-sales/{case['id']}/cancel-proposals",
                headers={**buyer, "Idempotency-Key": str(uuid4())},
                json={"request_id": str(uuid4()), "expected_version": case["version"]},
            )
        )
    elif case_status == "APPROVED":
        responses.append(await receive_case(client, merchant, case))
    else:
        responses.append(await execute_refund(client, merchant, case, proposal, confirmation))
        responses.append(
            await client.post(
                f"/api/v1/merchant/after-sales/{case['id']}/refund-proposals",
                headers={**merchant, "Idempotency-Key": str(uuid4())},
                json={"request_id": str(uuid4()), "expected_version": case["version"]},
            )
        )
    for blocked in responses:
        assert blocked.status_code == 409 and blocked.json()["code"] == "HUMAN_HANDOFF_REQUIRED"
    assert row(db, "SELECT status,version FROM aftersales_cases WHERE id=:id", id=case["id"]) == {
        "status": case_status,
        "version": case["version"],
    }
    assert row(db, "SELECT count(*) n FROM business_events")["n"] == before
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert (
        row(db, "SELECT status FROM orders WHERE id=:id", id=order["id"])["status"] == "DELIVERED"
    )


async def test_resolution_cannot_override_ineligible_order(env, buyer, product):
    client, db, _, _ = env
    order = await create_order(client, buyer, product)
    response = await create_ticket(client, buyer, ticket_body(order, reason="NOT_ELIGIBLE"))
    assert response.status_code == 201, response.text
    merchant = await merchant_auth(client)
    resolved = await resolve_ticket(client, merchant, response.json())
    assert resolved.status_code == 200, resolved.text
    eligibility = await client.get(
        f"/api/v1/orders/{order['id']}/after-sales-eligibility",
        headers=buyer,
        params={"reason_code": "QUALITY_ISSUE"},
    )
    assert eligibility.status_code == 200 and eligibility.json()["eligible"] is False
    assert "NOT_PAID" in eligibility.json()["reason_codes"]
    attempt = await client.post(
        "/api/v1/after-sales/proposals",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={
            "request_id": str(uuid4()),
            "order_id": order["id"],
            "expected_version": order["version"],
            "reason_code": "QUALITY_ISSUE",
            "description": "Claim after manual explanation.",
        },
    )
    assert attempt.status_code == 409
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
    assert row(db, "SELECT status FROM orders WHERE id=:id", id=order["id"])["status"] == (
        "PENDING_PAYMENT"
    )


@pytest.mark.parametrize("invalid", ["unconfirmed", "expired"])
async def test_resolution_does_not_replace_expiry_or_confirmation_checks(
    env, buyer, product, invalid
):
    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    proposal = await return_proposal(client, buyer, order)
    confirmation = {"confirmation_id": str(uuid4())}
    if invalid == "expired":
        original_confirmation = await confirm(client, buyer, proposal)
        proposal = timed_proposal(db, proposal, -60)
        confirmation = {"confirmation_id": str(uuid4())}
        with db.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO confirmations"
                    "(id,proposal_id,actor_id,store_id,decision,decided_at) "
                    "SELECT :id,:proposal_id,actor_id,store_id,decision,decided_at "
                    "FROM confirmations "
                    "WHERE id=:original"
                ),
                {
                    "id": confirmation["confirmation_id"],
                    "proposal_id": proposal["proposal_id"],
                    "original": original_confirmation["confirmation_id"],
                },
            )
    ticket_response = await create_ticket(client, buyer, ticket_body(order))
    assert ticket_response.status_code == 201, ticket_response.text
    merchant = await merchant_auth(client)
    resolved = await resolve_ticket(client, merchant, ticket_response.json())
    assert resolved.status_code == 200, resolved.text
    response = await submit_case(client, buyer, proposal, confirmation)
    assert response.status_code == (409 if invalid == "expired" else 404), response.text
    if invalid == "expired":
        assert response.json()["code"] == "STALE_PROPOSAL"
        assert (
            row(
                db,
                "SELECT consumed_at FROM confirmations WHERE id=:id",
                id=confirmation["confirmation_id"],
            )["consumed_at"]
            is None
        )
    assert row(db, "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0


async def test_merchant_claims_ticket_once_and_can_resolve_in_progress(env, buyer):
    client, db, _, _ = env
    response = await create_ticket(client, buyer, ticket_body())
    assert response.status_code == 201, response.text
    ticket = response.json()
    assert (await claim_ticket(client, buyer, ticket)).status_code == 403
    merchant = await merchant_auth(client)
    claimed = await claim_ticket(client, merchant, ticket)
    assert claimed.status_code == 200, claimed.text
    in_progress = claimed.json()
    assert in_progress["status"] == "IN_PROGRESS" and in_progress["version"] == 2
    assert in_progress["assigned_to"] and in_progress["resolution"] is None
    stale = await claim_ticket(client, merchant, ticket)
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_VERSION"
    duplicate = await claim_ticket(client, merchant, in_progress)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "INVALID_TICKET_STATE"
    resolved = await resolve_ticket(client, merchant, in_progress, resolution="EXPLAINED")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "RESOLVED" and resolved.json()["version"] == 3
    assert resolved.json()["assigned_to"] == in_progress["assigned_to"]
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE event_type='TICKET_CLAIMED'")["n"]
        == 1
    )
    assert row(db, "SELECT count(*) n FROM refunds")["n"] == 0
