from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from agentmall.cart.schemas import CartDTO, DeleteItem, NoQuery, SetQuantity
from agentmall.cart.service import get_cart, set_cart_quantity
from agentmall.identity.routes import Actor

router = APIRouter()
EmptyQuery = Annotated[NoQuery, Query()]


@router.get("/cart", response_model=CartDTO)
async def cart(request: Request, actor: Actor, query: EmptyQuery):
    async with request.app.state.sessions.begin() as session:
        result = await get_cart(session, actor)
    return result


@router.put("/cart/items/{product_id}", response_model=CartDTO)
async def put_item(
    request: Request, actor: Actor, product_id: UUID, payload: SetQuantity, query: EmptyQuery
):
    async with request.app.state.sessions.begin() as session:
        result = await set_cart_quantity(
            session, actor, product_id, payload.quantity, payload.expected_version
        )
    return result


@router.delete("/cart/items/{product_id}", response_model=CartDTO)
async def delete_item(
    request: Request, actor: Actor, product_id: UUID, payload: DeleteItem, query: EmptyQuery
):
    async with request.app.state.sessions.begin() as session:
        result = await set_cart_quantity(session, actor, product_id, 0, payload.expected_version)
    return result
