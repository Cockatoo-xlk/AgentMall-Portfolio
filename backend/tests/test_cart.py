import asyncio
from uuid import uuid4

import pytest
from conftest import row
from httpx import ASGITransport, AsyncClient, ReadError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def cart(client, buyer):
    r = await client.get("/api/v1/cart", headers=buyer)
    assert r.status_code == 200, r.text
    return r.json()


async def put(client, buyer, product, quantity, version, **extra):
    return await client.put(
        f"/api/v1/cart/items/{product}",
        headers=buyer,
        json={"quantity": quantity, "expected_version": version, **extra},
    )


async def test_add_replace_delete_and_no_reservation(env, buyer, product):
    client, db, _, _ = env
    before = row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product)
    empty = await cart(client, buyer)
    added = await put(client, buyer, product, 2, empty["version"])
    assert added.status_code == 200
    assert added.json()["items"][0]["quantity"] == 2
    changed = await put(client, buyer, product, 3, added.json()["version"])
    assert changed.json()["items"][0]["quantity"] == 3
    assert changed.json()["version"] == empty["version"] + 2
    r = await client.request(
        "DELETE",
        f"/api/v1/cart/items/{product}",
        headers=buyer,
        json={"expected_version": changed.json()["version"]},
    )
    assert r.status_code == 200 and r.json()["items"] == []
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == before


class DropSuccessfulPut(ASGITransport):
    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)
        if request.method == "PUT" and response.status_code == 200:
            await response.aclose()
            raise ReadError("Injected response loss after successful commit", request=request)
        return response


async def test_lost_response_old_version_retry_then_get_preserves_newer_write(env, buyer, product):
    client, _, app, _ = env
    initial = await cart(client, buyer)
    # The real handler and PG commit finish before the transport drops the response.
    async with AsyncClient(transport=DropSuccessfulPut(app=app), base_url="http://test") as lossy:
        with pytest.raises(ReadError, match="Injected response loss"):
            await put(lossy, buyer, product, 2, initial["version"])
    retry = await put(client, buyer, product, 2, initial["version"])
    assert retry.status_code == 409 and retry.json()["retryable"] is False
    recovered = await cart(client, buyer)
    assert recovered["items"][0]["quantity"] == 2
    assert recovered["version"] == initial["version"] + 1
    newer = await put(client, buyer, product, 5, recovered["version"])
    assert newer.status_code == 200
    late_retry = await put(client, buyer, product, 2, initial["version"])
    assert late_retry.status_code == 409
    final = await cart(client, buyer)
    assert final["items"][0]["quantity"] == 5
    assert final["version"] == newer.json()["version"]


async def wait_for_two_database_lock_waiters(db, schema):
    deadline = asyncio.get_running_loop().time() + 5
    while True:
        with db.connect() as observer:
            waiters = observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND application_name=:name AND wait_event_type='Lock'"
                ),
                {"name": f"agentmall:{schema}"},
            )
        if waiters == 2:
            return
        assert asyncio.get_running_loop().time() < deadline, "Both requests must wait on PG locks"
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("first_request", [False, True], ids=["existing-cart", "first-cart"])
async def test_two_simultaneous_writers_only_one_wins(env, buyer, product, first_request):
    client, db, _, settings = env
    user = row(db, "SELECT id FROM users WHERE login='buyer1'")["id"]
    version = 0 if first_request else (await cart(client, buyer))["version"]
    with db.begin() as blocker:
        if first_request:
            # An uncommitted first cart makes both requests block on the unique key.
            # Roll it back below so a request must really create the first cart.
            blocker.execute(
                text("INSERT INTO carts(id,user_id,store_id) VALUES (:id,:user,:store)"),
                {"id": uuid4(), "user": user, "store": settings.storefront_id},
            )
        else:
            blocker.execute(
                text("SELECT id FROM carts WHERE user_id=:user FOR UPDATE"), {"user": user}
            )
        tasks = [asyncio.create_task(put(client, buyer, product, qty, version)) for qty in (4, 7)]
        try:
            await wait_for_two_database_lock_waiters(db, settings.db_schema)
        finally:
            blocker.rollback()
            results = await asyncio.gather(*tasks)
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json() for r in results if r.status_code == 200)
    assert winner["version"] == version + 1
    assert await cart(client, buyer) == winner
    assert row(db, "SELECT count(*) AS n FROM carts WHERE user_id=:user", user=user)["n"] == 1


