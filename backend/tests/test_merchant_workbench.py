"""Merchant reads use the authenticated tenant and do not widen buyer reads."""

from uuid import uuid4

import pytest
from aftersales_helpers import delivered_order, merchant_headers, requested_case, review_case
from conftest import PASSWORD
from lifecycle_helpers import create_order
from sqlalchemy import text

ORDER_PATH = "/api/v1/merchant/orders"
CASE_PATH = "/api/v1/merchant/after-sales"


@pytest.mark.parametrize("path", [ORDER_PATH, CASE_PATH])
async def test_merchant_lists_require_merchant(client, buyer, path):
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=buyer)).status_code == 403


async def test_store_scope_pagination_and_status_filters(env, buyer, buyer2, product):
    client, db, _, _ = env
    merchant = await merchant_headers(client)
    order1 = await delivered_order(client, buyer, product, merchant)
    order2 = await delivered_order(client, buyer2, product, merchant)
    pending = await create_order(client, buyer, product)
    case1 = await requested_case(client, buyer, order1)
    case2 = await requested_case(client, buyer2, order2)
    reviewed = await review_case(client, merchant, case2)
    assert reviewed.status_code == 200
    case2 = reviewed.json()

    for path, entries, status, matching in [
        (ORDER_PATH, [order1, order2, pending], "DELIVERED", [order1, order2]),
        (CASE_PATH, [case1, case2], "APPROVED", [case2]),
    ]:
        remaining = sorted(entries, key=lambda row: row["id"])
        params = {"limit": 1}
        for index, expected in enumerate(remaining):
            response = await client.get(path, headers=merchant, params=params)
            assert response.status_code == 200
            cursor = expected["id"] if index < len(remaining) - 1 else None
            assert response.json() == {"items": [expected], "next_cursor": cursor}
            params["cursor"] = expected["id"]
        result = await client.get(path, headers=merchant, params={"status": status})
        assert result.status_code == 200
        assert result.json()["items"] == sorted(matching, key=lambda row: row["id"])
        for query in (
            {"limit": 0},
            {"limit": 101},
            {"status": "INVALID"},
            {"store_id": str(uuid4())},
        ):
            assert (await client.get(path, headers=merchant, params=query)).status_code == 422

    with db.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id, login, password_hash, role, store_id) "
                "SELECT :id, 'foreign_merchant', password_hash, 'merchant', :store "
                "FROM users WHERE login='merchant'"
            ),
            {"id": uuid4(), "store": uuid4()},
        )
    login = await client.post(
        "/api/v1/auth/login", json={"login": "foreign_merchant", "password": PASSWORD}
    )
    assert login.status_code == 200
    foreign = {"Authorization": "Bearer " + login.json()["access_token"]}
    for path, item in [(ORDER_PATH, order1), (CASE_PATH, case1)]:
        detail = f"{path}/{item['id']}"
        assert (await client.get(detail, headers=merchant)).json() == item
        assert (await client.get(detail, headers=buyer)).status_code == 403
        assert (await client.get(detail, headers=foreign)).status_code == 404
        result = await client.get(path, headers=foreign)
        assert result.status_code == 200
        assert result.json() == {"items": [], "next_cursor": None}
    assert (await client.get("/api/v1/orders", headers=merchant)).status_code == 403
    assert (
        await client.get("/api/v1/after-sales/" + case1["id"], headers=merchant)
    ).status_code == 403
