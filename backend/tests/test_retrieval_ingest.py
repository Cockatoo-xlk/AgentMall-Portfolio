import pytest
from retrieval_helpers import FixtureEncoder, index
from sqlalchemy import text


async def test_repeat_ingest_and_failed_batch_atomic(env):
    from agentmall.retrieval.ingest import index_products

    await index(env)
    await index(env)
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM product_search")) == 12
        before = c.execute(
            text("SELECT product_id, embedding::text FROM product_search ORDER BY product_id")
        ).all()

    class Broken(FixtureEncoder):
        def encode(self, texts, *, query=False):
            return super().encode(texts, query=query)[:-1] + [[0.0] * 7]

    with pytest.raises(ValueError):
        async with env[2].state.sessions.begin() as session:
            await index_products(session, env[3].storefront_id, Broken())
    with env[1].connect() as c:
        assert (
            c.execute(
                text("SELECT product_id, embedding::text FROM product_search ORDER BY product_id")
            ).all()
            == before
        )


async def test_wrong_revision_rejected(env):
    from agentmall.retrieval.ingest import index_products

    encoder = FixtureEncoder()
    encoder.revision = "unknown"
    with pytest.raises(ValueError):
        async with env[2].state.sessions.begin() as session:
            await index_products(session, env[3].storefront_id, encoder)
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM product_search")) == 0


@pytest.mark.parametrize("bad", ["dimension", "norm", "revision"])
async def test_database_rejects_invalid_embedding(env, bad):
    from sqlalchemy.exc import DBAPIError

    await index(env)
    assignment = {
        "dimension": "embedding='[1,0]'",
        "norm": "embedding=embedding*2",
        "revision": "embedding_revision='untrusted'",
    }[bad]
    # pgvector has no scalar multiply operator; use a 512D non-unit literal instead.
    if bad == "norm":
        assignment = "embedding='[2," + ",".join(["0"] * 511) + "]'"
    with pytest.raises(DBAPIError), env[1].begin() as c:
        c.execute(text("UPDATE product_search SET " + assignment))


async def test_policies_immutable_and_failed_source_batch_rollback(env):
    from copy import deepcopy

    from agentmall.retrieval.ingest import index_policies, load_policies

    encoder = await index(env)
    documents = deepcopy(load_policies())
    documents[-1]["sections"][0]["text"] = "修改已生效版本到无限退货"
    with pytest.raises(ValueError):
        async with env[2].state.sessions.begin() as session:
            await index_policies(session, documents, encoder)
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM knowledge_documents")) == 10
        assert (
            c.scalar(text("SELECT count(*) FROM knowledge_chunks WHERE text LIKE '%无限退货%'"))
            == 0
        )


async def test_cosine_order_is_computed_in_postgres(env):
    from retrieval_helpers import actor
    from sqlalchemy import select, update

    from agentmall.retrieval.models import ProductSearch
    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import SearchConfig, retrieve_products

    encoder = await index(env)
    async with env[2].state.sessions.begin() as session:
        ids = list(
            await session.scalars(
                select(ProductSearch.product_id).order_by(ProductSearch.product_id)
            )
        )
        await session.execute(update(ProductSearch).values(embedding=[0.0, 1.0] + [0.0] * 510))
        await session.execute(
            update(ProductSearch)
            .where(ProductSearch.product_id == ids[-1])
            .values(embedding=[1.0] + [0.0] * 511)
        )
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            "键盘",
            ProductQuery(query="键盘", mode="vector"),
            encoder,
            SearchConfig(min_similarity=0.9),
        )
        assert [h.id for h in hits] == [ids[-1]]


@pytest.mark.real_bge
async def test_real_embedding_offline_sql_roundtrip(env):
    import asyncio
    from pathlib import Path

    from retrieval_helpers import actor

    from agentmall.retrieval.embedding import REVISION, ROOT, LocalEncoder
    from agentmall.retrieval.ingest import index_products
    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import retrieve_products

    # Optional dependency/model is explicit; never download from a test.
    if not await asyncio.to_thread(Path(ROOT / ".models" / REVISION / "model.safetensors").exists):
        pytest.skip("NOT_RUN: project-local real model absent; run evals/embed.py --download")
    encoder = await asyncio.to_thread(LocalEncoder)
    async with env[2].state.sessions.begin() as session:
        await index_products(session, env[3].storefront_id, encoder)
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            "宿舍静音 K68",
            ProductQuery(query="宿舍静音 K68", mode="vector"),
            encoder,
        )
    assert hits and hits[0].product.name == "宿舍静音 K68"
    with env[1].connect() as c:
        assert (
            c.scalar(text("SELECT min(extensions.vector_dims(embedding)) FROM product_search"))
            == 512
        )
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM product_search "
                    "WHERE embedding_model='BAAI/bge-small-zh-v1.5'"
                )
            )
            == 12
        )
