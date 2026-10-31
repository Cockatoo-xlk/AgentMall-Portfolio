"""Callers cannot choose policy version or store scope."""


async def test_policy_version_cannot_be_selected(client, buyer):
    response = await client.get(
        "/api/v1/knowledge/search",
        headers=buyer,
        params={"query": "退货", "policy_version": "demo-v999"},
    )
    assert response.status_code == 422


async def test_product_retrieval_rejects_store_override(client):
    response = await client.get(
        "/api/v1/retrieval/products",
        params={"query": "静音键盘", "store_id": "00000000-0000-0000-0000-000000000999"},
    )
    assert response.status_code == 422


async def test_product_filters_and_stale_index_all_modes(env):
    from retrieval_helpers import index
    from sqlalchemy import text

    client, db, _, _ = env
    await index(env)
    with db.begin() as c:
        c.execute(text("UPDATE products SET active=false WHERE name='静音 K87'"))
        c.execute(text("UPDATE products SET on_hand=reserved WHERE name='静音 K98'"))
        c.execute(text("UPDATE products SET catalog_version=2 WHERE name='静音 K104'"))
        c.execute(text("UPDATE products SET price_cents=90000 WHERE name='办公 K108'"))
    for mode in ("lexical", "vector", "hybrid"):
        r = await client.get(
            "/api/v1/retrieval/products",
            params={
                "query": "静音键盘",
                "category": "keyboard",
                "max_price_cents": 20000,
                "mode": mode,
            },
        )
        assert r.status_code == 200, r.text
        hits = r.json()["items"]
        assert hits
        assert {h["product"]["name"] for h in hits} <= {"宿舍静音 K68", "轻巧 K61"}
        assert all(h["product"]["available"] > 0 for h in hits)


async def test_order_version_binds_policy_not_query(env, buyer, product):
    from aftersales_helpers import delivered_order
    from retrieval_helpers import index
    from test_aftersales import rewrite_owned_order

    order = await delivered_order(env[0], buyer, product)
    await index(env)
    rewrite_owned_order(env[1], order["id"], policy_version="unknown-version")
    for mode in ("lexical", "vector", "hybrid"):
        response = await env[0].get(
            "/api/v1/knowledge/search",
            headers=buyer,
            params={"query": "质量问题退货", "order_id": order["id"], "mode": mode},
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []


async def test_catalog_rebuild_restores_new_version(env):
    from retrieval_helpers import index
    from sqlalchemy import text

    from agentmall.retrieval.ingest import index_products

    encoder = await index(env)
    with env[1].begin() as c:
        c.execute(
            text(
                "UPDATE products SET name='新款紫色键盘',catalog_version=2 "
                "WHERE name='宿舍静音 K68'"
            )
        )
    params = {"query": "紫色", "mode": "lexical"}
    assert (await env[0].get("/api/v1/retrieval/products", params=params)).json()["items"] == []
    async with env[2].state.sessions.begin() as session:
        await index_products(session, env[3].storefront_id, encoder)
    hits = (await env[0].get("/api/v1/retrieval/products", params=params)).json()["items"]
    assert len(hits) == 1 and hits[0]["source_version"] == 2


async def test_0004_to_0005_preserves_refund_and_aftersales_history(env, buyer, product):
    from aftersales_helpers import (
        delivered_order,
        execute_refund,
        merchant_headers,
        received_case,
        refund_proposal,
    )
    from alembic import command
    from alembic.config import Config
    from conftest import ROOT
    from sqlalchemy import text

    client, db, _, _ = env
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    with db.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0004")
    merchant = await merchant_headers(client)
    order = await delivered_order(client, buyer, product, merchant)
    case = await received_case(client, buyer, order, merchant)
    proposal = await refund_proposal(client, merchant, case)
    assert (await execute_refund(client, merchant, case, proposal)).status_code == 201

    def snapshot():
        with db.connect() as c:
            return {
                table: c.execute(text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id")).all()
                for table in (
                    "aftersales_cases",
                    "refunds",
                    "business_events",
                    "orders",
                    "payments",
                    "products",
                )
            }

    before = snapshot()
    assert len(before["refunds"]) == 1
    with db.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "head")
        command.check(cfg)
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        assert (
            c.scalar(
                text(
                    "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n "
                    "ON n.oid=e.extnamespace WHERE e.extname='vector'"
                )
            )
            == "extensions"
        )
    assert snapshot() == before


async def test_concurrent_reindex_does_not_relabel_old_candidate_as_new_match(env):
    from uuid import uuid5

    from retrieval_helpers import FixtureEncoder, actor, index
    from sqlalchemy import text

    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import retrieve_products

    await index(env)
    product_id = uuid5(env[3].storefront_id, "synthetic-sku-01")

    class ReindexDuringEncoding(FixtureEncoder):
        def encode(self, texts, *, query=False):
            assert query
            with env[1].begin() as c:
                c.execute(
                    text(
                        "UPDATE products SET name='红色鼠标',description='',attributes='{}',"
                        "catalog_version=2 WHERE id=:id"
                    ),
                    {"id": product_id},
                )
                c.execute(
                    text(
                        "UPDATE product_search SET source_version=2,content_hash='new',"
                        "search_tsv=to_tsvector('simple','红色 鼠标'),embedding=:vector "
                        "WHERE product_id=:id"
                    ),
                    {"id": product_id, "vector": "[0,1," + ",".join(["0"] * 510) + "]"},
                )
            return super().encode(texts, query=query)

    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            "k68",
            ProductQuery(query="k68", mode="hybrid"),
            ReindexDuringEncoding(),
        )
    assert product_id not in {h.id for h in hits}
    with env[1].connect() as c:
        assert (
            c.scalar(text("SELECT catalog_version FROM products WHERE id=:id"), {"id": product_id})
            == 2
        )
