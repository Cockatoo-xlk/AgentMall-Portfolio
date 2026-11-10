"""Merchant-only commands. Draft review and index work never execute commerce actions."""

import asyncio
from uuid import uuid4, uuid5

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from agentmall.actions.service import database_now, payload_hash
from agentmall.catalog.models import Product
from agentmall.catalog_operations.importing import parse_rows
from agentmall.catalog_operations.models import (
    CatalogCommand,
    CatalogImport,
    CatalogIndexJob,
    ProductDraft,
)
from agentmall.catalog_operations.parser import verify_extraction
from agentmall.catalog_operations.schemas import ProductData
from agentmall.identity.service import require_merchant
from agentmall.infra.errors import DomainError, not_found
from agentmall.retrieval.ingest import PRODUCT_INDEX_VERSION, digest, index_product, product_text
from agentmall.retrieval.models import ProductSearch


def conflict(code="STALE_VERSION"):
    return DomainError(409, code, "状态或版本已变化，请核对服务端记录后重新决定")


async def owned(session, model, actor, ident, lock=False):
    require_merchant(actor)
    query = select(model).where(model.id == ident, model.store_id == actor.store_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise not_found()
    return row


async def command(app, actor, operation, payload, fn):
    require_merchant(actor)
    digest_value = payload_hash({"operation": operation, "body": payload.model_dump(mode="json")})
    async with app.state.sessions.begin() as session:
        await session.execute(
            insert(CatalogCommand)
            .values(
                id=uuid4(),
                store_id=actor.store_id,
                actor_id=actor.user_id,
                request_id=payload.request_id,
                digest=digest_value,
            )
            .on_conflict_do_nothing(constraint="uq_catalog_command_request")
        )
        receipt = await session.scalar(
            select(CatalogCommand)
            .where(
                CatalogCommand.store_id == actor.store_id,
                CatalogCommand.actor_id == actor.user_id,
                CatalogCommand.request_id == payload.request_id,
            )
            .with_for_update()
        )
        if receipt.digest != digest_value:
            raise conflict("IDEMPOTENCY_CONFLICT")
        if receipt.result is not None:
            return receipt.result, False
        value = await fn(session)
        await session.flush()
        receipt.result = jsonable_encoder(value)
        return receipt.result, True


async def command_receipt(session, actor, request_id):
    require_merchant(actor)
    row = await session.scalar(
        select(CatalogCommand).where(
            CatalogCommand.store_id == actor.store_id,
            CatalogCommand.actor_id == actor.user_id,
            CatalogCommand.request_id == request_id,
        )
    )
    if row is None or row.result is None:
        raise not_found()
    return {"request_id": request_id, "result": row.result}


def draft_view(d):
    return {
        key: getattr(d, key)
        for key in [
            "id",
            "status",
            "version",
            "data",
            "source",
            "extraction",
            "extraction_attempts",
            "target_product_id",
            "target_version",
            "approved_by",
            "approved_at",
            "published_product_id",
            "index_job_id",
            "history",
            "created_at",
        ]
    }


def import_view(j):
    return {
        key: getattr(j, key)
        for key in [
            "id",
            "status",
            "format",
            "source_hash",
            "parser_mode",
            "draft_ids",
            "errors",
            "created_at",
        ]
    }


async def job_view(session, actor, j):
    product = await owned(session, Product, actor, j.product_id)
    return {
        **{
            k: getattr(j, k)
            for k in [
                "id",
                "product_id",
                "requested_version",
                "status",
                "attempts",
                "error_code",
                "created_at",
            ]
        },
        "current_version": product.catalog_version,
        "effective_status": j.status
        if product.active and product.catalog_version == j.requested_version
        else "STALE",
    }


async def product_view(session, p, encoder=None):
    search = await session.get(ProductSearch, p.id)
    indexed = bool(
        search
        and encoder is not None
        and search.embedding_model == encoder.model_id
        and search.embedding_revision == encoder.revision
        and search.source_version == p.catalog_version
        and search.content_hash == digest(product_text(p))
        and search.tokenizer_version == PRODUCT_INDEX_VERSION
    )
    return {
        **{
            k: getattr(p, k)
            for k in [
                "id",
                "name",
                "category",
                "description",
                "attributes",
                "price_cents",
                "on_hand",
                "reserved",
                "active",
                "catalog_version",
            ]
        },
        "available": p.on_hand - p.reserved,
        "index_status": "INACTIVE"
        if not p.active
        else "INDEXED_CURRENT"
        if indexed
        else "NOT_INDEXED_CURRENT",
    }


async def list_rows(session, actor, model, filters):
    require_merchant(actor)
    query = select(model).where(model.store_id == actor.store_id)
    if filters.cursor:
        query = query.where(model.id > filters.cursor)
    if filters.status:
        if model is Product:
            if filters.status not in ["ACTIVE", "INACTIVE"]:
                raise DomainError(422, "INVALID_STATUS", "无效状态")
            query = query.where(Product.active.is_(filters.status == "ACTIVE"))
        else:
            query = query.where(model.status == filters.status)
    if filters.category:
        if model is not Product:
            raise DomainError(422, "INVALID_FILTER", "此列表不支持品类筛选")
        query = query.where(Product.category == filters.category)
    rows = list(await session.scalars(query.order_by(model.id).limit(filters.limit + 1)))
    return rows[: filters.limit], rows[filters.limit - 1].id if len(rows) > filters.limit else None


async def bump(session, d, actor, state):
    d.status = state
    d.version += 1
    d.history = [
        *d.history,
        {
            "state": state,
            "version": d.version,
            "actor_id": str(actor.user_id),
            "at": (await database_now(session)).isoformat(),
            "data_hash": payload_hash(d.data),
        },
    ]


async def assist(d, parser):
    if d.extraction_attempts >= 3:
        raise conflict("EXTRACTION_RETRY_EXHAUSTED")
    d.extraction_attempts += 1
    try:
        async with asyncio.timeout(2):
            parsed = verify_extraction(
                d.data["description"], await parser.parse(d.data["description"])
            )
        values = dict(d.data)
        attributes = dict(values["attributes"])
        conflicts = []
        if values["category"] is None:
            values["category"] = parsed.category
        elif parsed.category is not None and values["category"] != parsed.category:
            conflicts.append("category")
        from agentmall.catalog_operations.schemas import ATTRIBUTES

        allowed = set(ATTRIBUTES.get(values["category"], "").split())
        evidence = []
        for spec in parsed.specs:
            if spec.field not in allowed or (
                spec.field in attributes and attributes[spec.field] != spec.value
            ):
                conflicts.append(spec.field)
                continue
            attributes[spec.field] = spec.value
            evidence.append(
                {
                    **spec.model_dump(),
                    "start": d.data["description"].index(spec.quote),
                    "end": d.data["description"].index(spec.quote) + len(spec.quote),
                }
            )
        values["attributes"] = attributes
        d.data = ProductData.model_validate(values).model_dump(mode="json")
        d.extraction = {
            "mode": parser.mode,
            "status": "SUGGESTED",
            "evidence": evidence,
            "category_quote": parsed.category_quote,
            "uncertain": sorted(set(parsed.uncertain + conflicts)),
            "source_hash": payload_hash(d.data["description"]),
        }
        return True
    except Exception:
        # No raw SDK/transport/exception prose is exposed or persisted.
        d.extraction = {
            "mode": parser.mode,
            "status": "FAILED",
            "error_code": "MODEL_DISABLED"
            if parser.mode == "MODEL_DISABLED"
            else "EXTRACTION_INVALID_OR_UNAVAILABLE",
            "uncertain": ["category"] if d.data["category"] is None else [],
        }
        return False


async def import_products(app, actor, payload):
    rows, errors = parse_rows(payload)

    async def apply(session):
        job = CatalogImport(
            id=uuid5(payload.request_id, str(actor.user_id) + ":" + str(actor.store_id)),
            store_id=actor.store_id,
            actor_id=actor.user_id,
            request_id=payload.request_id,
            status="COMPLETED",
            format=payload.format,
            source_hash=payload_hash(payload.content),
            parser_mode=app.state.catalog_parser.mode,
            draft_ids=[],
            errors=errors,
        )
        session.add(job)
        await session.flush()
        identifiers = []
        issues = list(errors)
        for rank, data, raw in rows:
            draft = ProductDraft(
                id=uuid5(job.id, f"row:{rank}"),
                store_id=actor.store_id,
                actor_id=actor.user_id,
                import_id=job.id,
                status="DRAFT",
                version=1,
                data=data.model_dump(mode="json"),
                source={
                    "kind": "IMPORT",
                    "row": rank,
                    "original": raw,
                    "source_hash": payload_hash(raw),
                },
                extraction={},
                extraction_attempts=0,
                history=[],
            )
            if payload.assist and not await assist(draft, app.state.catalog_parser):
                issues.append(
                    {"row": rank, "code": "AI_ASSIST_UNAVAILABLE", "draft_id": str(draft.id)}
                )
            session.add(draft)
            identifiers.append(str(draft.id))
        job.draft_ids = identifiers
        job.errors = issues
        job.status = (
            "PARTIAL" if issues and identifiers else "FAILED" if not identifiers else "COMPLETED"
        )
        await session.flush()
        return import_view(job)

    return await command(app, actor, "import", payload, apply)


async def create_draft(app, actor, payload, target_id=None):
    async def apply(session):
        target = await owned(session, Product, actor, target_id, True) if target_id else None
        if target and target.catalog_version != payload.expected_version:
            raise conflict()
        data = (
            ProductData(
                name=target.name,
                category=target.category,
                description=target.description,
                attributes=target.attributes,
                price_cents=target.price_cents,
                on_hand=target.on_hand,
            )
            if target
            else payload.data
        )
        d = ProductDraft(
            id=uuid4(),
            store_id=actor.store_id,
            actor_id=actor.user_id,
            status="DRAFT",
            version=1,
            data=data.model_dump(mode="json"),
            source={
                "kind": "PRODUCT_REVISION",
                "product_id": str(target.id),
                "catalog_version": target.catalog_version,
                "base_on_hand": target.on_hand,
                "original": data.model_dump(mode="json"),
            }
            if target
            else {"kind": "MERCHANT_INPUT", "original": data.model_dump(mode="json")},
            target_product_id=target.id if target else None,
            target_version=target.catalog_version if target else None,
            extraction={},
            extraction_attempts=0,
            history=[],
        )
        session.add(d)
        await session.flush()
        return draft_view(d)

    return await command(
        app, actor, "revise:" + str(target_id) if target_id else "draft-create", payload, apply
    )


async def change_draft(app, actor, ident, operation, payload):
    async def apply(session):
        d = await owned(session, ProductDraft, actor, ident, True)
        if d.version != payload.expected_version:
            raise conflict()
        if d.status == "PUBLISHED":
            raise conflict("PUBLISHED_DRAFT_IMMUTABLE")
        if operation in ["edit", "extract"]:
            old_description = d.data["description"]
            if operation == "edit":
                d.data = payload.data.model_dump(mode="json")
                if d.data["description"] != old_description:
                    d.extraction_attempts = 0
                d.extraction = {
                    "status": "MERCHANT_EDITED",
                    "mode": app.state.catalog_parser.mode,
                    "uncertain": [],
                }
            else:
                await assist(d, app.state.catalog_parser)
            d.approved_hash = d.approved_version = d.approved_by = d.approved_at = None
            await bump(session, d, actor, "DRAFT")
        elif operation == "submit":
            if d.status not in ["DRAFT", "REJECTED"]:
                raise conflict("INVALID_DRAFT_TRANSITION")
            data = ProductData.model_validate(d.data)
            if data.category is None:
                raise conflict("CATEGORY_CONFIRMATION_REQUIRED")
            await bump(session, d, actor, "READY_FOR_REVIEW")
        elif operation in ["approve", "reject"]:
            if d.status != "READY_FOR_REVIEW":
                raise conflict("INVALID_DRAFT_TRANSITION")
            await bump(session, d, actor, "APPROVED" if operation == "approve" else "REJECTED")
            if operation == "approve":
                d.approved_hash = payload_hash(d.data)
                d.approved_version = d.version
                d.approved_by = actor.user_id
                d.approved_at = await database_now(session)
            else:
                d.history = [*d.history, {"reason": payload.reason, "actor_id": str(actor.user_id)}]
        elif operation == "publish":
            if (
                d.status != "APPROVED"
                or d.approved_version != d.version
                or d.approved_hash != payload_hash(d.data)
            ):
                raise conflict("REVIEW_REQUIRED")
            data = ProductData.model_validate(d.data)
            if data.category is None:
                raise conflict("CATEGORY_CONFIRMATION_REQUIRED")
            if d.target_product_id:
                product = await owned(session, Product, actor, d.target_product_id, True)
                if product.catalog_version != d.target_version:
                    raise conflict()
                # Payment consumes stock without changing catalog_version. Never
                # restore sold stock from a stale draft, even if price is unchanged.
                if product.on_hand != d.source.get("base_on_hand"):
                    raise conflict("STOCK_CHANGED")
                if data.on_hand < product.reserved:
                    raise conflict("RESERVED_STOCK_PROTECTED")
                for key, value in data.model_dump().items():
                    setattr(product, key, value)
                product.active = True
                product.catalog_version += 1
            else:
                product = Product(
                    id=uuid5(d.id, "product"),
                    store_id=actor.store_id,
                    **data.model_dump(),
                    active=True,
                    reserved=0,
                    catalog_version=1,
                )
                session.add(product)
            await session.flush()
            job = CatalogIndexJob(
                id=uuid5(d.id, "index:" + str(product.catalog_version)),
                store_id=actor.store_id,
                product_id=product.id,
                requested_version=product.catalog_version,
                status="PENDING",
                attempts=0,
            )
            session.add(job)
            d.published_product_id = product.id
            d.index_job_id = job.id
            await bump(session, d, actor, "PUBLISHED")
        else:
            raise DomainError(422, "INVALID_OPERATION", "无效操作")
        await session.flush()
        return draft_view(d)

    return await command(app, actor, operation + ":" + str(ident), payload, apply)


async def deactivate(app, actor, ident, payload):
    async def apply(session):
        product = await owned(session, Product, actor, ident, True)
        if product.catalog_version != payload.expected_version:
            raise conflict()
        if not product.active:
            raise conflict("ALREADY_INACTIVE")
        product.active = False
        product.catalog_version += 1
        await session.flush()
        return await product_view(session, product, app.state.retrieval_encoder)

    return await command(app, actor, "deactivate:" + str(ident), payload, apply)


async def run_index(app, actor, ident, payload):
    async def apply(session):
        job = await owned(session, CatalogIndexJob, actor, ident, True)
        product = await owned(session, Product, actor, job.product_id, True)
        if product.catalog_version != job.requested_version or not product.active:
            job.status = "STALE"
            job.error_code = "PRODUCT_VERSION_CHANGED"
        elif job.status == "SUCCEEDED":
            pass
        else:
            if job.attempts >= 3:
                raise conflict("INDEX_RETRY_EXHAUSTED")
            job.attempts += 1
            try:
                if app.state.retrieval_encoder is None:
                    raise ValueError("encoder unavailable")
                async with session.begin_nested():
                    async with asyncio.timeout(5):
                        await index_product(session, product, app.state.retrieval_encoder)
                job.status = "SUCCEEDED"
                job.error_code = None
            except Exception:
                job.status = "FAILED"
                job.error_code = (
                    "EMBEDDING_UNAVAILABLE"
                    if app.state.retrieval_encoder is None
                    else "INDEX_BUILD_FAILED"
                )
        await session.flush()
        return await job_view(session, actor, job)

    return await command(app, actor, "index:" + str(ident), payload, apply)
