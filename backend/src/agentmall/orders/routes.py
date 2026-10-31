from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from agentmall.actions.routes import Key
from agentmall.actions.schemas import ActionReceipt
from agentmall.identity.routes import Actor
from agentmall.orders.schemas import ExecuteOrder, OrderDTO, OrderFilters, OrderPage
from agentmall.orders.service import execute_confirmed_action, get_order, list_orders

router = APIRouter()


@router.post("/orders", response_model=ActionReceipt)
async def execute(
    request: Request, response: Response, actor: Actor, payload: ExecuteOrder, key: Key
):
    async with request.app.state.sessions.begin() as session:
        receipt, created = await execute_confirmed_action(
            session,
            actor,
            payload.proposal_id,
            payload.confirmation_id,
            key,
            expected_action="CHECKOUT",
        )
    response.status_code = 201 if created else 200
    return receipt


@router.get("/orders", response_model=OrderPage)
async def orders(request: Request, actor: Actor, filters: Annotated[OrderFilters, Query()]):
    async with request.app.state.sessions.begin() as session:
        return await list_orders(session, actor, filters)


@router.get("/orders/{order_id}", response_model=OrderDTO)
async def order(request: Request, actor: Actor, order_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await get_order(session, actor, order_id)
