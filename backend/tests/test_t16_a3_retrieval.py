"""Category vocabulary, document freshness and existing scoped PostgreSQL recall."""

from types import SimpleNamespace

import pytest
from retrieval_helpers import actor, index
from sqlalchemy import text

from agentmall.retrieval.ingest import digest, product_text
from agentmall.retrieval.schemas import ProductQuery
from agentmall.retrieval.search import CONFIG, retrieve_products
from agentmall.retrieval.tokenize import TOKENIZER_VERSION


@pytest.mark.parametrize(
    "category,label", [("keyboard", "键盘"), ("mouse", "鼠标"), ("headphones", "耳机")]
)
def test_product_document_has_trusted_chinese_category(category, label):
    product = SimpleNamespace(name="合成SKU", category=category, description="演示", attributes={})
    value = product_text(product)
    assert category in value.splitlines() and label in value.splitlines()


def test_unknown_category_does_not_gain_guessed_label():
    product = SimpleNamespace(name="合成SKU", category="unknown", description="演示", attributes={})
    assert not any(label in product_text(product) for label in ["键盘", "鼠标", "耳机"])
    assert CONFIG.min_similarity == 0.45


async def search(env, encoder, query="键盘", **kw):
    async with env[2].state.sessions.begin() as session:
        return await retrieve_products(
            session, actor(env[3]), query, ProductQuery(query=query, mode="lexical", **kw), encoder
        )


async def test_generic_category_lexical_recall_is_not_empty(env):
    encoder = await index(env)
    hits = await search(
        env, encoder, category="keyboard", max_price_cents=30000, noise_preference="quiet"
    )
    assert hits
    assert all(h.product.category == "keyboard" and h.product.price_cents <= 30000 for h in hits)


async def test_old_document_format_requires_explicit_rebuild(env):
    encoder = await index(env)
    with env[1].begin() as conn:
        conn.execute(
            text("UPDATE product_search SET tokenizer_version=:v"), {"v": TOKENIZER_VERSION}
        )
    assert await search(env, encoder, query="静音") == []
    await index(env)
    assert await search(env, encoder, query="静音")


async def test_current_source_hash_is_rechecked(env):
    encoder = await index(env)
    with env[1].begin() as conn:
        conn.execute(text("UPDATE product_search SET content_hash=:bad"), {"bad": "0" * 64})
    assert await search(env, encoder, query="静音") == []


async def test_unrebuilt_source_change_fails_closed_even_without_version_bump(env):
    encoder = await index(env)
    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET description=description || ' new source'"))
    assert await search(env, encoder, query="静音") == []


async def test_rebuild_records_current_version_hash_and_ids(env):
    from sqlalchemy import select

    from agentmall.catalog.models import Product
    from agentmall.retrieval.models import ProductSearch

    encoder = await index(env)
    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET catalog_version=catalog_version+1"))
    assert await search(env, encoder, query="静音") == []
    await index(env)
    async with env[2].state.sessions.begin() as session:
        rows = (await session.execute(select(Product, ProductSearch).join(ProductSearch))).all()
        assert len(rows) == 12
        for product, document in rows:
            assert product.id == document.product_id
            assert document.source_version == product.catalog_version == 2
            assert document.content_hash == digest(product_text(product))
            assert document.tokenizer_version != TOKENIZER_VERSION
    assert await search(env, encoder, query="静音")


async def test_category_expansion_does_not_return_unrelated_lexical_results(env):
    encoder = await index(env)
    assert await search(env, encoder, query="航空发动机涡轮叶片") == []
