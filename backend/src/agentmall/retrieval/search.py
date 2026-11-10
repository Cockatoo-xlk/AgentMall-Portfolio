"""Exact filtered recall. No generated answers or business mutations."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, or_, select, tuple_

from agentmall.catalog.capabilities import connection_conditions
from agentmall.catalog.categories import KIND_ATTRIBUTES
from agentmall.catalog.models import Product
from agentmall.catalog.service import product_dto
from agentmall.identity.service import require_buyer
from agentmall.infra.errors import DomainError
from agentmall.orders.models import Order
from agentmall.retrieval.embedding import MODEL, REVISION, identity, validate_vectors
from agentmall.retrieval.ingest import PRODUCT_INDEX_VERSION, digest, product_text
from agentmall.retrieval.models import KnowledgeChunk as K
from agentmall.retrieval.models import KnowledgeDocument as D
from agentmall.retrieval.models import ProductSearch as P
from agentmall.retrieval.schemas import CitationChunk, SearchHit
from agentmall.retrieval.tokenize import TOKENIZER_VERSION, query_tokens


@dataclass(frozen=True)
class SearchConfig:
    candidates: int = 20
    rrf_k: int = 60
    top_k: int = 5
    min_similarity: float = 0.45


CONFIG = SearchConfig()


def rrf(rankings, config=CONFIG):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, entity in enumerate(dict.fromkeys(ranking), 1):
            scores[entity] += 1 / (config.rrf_k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))[: config.top_k]


async def recall(session, base, index, key, query, mode, encoder, config, *, versioned=False):
    lexical_query = query_tokens(query)
    if not lexical_query:
        return []
    model, revision = identity(encoder) if encoder else (MODEL, REVISION)
    base = base.where(
        index.embedding_model == model,
        index.embedding_revision == revision,
        index.tokenizer_version == (PRODUCT_INDEX_VERSION if index is P else TOKENIZER_VERSION),
    )
    rankings, values = [], {}
    if mode in ("lexical", "hybrid"):
        tsquery = func.to_tsquery("simple", lexical_query)
        rank = func.ts_rank_cd(index.search_tsv, tsquery)
        rows = (
            await session.execute(
                base.where(index.search_tsv.op("@@")(tsquery))
                .order_by(rank.desc(), key)
                .limit(config.candidates)
            )
        ).all()
        rankings.append(rows)
        values.update({row[0]: row for row in rows})
    if mode in ("vector", "hybrid"):
        if encoder is None:
            raise DomainError(503, "EMBEDDING_UNAVAILABLE", "本地检索模型尚未配置")
        vector = validate_vectors(
            encoder, await asyncio.to_thread(encoder.encode, [query], query=True), 1
        )[0]
        distance = index.embedding.cosine_distance(vector)
        rows = (
            await session.execute(
                base.where(distance <= 1 - config.min_similarity)
                .order_by(distance, key)
                .limit(config.candidates)
            )
        ).all()
        rankings.append(rows)
        values.update({row[0]: row for row in rows})
    # A rebuild between recall passes must not combine evidence from two versions.
    identities = [
        [row[0] for row in rows if not versioned or row[1:3] == values[row[0]][1:3]]
        for rows in rankings
    ]
    # Single-mode ranking remains its own rank order (RRF of one list is monotonic).
    return [(values[entity], score) for entity, score in rrf(identities, config)]


def product_scope(actor, filters):
    conditions = [
        Product.store_id == actor.store_id,
        Product.active.is_(True),
        Product.catalog_version == P.source_version,
    ]
    if filters.category:
        conditions.append(Product.category == filters.category)
    if filters.max_price_cents is not None:
        conditions.append(Product.price_cents <= filters.max_price_cents)
    if filters.in_stock:
        conditions.append(Product.on_hand > Product.reserved)
    if filters.usage:
        conditions.append(
            Product.attributes["usage"].as_string().icontains(filters.usage, autoescape=True)
        )
    if filters.product_kind:
        category, attribute, term = KIND_ATTRIBUTES[filters.product_kind]
        conditions.extend(
            [
                Product.category == category,
                Product.attributes[attribute].as_string().icontains(term, autoescape=True),
            ]
        )
    if filters.screen_inches is not None:
        conditions.append(Product.attributes["screen_inches"].as_string() == filters.screen_inches)
    if filters.activity == "road_cycling":
        conditions.append(Product.attributes["usage"].as_string() == "公路车骑行")
    if filters.noise_preference:
        conditions.append(Product.attributes["noise"].as_string() == "较安静")
    if filters.layout:
        conditions.append(Product.attributes["size"].as_string() == filters.layout)
    conditions.extend(
        connection_conditions(Product.attributes, filters.connection, filters.excluded_connections)
    )
    if filters.exclude_product_ids:
        conditions.append(Product.id.not_in(filters.exclude_product_ids))
    if filters.keyboard_type:
        switches = (
            ["薄膜"]
            if filters.keyboard_type == "membrane"
            else ["静音轴", "线性轴", "段落轴", "青轴", "茶轴", "红轴"]
        )
        conditions.append(Product.attributes["switch"].as_string().in_(switches))
    return conditions


async def retrieve_products(session, actor, query, filters, encoder=None, config=CONFIG):
    scope = product_scope(actor, filters)
    base = (
        select(P.product_id, P.source_version, P.content_hash)
        .join(Product, Product.id == P.product_id)
        .where(*scope)
    )
    candidates = await recall(
        session, base, P, P.product_id, query, filters.mode, encoder, config, versioned=True
    )
    if not candidates:
        return []
    # A fresh READ COMMITTED statement rechecks current facts after both recall passes.
    products = {
        p.id: p
        for p in await session.scalars(
            select(Product)
            .join(P)
            .where(
                *scope,
                tuple_(Product.id, P.source_version, P.content_hash).in_(
                    [tuple(row) for row, _ in candidates]
                ),
            )
            .execution_options(populate_existing=True)
        )
    }
    return [
        SearchHit(
            id=row[0],
            product=product_dto(products[row[0]]),
            source_uri=f"/api/v1/products/{row[0]}",
            source_version=products[row[0]].catalog_version,
            score=score,
        )
        for row, score in candidates
        if row[0] in products and row[2] == digest(product_text(products[row[0]]))
    ]


async def policy_scope(session, actor, order_id):
    require_buyer(actor)
    # Without an order, expose the current deterministic demo policy only.
    version = "demo-v1"
    if order_id is not None:
        order = await session.scalar(
            select(Order).where(
                Order.id == order_id,
                Order.user_id == actor.user_id,
                Order.store_id == actor.store_id,
            )
        )
        if order is None:
            raise DomainError(404, "ORDER_NOT_FOUND", "订单不存在或不可访问")
        version = order.policy_version
    return [
        D.store_id == actor.store_id,
        D.visibility == "public",
        D.kind == "policy",
        D.version == version,
        D.valid_from <= func.now(),
        or_(D.valid_to.is_(None), D.valid_to > func.now()),
    ]


async def retrieve_policies(
    session, actor, order_id, query, mode="hybrid", encoder=None, config=CONFIG
):
    scope = await policy_scope(session, actor, order_id)  # Authorize BEFORE encoding/recall.
    base = select(K.id, K, D).join(D).where(*scope)
    candidates = await recall(session, base, K, K.id, query, mode, encoder, config)
    return [
        CitationChunk(
            id=k.id,
            document_id=d.id,
            title=d.title,
            text=k.text,
            section_id=k.section_id,
            source_uri=f"{d.source_uri}#{k.section_id}",
            policy_version=d.version,
            visibility="public",
            score=score,
        )
        for (_, k, d), score in candidates
    ]
