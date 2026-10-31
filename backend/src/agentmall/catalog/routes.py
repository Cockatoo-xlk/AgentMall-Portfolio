from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from agentmall.catalog.schemas import ProductDTO, ProductFilters, ProductPage
from agentmall.catalog.service import get_product, search_products
from agentmall.identity.service import ActorContext

router = APIRouter()


def storefront(request: Request):
    return ActorContext(None, "public", request.app.state.settings.storefront_id)


@router.get("/products", response_model=ProductPage)
async def products(request: Request, filters: Annotated[ProductFilters, Query()]):
    async with request.app.state.sessions.begin() as session:
        return await search_products(session, storefront(request), filters)


@router.get("/products/{product_id}", response_model=ProductDTO)
async def product(request: Request, product_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await get_product(session, storefront(request), product_id)
