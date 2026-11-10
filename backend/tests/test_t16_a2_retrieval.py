"""Real PostgreSQL scope precedes both recall limits and the fused TopK."""

from uuid import uuid4

import pytest
from retrieval_helpers import actor, index
from sqlalchemy import text

from agentmall.retrieval.schemas import ProductQuery
from agentmall.retrieval.search import SearchConfig, retrieve_products


@pytest.mark.parametrize(
    "budget,want",
    [
        (29899, set()),
        (29900, {"静音 K87"}),
        (35899, {"静音 K87"}),
        (35900, {"静音 K87", "办公 K108"}),
        (39899, {"静音 K87", "办公 K108"}),
        (39900, {"静音 K87", "办公 K108", "静音 K98"}),
        (40000, {"静音 K87", "办公 K108", "静音 K98"}),
    ],
)
async def test_default_catalogue_wireless_budget_boundaries(env, budget, want):
    encoder = await index(env)
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            "静音无线键盘",
            ProductQuery(
                query="静音无线键盘",
                mode="vector",
                category="keyboard",
                max_price_cents=budget,
                noise_preference="quiet",
                connection="无线",
            ),
            encoder,
        )
        assert {hit.product.name for hit in hits} == want
        assert all(hit.product.attributes["connection"] in {"双模", "三模"} for hit in hits)
        assert all("wireless" in hit.product.attributes["connection_capabilities"] for hit in hits)


async def test_ineligible_topk_cannot_starve_eligible_products(env):
    from agentmall.catalog.models import Product

    async with env[2].state.sessions.begin() as session:
        # These sort ahead of every seed UUID at the same fixture-vector distance.
        for i in range(1, 9):
            from uuid import UUID

            session.add(
                Product(
                    id=UUID(int=i),
                    store_id=env[3].storefront_id,
                    name=f"合成高排名有线 {i}",
                    category="keyboard",
                    price_cents=10000,
                    on_hand=20,
                    reserved=0,
                    active=True,
                    catalog_version=1,
                    attributes={"connection": "有线", "noise": "明显"},
                    description="合成候选截断反例",
                )
            )
    encoder = await index(env)
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            "键盘",
            ProductQuery(
                query="键盘",
                mode="hybrid",
                category="keyboard",
                max_price_cents=40000,
                noise_preference="quiet",
                connection="无线",
            ),
            encoder,
            config=SearchConfig(candidates=3, top_k=3),
        )
    assert {h.product.name for h in hits} == {"静音 K87", "静音 K98", "办公 K108"}


async def test_stock_visibility_tenant_version_and_strict_labels(env):
    encoder = await index(env)
    async with env[2].state.sessions.begin() as session:

        async def search(**extra):
            return await retrieve_products(
                session,
                actor(env[3]),
                "键盘",
                ProductQuery(
                    query="键盘",
                    mode="vector",
                    category="keyboard",
                    max_price_cents=40000,
                    noise_preference="quiet",
                    **extra,
                ),
                encoder,
            )

        assert {h.product.name for h in await search(connection="有线")} == {"宿舍静音 K68"}
        assert await search(connection="无线", excluded_connections=["双模", "三模"]) == []
    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET on_hand=0 WHERE name='静音 K87'"))
        conn.execute(text("UPDATE products SET active=false WHERE name='静音 K98'"))
        conn.execute(text("UPDATE products SET store_id=:s WHERE name='办公 K108'"), {"s": uuid4()})
    async with env[2].state.sessions.begin() as session:
        assert (
            await retrieve_products(
                session,
                actor(env[3]),
                "键盘",
                ProductQuery(
                    query="键盘",
                    mode="vector",
                    connection="无线",
                    category="keyboard",
                    max_price_cents=40000,
                    noise_preference="quiet",
                ),
                encoder,
            )
            == []
        )


async def test_changed_capability_requires_new_versioned_index(env):
    encoder = await index(env)
    with env[1].begin() as conn:
        conn.execute(
            text(
                "UPDATE products SET catalog_version=catalog_version+1, "
                "attributes=jsonb_set(attributes,'{connection_capabilities}','[\"wired\"]') "
                "WHERE name='静音 K87'"
            )
        )
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            "键盘",
            ProductQuery(
                query="键盘",
                mode="vector",
                connection="无线",
                category="keyboard",
                max_price_cents=29900,
            ),
            encoder,
        )
        assert hits == []
    await index(env)
    async with env[2].state.sessions.begin() as session:
        assert (
            await retrieve_products(
                session,
                actor(env[3]),
                "键盘",
                ProductQuery(
                    query="键盘",
                    mode="vector",
                    connection="无线",
                    category="keyboard",
                    max_price_cents=29900,
                ),
                encoder,
            )
            == []
        )
