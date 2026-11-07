"""Atomic, repeatable indexing. Caller owns the outer transaction."""

import asyncio
import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from agentmall.catalog.categories import CATEGORY_ALIASES, CATEGORY_LABELS
from agentmall.catalog.models import Product
from agentmall.retrieval.embedding import ROOT, identity, validate_vectors
from agentmall.retrieval.models import KnowledgeChunk, KnowledgeDocument, ProductSearch
from agentmall.retrieval.tokenize import TOKENIZER_VERSION, document_tokens, tokens

# Product document vocabulary has its own identity. Policy indices retain their
# existing tokenizer identity; old product indices require an explicit rebuild.
PRODUCT_INDEX_VERSION = TOKENIZER_VERSION + ":catalog-zh-v3"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def product_text(product):
    category = product.category
    if category in CATEGORY_LABELS:
        category += "\n" + CATEGORY_LABELS[category] + "\n" + " ".join(CATEGORY_ALIASES[category])
    return f"{product.name}\n{category}\n{product.description}\n" + json.dumps(
        product.attributes, ensure_ascii=False, sort_keys=True
    )


def load_policies():
    return [json.loads(p.read_text()) for p in sorted((ROOT / "fixtures/policies").glob("*.json"))]


async def encode(encoder, texts):
    identity(encoder)
    vectors = await asyncio.to_thread(encoder.encode, texts)
    return validate_vectors(encoder, vectors, len(texts))


def indexed(text, vector, encoder):
    return dict(
        search_tsv=func.to_tsvector("simple", document_tokens(text)),
        embedding=vector,
        embedding_model=encoder.model_id,
        embedding_revision=encoder.revision,
        tokenizer_version=TOKENIZER_VERSION,
    )


async def index_products(session, store_id, encoder):
    identity(encoder)
    # Writers use product row locks too: version/text cannot change mid-build.
    products = list(
        await session.scalars(
            select(Product)
            .where(Product.store_id == store_id)
            .order_by(Product.id)
            .with_for_update()
        )
    )
    texts = [product_text(p) for p in products]
    vectors = await encode(encoder, texts)
    async with session.begin_nested():
        for product, text, vector in zip(products, texts, vectors, strict=True):
            values = dict(
                product_id=product.id,
                source_version=product.catalog_version,
                content_hash=digest(text),
                **indexed(text, vector, encoder),
            )
            values["tokenizer_version"] = PRODUCT_INDEX_VERSION
            statement = insert(ProductSearch).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["product_id"],
                    set_={k: v for k, v in values.items() if k != "product_id"},
                )
            )
    return len(products)


async def index_policies(session, documents, encoder):
    identity(encoder)
    prepared = []
    for document in documents:
        fields = {k: v for k, v in document.items() if k != "sections"}
        fields["id"], fields["store_id"] = UUID(fields["id"]), UUID(fields["store_id"])
        fields["content_hash"] = digest(document)
        for key in ("valid_from", "valid_to"):
            fields[key] = datetime.fromisoformat(fields[key]) if fields.get(key) else None
        if not document["sections"] or len({s["id"] for s in document["sections"]}) != len(
            document["sections"]
        ):
            raise ValueError("Policy must have unique nonempty sections")
        for section in document["sections"]:
            if not tokens(section["text"]):
                raise ValueError("Policy section has no searchable content")
        prepared.append((fields, document["sections"]))
    texts = [f"{fields['title']}\n{s['text']}" for fields, sections in prepared for s in sections]
    vectors = iter(await encode(encoder, texts))
    async with session.begin_nested():
        for fields, sections in prepared:
            await session.execute(
                insert(KnowledgeDocument).values(**fields).on_conflict_do_nothing()
            )
            existing = await session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == fields["id"])
                .with_for_update()
            )
            if existing is None or existing.content_hash != fields["content_hash"]:
                raise ValueError("Immutable policy source conflict; create a new version")
            for section in sections:
                content = f"{fields['title']}\n{section['text']}"
                values = dict(
                    id=uuid5(fields["id"], section["id"]),
                    document_id=fields["id"],
                    section_id=section["id"],
                    text=section["text"],
                    token_count=len(tokens(content)),
                    **indexed(content, next(vectors), encoder),
                )
                statement = insert(KnowledgeChunk).values(**values)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["id"],
                        set_={
                            k: v
                            for k, v in values.items()
                            if k not in {"id", "document_id", "section_id", "text"}
                        },
                    )
                )
    return len(texts)
