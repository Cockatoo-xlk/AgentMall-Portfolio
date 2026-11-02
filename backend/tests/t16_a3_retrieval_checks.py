"""Mandatory real-BGE checks for the explicit offline verifier, never auto-skipped."""

from uuid import uuid4

from sqlalchemy import event, select, text, update

from agentmall.catalog.models import Product
from agentmall.identity.service import ActorContext
from agentmall.infra.db import database
from agentmall.retrieval.ingest import (
    PRODUCT_INDEX_VERSION,
    digest,
    index_products,
    product_text,
)
from agentmall.retrieval.models import ProductSearch
from agentmall.retrieval.schemas import ProductQuery
from agentmall.retrieval.search import CONFIG, retrieve_products
from agentmall.retrieval.tokenize import TOKENIZER_VERSION


async def verify(settings, encoder):
    assert encoder.model_id == "BAAI/bge-small-zh-v1.5" and encoder.dimension == 512
    assert CONFIG.min_similarity == 0.45
    engine, sessions = database(settings)
    cases, statements = [], []

    def observe(conn, cursor, statement, parameters, context, many):
        if "product_search" in statement and " LIMIT " in statement:
            statements.append(" ".join(statement.split()))

    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    try:
        async with sessions.begin() as session:
            u = (
                await session.execute(text("SELECT id,role FROM users WHERE login='buyer1'"))
            ).one()
            actor = ActorContext(u.id, u.role, settings.storefront_id)

        async def query(session, value, **constraints):
            return await retrieve_products(
                session, actor, value, ProductQuery(query=value, **constraints), encoder
            )

        async with sessions.begin() as session:
            for value, filters, minimum in [
                (
                    "键盘",
                    {"category": "keyboard", "max_price_cents": 30000, "noise_preference": "quiet"},
                    1,
                ),
                (
                    "静音键盘",
                    {"category": "keyboard", "max_price_cents": 30000, "noise_preference": "quiet"},
                    1,
                ),
                (
                    "无线静音键盘",
                    {
                        "category": "keyboard",
                        "max_price_cents": 40000,
                        "noise_preference": "quiet",
                        "connection": "无线",
                    },
                    2,
                ),
                ("鼠标", {"category": "mouse"}, 1),
                ("耳机", {"category": "headphones"}, 1),
            ]:
                statements.clear()
                hits = await query(session, value, **filters)
                assert len(hits) >= minimum, value
                for hit in hits:
                    p = hit.product
                    assert p.category == filters["category"] and p.available > 0
                    assert p.price_cents <= filters.get("max_price_cents", p.price_cents)
                    if filters.get("noise_preference"):
                        assert p.attributes["noise"] == "较安静"
                    if filters.get("connection"):
                        assert "wireless" in p.attributes["connection_capabilities"]
                if filters.get("connection"):
                    assert len(statements) == 2
                    for statement in statements:
                        where = statement[statement.index(" WHERE ") : statement.index(" LIMIT ")]
                        assert all(
                            x in where
                            for x in [
                                "products.attributes",
                                "products.price_cents",
                                "products.store_id",
                                "products.active",
                                "products.catalog_version",
                                "products.on_hand",
                                "products.reserved",
                            ]
                        )
                    scoped_sql = list(statements)
                cases.append(
                    {
                        "case": value,
                        "filters": filters,
                        "hits": [h.model_dump(mode="json") for h in hits],
                    }
                )
            unrelated = await query(session, "航空发动机涡轮叶片")
            assert unrelated == []
            cases.append({"case": "unrelated", "hits": []})

        # Controlled mutations in fresh owned schemas, always rolled back. No new SKU.
        for name, values in [
            ("over_budget", {"price_cents": 50000}),
            ("inactive", {"active": False}),
            ("no_stock", {"on_hand": Product.reserved}),
            ("cross_store", {"store_id": uuid4()}),
            ("catalog_version", {"catalog_version": Product.catalog_version + 1}),
            ("source_changed_without_version", {"description": Product.description + " changed"}),
        ]:
            async with sessions() as session:
                await session.begin()
                try:
                    await session.execute(update(Product).values(**values))
                    hits = await query(
                        session,
                        "无线静音键盘",
                        category="keyboard",
                        max_price_cents=40000,
                        noise_preference="quiet",
                        connection="无线",
                    )
                    assert hits == [], name
                    cases.append({"case": name, "hits": [], "mutation_rolled_back": True})
                finally:
                    await session.rollback()

        async with sessions() as session:
            await session.begin()
            try:
                await session.execute(update(ProductSearch).values(content_hash="0" * 64))
                assert await query(session, "键盘") == []
                cases.append(
                    {"case": "corrupt_content_hash", "hits": [], "mutation_rolled_back": True}
                )
            finally:
                await session.rollback()

        # Emulate the exact legacy document identity, then explicitly rebuild.
        async with sessions.begin() as session:
            products = list(await session.scalars(select(Product).order_by(Product.id)))
            old_hashes = {}
            for p in products:
                import json

                legacy = f"{p.name}\n{p.category}\n{p.description}\n" + json.dumps(
                    p.attributes, ensure_ascii=False, sort_keys=True
                )
                old_hashes[str(p.id)] = digest(legacy)
                await session.execute(
                    update(ProductSearch)
                    .where(ProductSearch.product_id == p.id)
                    .values(tokenizer_version=TOKENIZER_VERSION, content_hash=digest(legacy))
                )
        async with sessions.begin() as session:
            assert await query(session, "静音键盘") == []
            cases.append({"case": "legacy_index_not_current", "hits": []})
            await index_products(session, settings.storefront_id, encoder)
        async with sessions.begin() as session:
            rows = (await session.execute(select(Product, ProductSearch).join(ProductSearch))).all()
            rebuilt = []
            for p, doc in rows:
                assert doc.product_id == p.id and doc.source_version == p.catalog_version == 1
                assert doc.content_hash == digest(product_text(p)) != old_hashes[str(p.id)]
                assert doc.tokenizer_version == PRODUCT_INDEX_VERSION
                rebuilt.append(
                    {
                        "id": str(p.id),
                        "catalog_version": p.catalog_version,
                        "content_hash": doc.content_hash,
                        "legacy_hash": old_hashes[str(p.id)],
                        "document_version": doc.tokenizer_version,
                    }
                )
            assert len(rebuilt) == 12 and await query(session, "键盘")
            versions = list(
                await session.scalars(
                    text("SELECT DISTINCT tokenizer_version FROM knowledge_chunks")
                )
            )
            assert versions == [TOKENIZER_VERSION]
            dims = list(
                await session.scalars(
                    text("SELECT DISTINCT vector_dims(embedding) FROM product_search")
                )
            )
            assert dims == [512]
        return {
            "mode": "REAL_BGE_REAL_PGVECTOR_POSTGRES",
            "cases": cases,
            "rebuilt_documents": rebuilt,
            "recall_sql_without_parameters": scoped_sql,
            "filters_before_limit": True,
            "min_similarity": CONFIG.min_similarity,
            "dimensions": dims,
            "policy_tokenizer_versions": versions,
        }
    finally:
        await engine.dispose()
