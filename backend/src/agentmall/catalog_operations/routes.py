"""Authenticated merchant catalog operations; imports accept data, never local paths."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import ValidationError

from agentmall.catalog.models import Product
from agentmall.catalog_operations import service
from agentmall.catalog_operations.models import CatalogImport, CatalogIndexJob, ProductDraft
from agentmall.catalog_operations.schemas import (
    Approve,
    Command,
    DraftCreate,
    DraftEdit,
    Filters,
    ImportRequest,
    Reject,
    VersionCommand,
)
from agentmall.identity.routes import Actor
from agentmall.identity.service import require_merchant
from agentmall.infra.errors import DomainError

router = APIRouter(prefix="/merchant/catalog")


@router.get("/meta")
async def meta(request: Request, actor: Actor):
    require_merchant(actor)
    encoder = request.app.state.retrieval_encoder
    return {
        "parser_mode": request.app.state.catalog_parser.mode,
        "embedding_model": getattr(encoder, "model_id", None),
        "indexing": "EXPLICIT_BOUNDED_RETRY",
        "max_import_bytes": 131072,
        "max_rows": 50,
    }


@router.get("/commands/{request_id}")
async def receipt(request: Request, actor: Actor, request_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await service.command_receipt(session, actor, request_id)


async def listing(request, actor, filters, model):
    async with request.app.state.sessions.begin() as session:
        rows, cursor = await service.list_rows(session, actor, model, filters)
        items = []
        for row in rows:
            if model is Product:
                items.append(
                    await service.product_view(session, row, request.app.state.retrieval_encoder)
                )
            elif model is ProductDraft:
                items.append(service.draft_view(row))
            elif model is CatalogImport:
                items.append(service.import_view(row))
            else:
                items.append(await service.job_view(session, actor, row))
        return {"items": items, "next_cursor": cursor}


@router.get("/products")
async def products(request: Request, actor: Actor, filters: Annotated[Filters, Query()]):
    return await listing(request, actor, filters, Product)


@router.get("/drafts")
async def drafts(request: Request, actor: Actor, filters: Annotated[Filters, Query()]):
    return await listing(request, actor, filters, ProductDraft)


@router.get("/imports")
async def imports(request: Request, actor: Actor, filters: Annotated[Filters, Query()]):
    return await listing(request, actor, filters, CatalogImport)


@router.get("/index-jobs")
async def jobs(request: Request, actor: Actor, filters: Annotated[Filters, Query()]):
    return await listing(request, actor, filters, CatalogIndexJob)


@router.get("/drafts/{ident}")
async def draft(request: Request, actor: Actor, ident: UUID):
    async with request.app.state.sessions.begin() as session:
        return service.draft_view(await service.owned(session, ProductDraft, actor, ident))


@router.post("/imports")
async def importing(request: Request, response: Response, actor: Actor):
    require_merchant(actor)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 524288:
            raise DomainError(413, "IMPORT_TOO_LARGE", "导入请求超过大小限制")

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out

    try:
        payload = ImportRequest.model_validate(json.loads(body, object_pairs_hook=unique))
    except (ValueError, ValidationError, RecursionError):
        raise DomainError(422, "INVALID_IMPORT", "导入格式不符合契约") from None
    value, created = await service.import_products(request.app, actor, payload)
    response.status_code = 201 if created else 200
    return value


@router.post("/drafts")
async def creating(request: Request, actor: Actor, payload: DraftCreate):
    value, _ = await service.create_draft(request.app, actor, payload)
    return value


@router.post("/products/{ident}/draft")
async def revising(request: Request, actor: Actor, ident: UUID, payload: VersionCommand):
    value, _ = await service.create_draft(request.app, actor, payload, ident)
    return value


@router.patch("/drafts/{ident}")
async def editing(request: Request, actor: Actor, ident: UUID, payload: DraftEdit):
    value, _ = await service.change_draft(request.app, actor, ident, "edit", payload)
    return value


@router.post("/drafts/{ident}/extract")
async def extracting(request: Request, actor: Actor, ident: UUID, payload: VersionCommand):
    value, _ = await service.change_draft(request.app, actor, ident, "extract", payload)
    return value


@router.post("/drafts/{ident}/submit")
async def submitting(request: Request, actor: Actor, ident: UUID, payload: VersionCommand):
    value, _ = await service.change_draft(request.app, actor, ident, "submit", payload)
    return value


@router.post("/drafts/{ident}/approve")
async def approving(request: Request, actor: Actor, ident: UUID, payload: Approve):
    value, _ = await service.change_draft(request.app, actor, ident, "approve", payload)
    return value


@router.post("/drafts/{ident}/reject")
async def rejecting(request: Request, actor: Actor, ident: UUID, payload: Reject):
    value, _ = await service.change_draft(request.app, actor, ident, "reject", payload)
    return value


@router.post("/drafts/{ident}/publish")
async def publishing(request: Request, actor: Actor, ident: UUID, payload: VersionCommand):
    value, _ = await service.change_draft(request.app, actor, ident, "publish", payload)
    return value


@router.post("/products/{ident}/deactivate")
async def deactivating(request: Request, actor: Actor, ident: UUID, payload: VersionCommand):
    value, _ = await service.deactivate(request.app, actor, ident, payload)
    return value


@router.post("/index-jobs/{ident}/run")
async def indexing(request: Request, actor: Actor, ident: UUID, payload: Command):
    value, _ = await service.run_index(request.app, actor, ident, payload)
    return value
