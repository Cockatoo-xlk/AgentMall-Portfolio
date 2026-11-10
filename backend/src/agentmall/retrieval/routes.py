from typing import Annotated

from fastapi import APIRouter, Query, Request

from agentmall.catalog.routes import storefront
from agentmall.identity.routes import Actor
from agentmall.retrieval.schemas import PolicyQuery, ProductQuery
from agentmall.retrieval.search import retrieve_policies, retrieve_products

router = APIRouter()


@router.get("/retrieval/products")
async def products(request: Request, filters: Annotated[ProductQuery, Query()]):
    async with request.app.state.sessions.begin() as session:
        return {
            "items": await retrieve_products(
                session,
                storefront(request),
                filters.query,
                filters,
                request.app.state.retrieval_encoder,
            )
        }


@router.get("/retrieval/products/reranked")
async def reranked(request: Request, filters: Annotated[ProductQuery, Query()]):
    from sqlalchemy import text

    from agentmall.retrieval.ranking import reranked_products

    async with request.app.state.sessions.begin() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return await reranked_products(
            session,
            storefront(request),
            filters.query,
            filters,
            request.app.state.retrieval_encoder,
            getattr(request.app.state, "retrieval_reranker", None),
            fallback=getattr(request.app.state, "reranker_fallback", False),
        )


@router.get("/knowledge/search")
async def policies(request: Request, actor: Actor, filters: Annotated[PolicyQuery, Query()]):
    async with request.app.state.sessions.begin() as session:
        return {
            "items": await retrieve_policies(
                session,
                actor,
                filters.order_id,
                filters.query,
                filters.mode,
                request.app.state.retrieval_encoder,
            )
        }
