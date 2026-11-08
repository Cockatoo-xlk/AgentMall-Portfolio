"""Ranking changes only; real owned PostgreSQL, synthetic scoring never claims quality."""

import pytest
from retrieval_helpers import index
from sqlalchemy import text


class FixtureReranker:
    model_id = "fixture/reranker"
    revision = "test-only"
    timeout_seconds = 1
    load_ms = 0

    def score(self, query, documents):
        return [float(i) for i in range(len(documents))]


async def test_explicit_rerank_endpoint_reads_same_authorized_facts_without_writes(env):
    from agentmall.seed import seed

    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    await index(env)
    env[2].state.retrieval_reranker = FixtureReranker()
    with env[1].connect() as c:
        before = c.scalar(text("SELECT sum(reserved) FROM products"))
    response = await env[0].get(
        "/api/v1/retrieval/products/reranked",
        params={"query": "手机", "category": "smartphone", "max_price_cents": 300000},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ranking"] == "CROSS_ENCODER" and data["rerank_status"] == "OK"
    assert 1 <= len(data["items"]) <= 5
    assert all(
        i["product"]["category"] == "smartphone" and i["product"]["price_cents"] <= 300000
        for i in data["items"]
    )
    assert set(i["id"] for i in data["items"]) <= set(data["candidate_ids"])
    with env[1].connect() as c:
        assert c.scalar(text("SELECT sum(reserved) FROM products")) == before
        assert c.scalar(text("SELECT count(*) FROM action_proposals")) == 0
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0


@pytest.mark.parametrize("kind", ["missing", "exception", "nan", "wrong_shape"])
async def test_missing_or_failed_reranker_never_silently_enables_or_writes(env, kind):
    await index(env)

    class Failed(FixtureReranker):
        def score(self, query, docs):
            if kind == "exception":
                raise RuntimeError("sensitive-internal-marker")
            return [float("nan")] * len(docs) if kind == "nan" else []

    env[2].state.retrieval_reranker = None if kind == "missing" else Failed()
    response = await env[0].get("/api/v1/retrieval/products/reranked", params={"query": "键盘"})
    assert response.status_code == 503, response.text
    assert "sensitive-internal-marker" not in response.text
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0
        assert c.scalar(text("SELECT count(*) FROM action_proposals")) == 0
    env[2].state.reranker_fallback = True
    fallback = await env[0].get("/api/v1/retrieval/products/reranked", params={"query": "键盘"})
    assert fallback.status_code == 200 and fallback.json()["ranking"] == "HYBRID_FALLBACK"
    assert fallback.json()["rerank_status"].startswith("FALLBACK_")
    assert fallback.json()["rerank_ms"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "price_cents=price_cents+1",
        "catalog_version=catalog_version+1",
        "active=false",
        "on_hand=reserved",
        "store_id='00000000-0000-0000-0000-000000000999'",
    ],
)
async def test_catalog_race_during_scoring_cannot_return_changed_or_foreign_facts(env, mutation):
    await index(env)

    class Racing(FixtureReranker):
        def score(self, query, documents):
            with env[1].begin() as c:
                c.execute(text("UPDATE products SET " + mutation + " WHERE category='keyboard'"))
            return super().score(query, documents)

    env[2].state.retrieval_reranker = Racing()
    response = await env[0].get(
        "/api/v1/retrieval/products/reranked", params={"query": "键盘", "category": "keyboard"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [] and response.json()["candidate_ids"] == []
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0


async def test_no_explicit_rerank_leaves_original_search_unchanged(env):
    await index(env)

    class MustNotRun(FixtureReranker):
        def score(self, *args):
            raise AssertionError("Default search must not rerank")

    env[2].state.retrieval_reranker = MustNotRun()
    response = await env[0].get("/api/v1/retrieval/products", params={"query": "键盘"})
    assert response.status_code == 200 and response.json()["items"]


def slow_worker(pipe, directory):
    import time

    pipe.send({"ready": True})
    pipe.recv()
    time.sleep(5)


def test_cpu_timeout_terminates_real_worker_and_does_not_automatically_restart(
    monkeypatch, tmp_path
):
    from agentmall.retrieval import reranker

    monkeypatch.setattr(reranker, "verify_files", lambda directory: {})
    monkeypatch.setattr(reranker, "_worker", slow_worker)
    model = reranker.LocalReranker(tmp_path, timeout_seconds=0.05, load_timeout_seconds=5)
    try:
        with pytest.raises(reranker.RerankError, match="TIMEOUT"):
            model.score("合成查询", ["合成文档"])
        assert not model._process.is_alive()
        with pytest.raises(reranker.RerankError, match="UNAVAILABLE"):
            model.score("合成查询", ["合成文档"])
        assert model.calls == 1
    finally:
        model.close()


def test_model_files_missing_fail_before_any_model_inference(tmp_path):
    from agentmall.retrieval.reranker import LocalReranker, RerankError

    with pytest.raises(RerankError, match="MISSING"):
        LocalReranker(tmp_path)


def crashed_worker(pipe, directory):
    pipe.close()


def test_model_load_crash_is_structured_and_leaves_no_worker(monkeypatch, tmp_path):
    from agentmall.retrieval import reranker

    monkeypatch.setattr(reranker, "verify_files", lambda path: {})
    monkeypatch.setattr(reranker, "_worker", crashed_worker)
    with pytest.raises(reranker.RerankError, match="UNAVAILABLE"):
        reranker.LocalReranker(tmp_path, load_timeout_seconds=5)


async def test_quality_safety_oracle_checks_store_independently_of_retrieval_filter(
    env, monkeypatch
):
    from evals import expanded_retrieval as evaluation

    from agentmall.identity.service import ActorContext
    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import retrieve_products

    await index(env)
    actor = ActorContext(None, "public", env[3].storefront_id)
    filters = ProductQuery(query="键盘")
    async with env[2].state.sessions.begin() as s:
        hits = await retrieve_products(s, actor, "键盘", filters, env[2].state.retrieval_encoder)
    with env[1].begin() as c:
        c.execute(
            text(
                "UPDATE products SET store_id='00000000-0000-0000-0000-000000000999' WHERE id=:id"
            ),
            {"id": hits[0].id},
        )
    monkeypatch.setattr(evaluation, "product_scope", lambda actor, filters: [], raising=False)
    async with env[2].state.sessions.begin() as s:
        violations = await evaluation.audit_hits(s, actor, filters, [hits[0]])
    assert "ACL_STOCK_OR_FILTER" in violations
