"""T06 fixtures traverse the public T02/T05 lifecycle before after-sales actions."""

from uuid import uuid4

from checkout_helpers import confirm
from conftest import PASSWORD
from lifecycle_helpers import create_order, execute_action, prepare_action


async def merchant_headers(client):
    response = await client.post(
        "/api/v1/auth/login", json={"login": "merchant", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


async def delivered_order(client, buyer, product, merchant=None):
    merchant = merchant if merchant is not None else await merchant_headers(client)
    order = await create_order(client, buyer, product)
    proposal = await prepare_action(client, buyer, order, "payment")
    confirmation = await confirm(client, buyer, proposal)
    paid = await execute_action(client, buyer, order, proposal, confirmation, "payment")
    assert paid.status_code == 201, paid.text
    response = await client.get(f"/api/v1/orders/{order['id']}", headers=buyer)
    assert response.status_code == 200, response.text
    order = response.json()
    for event in ("ship", "deliver"):
        response = await client.post(
            f"/api/v1/merchant/orders/{order['id']}/{event}",
            headers=merchant,
            json={"expected_version": order["version"]},
        )
        assert response.status_code == 200, response.text
        order = response.json()
    assert order["status"] == "DELIVERED" and order["delivered_at"]
    return order


async def return_proposal(client, buyer, order, key=None, body=None):
    response = await client.post(
        "/api/v1/after-sales/proposals",
        headers={**buyer, "Idempotency-Key": key or str(uuid4())},
        json=body
        if body is not None
        else {
            "request_id": str(uuid4()),
            "order_id": order["id"],
            "expected_version": order["version"],
            "reason_code": "QUALITY_ISSUE",
            "description": "Item failed its first normal use.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def submit_case(client, buyer, proposal, confirmation=None, key=None):
    if confirmation is None:
        confirmation = await confirm(client, buyer, proposal)
    return await client.post(
        "/api/v1/after-sales",
        headers={**buyer, "Idempotency-Key": key or str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
    )


async def requested_case(client, buyer, order, key=None, body=None):
    proposal = await return_proposal(client, buyer, order, body=body)
    response = await submit_case(client, buyer, proposal, key=key)
    assert response.status_code == 201, response.text
    response = await client.get(f"/api/v1/after-sales/{response.json()['case_id']}", headers=buyer)
    assert response.status_code == 200, response.text
    return response.json()


async def review_case(
    client, merchant, case, decision="approve", reason="Inspection approved.", expected_version=None
):
    return await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/review",
        headers=merchant,
        json={
            "decision": decision,
            "reason": reason,
            "expected_version": case["version"] if expected_version is None else expected_version,
        },
    )


async def receive_case(client, merchant, case, expected_version=None):
    return await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/receive",
        headers=merchant,
        json={
            "expected_version": case["version"] if expected_version is None else expected_version
        },
    )


async def refund_proposal(client, merchant, case, key=None, body=None):
    response = await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/refund-proposals",
        headers={**merchant, "Idempotency-Key": key or str(uuid4())},
        json=body
        if body is not None
        else {"request_id": str(uuid4()), "expected_version": case["version"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def execute_refund(client, merchant, case, proposal, confirmation=None, key=None):
    if confirmation is None:
        confirmation = await confirm(client, merchant, proposal)
    return await client.post(
        f"/api/v1/merchant/after-sales/{case['id']}/refund",
        headers={**merchant, "Idempotency-Key": key or str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
    )


async def cancel_proposal(client, buyer, case, key=None, body=None):
    response = await client.post(
        f"/api/v1/after-sales/{case['id']}/cancel-proposals",
        headers={**buyer, "Idempotency-Key": key or str(uuid4())},
        json=body
        if body is not None
        else {"request_id": str(uuid4()), "expected_version": case["version"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def execute_cancel(client, buyer, case, proposal, confirmation=None, key=None):
    if confirmation is None:
        confirmation = await confirm(client, buyer, proposal)
    return await client.post(
        f"/api/v1/after-sales/{case['id']}/cancel",
        headers={**buyer, "Idempotency-Key": key or str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
    )


async def received_case(client, buyer, order, merchant=None):
    merchant = merchant if merchant is not None else await merchant_headers(client)
    case = await requested_case(client, buyer, order)
    response = await review_case(client, merchant, case)
    assert response.status_code == 200, response.text
    response = await receive_case(client, merchant, response.json())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RECEIVED"
    return response.json()