async def test_two_buyers_cannot_select_each_others_cart(client, buyer, buyer2, product):
    a = await cart(client, buyer)
    b = await cart(client, buyer2)
    assert a["id"] != b["id"]
    assert (await put(client, buyer, product, 2, a["version"])).status_code == 200
    for field, value in [
        ("user_id", a["user_id"]),
        ("cart_id", a["id"]),
        ("store_id", a["store_id"]),
    ]:
        assert (
            await put(client, buyer2, product, 8, b["version"], **{field: value})
        ).status_code == 422
        assert (
            await client.get("/api/v1/cart", headers=buyer2, params={field: value})
        ).status_code == 422
    assert (await cart(client, buyer2))["items"] == []
    assert (await cart(client, buyer))["items"][0]["quantity"] == 2


async def test_cross_store_and_unlisted_product_writes_rejected(env, buyer, product):
    client, db, _, _ = env
    c = await cart(client, buyer)
    with db.begin() as conn:
        conn.execute(
            text("UPDATE products SET store_id=:store WHERE id=:id"),
            {"store": uuid4(), "id": product},
        )
    assert (await put(client, buyer, product, 1, c["version"])).status_code == 404
    r = await client.request(
        "DELETE",
        f"/api/v1/cart/items/{product}",
        headers=buyer,
        json={"expected_version": c["version"]},
    )
    assert r.status_code == 404
    assert await cart(client, buyer) == c
    with db.begin() as conn:
        conn.execute(
            text("UPDATE products SET store_id=:store,active=false WHERE id=:id"),
            {"store": c["store_id"], "id": product},
        )
    assert (await put(client, buyer, product, 1, c["version"])).status_code == 404


async def test_cart_read_scoped_to_store_and_database_fk(env, buyer, product):
    client, db, app, settings = env
    c = await cart(client, buyer)
    # A pre-existing cart for the same buyer in another storefront is not visible.
    other_store = uuid4()
    with db.begin() as conn:
        conn.execute(
            text("UPDATE carts SET store_id=:store WHERE id=:id"),
            {"store": other_store, "id": c["id"]},
        )
    fresh = await cart(client, buyer)
    assert fresh["id"] != c["id"] and fresh["store_id"] == str(settings.storefront_id)
    with pytest.raises(IntegrityError), db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO cart_items(id,cart_id,product_id,store_id,quantity) "
                "VALUES (:id,:cart,:product,:store,1)"
            ),
            {"id": uuid4(), "cart": c["id"], "product": product, "store": other_store},
        )


@pytest.mark.parametrize("quantity", [-1, 11, 1.5, "2", True, None])
async def test_invalid_quantity_has_no_write(client, buyer, product, quantity):
    before = await cart(client, buyer)
    assert (await put(client, buyer, product, quantity, before["version"])).status_code == 422
    assert await cart(client, buyer) == before


@pytest.mark.parametrize("version", [-1, 1.5, "0", True, None])
async def test_invalid_version_rejected(client, buyer, product, version):
    assert (await put(client, buyer, product, 1, version)).status_code == 422


async def test_zero_removes_and_stale_delete_conflicts(client, buyer, product):
    v = (await cart(client, buyer))["version"]
    added = await put(client, buyer, product, 1, v)
    stale = await client.request(
        "DELETE", f"/api/v1/cart/items/{product}", headers=buyer, json={"expected_version": v}
    )
    assert stale.status_code == 409
    removed = await put(client, buyer, product, 0, added.json()["version"])
    assert removed.status_code == 200 and removed.json()["items"] == []


async def test_limit_twenty_lines_and_out_of_stock_not_reserved(env, buyer):
    client, db, _, settings = env
    ids = [uuid4() for _ in range(21)]
    with db.begin() as conn:
        for pid in ids:
            conn.execute(
                text(
                    "INSERT INTO products(id,store_id,name,category,price_cents,on_hand) "
                    "VALUES (:id,:store,'容量测试','keyboard',100,0)"
                ),
                {"id": pid, "store": settings.storefront_id},
            )
    v = (await cart(client, buyer))["version"]
    for pid in ids[:20]:
        r = await put(client, buyer, str(pid), 1, v)
        assert r.status_code == 200
        v = r.json()["version"]
    assert (await put(client, buyer, str(ids[20]), 1, v)).status_code == 409
    assert len((await cart(client, buyer))["items"]) == 20
