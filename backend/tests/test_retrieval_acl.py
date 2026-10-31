"""ACL failures must not disclose knowledge or counts."""


async def test_knowledge_requires_authentication(client):
    response = await client.get("/api/v1/knowledge/search", params={"query": "退货"})
    assert response.status_code == 401


async def test_knowledge_rejects_foreign_order(client, buyer2):
    response = await client.get(
        "/api/v1/knowledge/search",
        headers=buyer2,
        params={"query": "退货", "order_id": "00000000-0000-0000-0000-000000000999"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "ORDER_NOT_FOUND"


async def test_policy_acl_before_topk_and_no_business_mutation(env, buyer, buyer2, product):
    from aftersales_helpers import delivered_order
    from retrieval_helpers import index
    from sqlalchemy import text

    client, db, _, _ = env
    order = await delivered_order(client, buyer, product)
    await index(env)

    def snapshot():
        with db.connect() as c:
            return {
                t: c.execute(text(f"SELECT to_jsonb(t) FROM {t} t ORDER BY id")).all()
                for t in ("orders", "products", "refunds", "aftersales_cases", "business_events")
            }

    before = snapshot()
    for mode in ("lexical", "vector", "hybrid"):
        r = await client.get(
            "/api/v1/knowledge/search",
            headers=buyer,
            params={"query": "质量问题退货", "order_id": order["id"], "mode": mode},
        )
        assert r.status_code == 200, r.text
        assert r.json()["items"]
        for hit in r.json()["items"]:
            assert hit["policy_version"] == "demo-v1"
            assert hit["visibility"] == "public"
            assert hit["source_uri"].startswith("fixture://policies/")
            assert hit["section_id"] and hit["text"]
        denied = await client.get(
            "/api/v1/knowledge/search",
            headers=buyer2,
            params={"query": "退货", "order_id": order["id"], "mode": mode},
        )
        assert denied.status_code == 404
        assert "items" not in denied.json()
    assert snapshot() == before
