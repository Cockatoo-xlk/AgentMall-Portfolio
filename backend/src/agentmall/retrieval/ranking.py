"""Optional reranking of an authorized hybrid pool; old search defaults stay unchanged."""

import asyncio
import math
import time
from dataclasses import replace

from sqlalchemy import select

from agentmall.catalog.models import Product
from agentmall.catalog.service import product_dto
from agentmall.infra.errors import DomainError
from agentmall.retrieval.embedding import MODEL, REVISION, identity
from agentmall.retrieval.ingest import PRODUCT_INDEX_VERSION, digest, product_text
from agentmall.retrieval.models import ProductSearch as P
from agentmall.retrieval.search import CONFIG, product_scope, retrieve_products


async def revalidate(session, actor, filters, hits, encoder):
    if not hits:
        return []
    model, revision = identity(encoder) if encoder else (MODEL, REVISION)
    rows = (
        await session.execute(
            select(Product, P)
            .join(P)
            .where(
                *product_scope(actor, filters),
                Product.id.in_([h.id for h in hits]),
                P.embedding_model == model,
                P.embedding_revision == revision,
                P.tokenizer_version == PRODUCT_INDEX_VERSION,
            )
            .execution_options(populate_existing=True)
        )
    ).all()
    valid = {
        p.id: product_dto(p) for p, index in rows if index.content_hash == digest(product_text(p))
    }
    return [
        hit
        for hit in hits
        if hit.id in valid and valid[hit.id].model_dump() == hit.product.model_dump()
    ]


async def reranked_products(
    session, actor, query, filters, encoder, reranker, *, fallback=False, config=CONFIG
):
    if filters.mode != "hybrid":
        raise DomainError(422, "HYBRID_REQUIRED", "重排仅接受Hybrid候选")
    if not 1 <= config.candidates <= 20 or config.top_k != 5:
        raise ValueError("Bounded20/5 rerank contract")
    started = time.perf_counter()
    pool = await retrieve_products(
        session, actor, query, filters, encoder, replace(config, top_k=config.candidates)
    )
    retrieval_ms = (time.perf_counter() - started) * 1000
    status = "OK"
    scores = None
    rank_ms = None
    if reranker is None:
        if not fallback:
            raise DomainError(503, "RERANKER_UNAVAILABLE", "本地重排模型未启用或权重不可用")
        status = "FALLBACK_MODEL_UNAVAILABLE"
    elif pool:
        score_started = time.perf_counter()
        try:
            scores = await asyncio.to_thread(
                reranker.score, query, [product_text_proxy(h.product) for h in pool]
            )
            if len(scores) != len(pool) or any(
                type(s) not in (int, float) or not math.isfinite(s) for s in scores
            ):
                raise ValueError("Invalid scores")
            rank_ms = (time.perf_counter() - score_started) * 1000
        except Exception as error:
            if not fallback:
                raise DomainError(503, "RERANKER_FAILED", "本地重排失败；没有业务写入") from error
            status = "FALLBACK_MODEL_ERROR"
    valid = await revalidate(session, actor, filters, pool, encoder)
    score_map = (
        {h.id: float(s) for h, s in zip(pool, scores, strict=True)}
        if scores is not None and status == "OK"
        else {}
    )
    ranked = sorted(valid, key=lambda h: (-score_map[h.id], str(h.id))) if score_map else valid
    return {
        "items": ranked[: config.top_k],
        "candidate_ids": [str(h.id) for h in valid],
        "ranking": "CROSS_ENCODER" if status == "OK" else "HYBRID_FALLBACK",
        "rerank_status": status,
        "reranker_model": getattr(reranker, "model_id", None),
        "reranker_revision": getattr(reranker, "revision", None),
        "retrieval_ms": retrieval_ms,
        "rerank_ms": rank_ms,
        "pipeline_ms": (time.perf_counter() - started) * 1000,
        "scores": [{"id": str(h.id), "score": score_map[h.id]} for h in ranked[: config.top_k]]
        if score_map
        else [],
    }


def product_text_proxy(dto):
    # Exact current domain facts; no model-generated descriptions or hidden fields.
    import json

    from agentmall.catalog.categories import CATEGORY_LABELS

    return f"{dto.name}\n{CATEGORY_LABELS[dto.category]}\n{dto.description}\n" + json.dumps(
        dto.attributes, ensure_ascii=False, sort_keys=True
    )
