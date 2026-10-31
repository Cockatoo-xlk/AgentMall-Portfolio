from uuid import uuid4

from sqlalchemy import text


async def test_budget_keyword_category_and_public_fields(client):
    r = await client.get(
        "/api/v1/products",
        params={"max_price_cents": 30000, "category": "keyboard", "query": "静音"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    for item in items:
        assert item["price_cents"] <= 30000
        assert isinstance(item["price_cents"], int)
        assert item["category"] == "keyboard"
        assert not ({"store_id", "on_hand", "reserved", "active", "created_at"} & item.keys())
        detail = await client.get("/api/v1/products/" + item["id"])
        assert detail.json() == item
    zero = await client.get("/api/v1/products", params={"max_price_cents": 0})
    assert zero.json()["items"] == []


async def test_inactive_and_other_store_are_not_public(env, product):
    client, db, _, _ = env
    with db.begin() as conn:
        conn.execute(text("UPDATE products SET active=false WHERE id=:id"), {"id": product})
        other = conn.scalar(text("SELECT id FROM products WHERE active ORDER BY id LIMIT 1"))
        conn.execute(
            text("UPDATE products SET store_id=:store WHERE id=:id"),
            {"id": other, "store": uuid4()},
        )
    for pid in [product, str(other), str(uuid4())]:
        assert (await client.get(f"/api/v1/products/{pid}")).status_code == 404
    ids = {item["id"] for item in (await client.get("/api/v1/products")).json()["items"]}
    assert product not in ids and str(other) not in ids


async def test_cursor_pages_and_limits(client):
    ids = []
    params = {"limit": 3}
    while True:
        r = await client.get("/api/v1/products", params=params)
        assert r.status_code == 200
        page = r.json()
        assert len(page["items"]) <= 3
        ids.extend(p["id"] for p in page["items"])
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]
    assert len(ids) == len(set(ids)) >= 10
    for params in [
        {"limit": 101},
        {"max_price_cents": -1},
        {"cursor": "invalid"},
        {"store_id": str(uuid4())},
    ]:
        assert (await client.get("/api/v1/products", params=params)).status_code == 422
