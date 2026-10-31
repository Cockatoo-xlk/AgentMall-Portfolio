from uuid import UUID

from fastapi import APIRouter, Request, Response

from agentmall.actions.routes import Key
from agentmall.actions.schemas import CancelReceipt, OrderActionRequest, PaymentReceipt, ProposalDTO
from agentmall.identity.routes import Actor
from agentmall.orders.lifecycle import advance_shipment, shipment
from agentmall.orders.schemas import ExecuteOrder, OrderDTO, ShipmentDTO, ShipmentRequest
from agentmall.orders.service import execute_confirmed_action
from agentmall.payments.service import prepare_order_action

router = APIRouter()


@router.post("/orders/{order_id}/payment-proposals", response_model=ProposalDTO)
async def payment_proposal(
    request: Request,
    response: Response,
    actor: Actor,
    order_id: UUID,
    payload: OrderActionRequest,
    key: Key,
):
    async with request.app.state.sessions.begin() as session:
        result, created = await prepare_order_action(
            session, actor, order_id, "MOCK_PAYMENT", payload, key
        )
    response.status_code = 201 if created else 200
    return result


@router.post("/orders/{order_id}/cancel-proposals", response_model=ProposalDTO)
async def cancel_proposal(
    request: Request,
    response: Response,
    actor: Actor,
    order_id: UUID,
    payload: OrderActionRequest,
    key: Key,
):
    async with request.app.state.sessions.begin() as session:
        result, created = await prepare_order_action(
            session, actor, order_id, "CANCEL_ORDER", payload, key
        )
    response.status_code = 201 if created else 200
    return result


@router.post("/orders/{order_id}/mock-payments", response_model=PaymentReceipt)
async def mock_payment(
    request: Request,
    response: Response,
    actor: Actor,
    order_id: UUID,
    payload: ExecuteOrder,
    key: Key,
):
    async with request.app.state.sessions.begin() as session:
        result, created = await execute_confirmed_action(
            session,
            actor,
            payload.proposal_id,
            payload.confirmation_id,
            key,
            expected_action="MOCK_PAYMENT",
            order_id=order_id,
            adapter=request.app.state.mock_payment_adapter,
        )
    response.status_code = 201 if created and result.status == "SUCCEEDED" else 200
    return result


@router.post("/orders/{order_id}/cancel", response_model=CancelReceipt)
async def cancel(request: Request, actor: Actor, order_id: UUID, payload: ExecuteOrder, key: Key):
    async with request.app.state.sessions.begin() as session:
        result, _ = await execute_confirmed_action(
            session,
            actor,
            payload.proposal_id,
            payload.confirmation_id,
            key,
            expected_action="CANCEL_ORDER",
            order_id=order_id,
        )
    return result


@router.get("/orders/{order_id}/shipment", response_model=ShipmentDTO)
async def get_shipment(request: Request, actor: Actor, order_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await shipment(session, actor, order_id)


@router.post("/merchant/orders/{order_id}/ship", response_model=OrderDTO)
async def ship(request: Request, actor: Actor, order_id: UUID, payload: ShipmentRequest):
    async with request.app.state.sessions.begin() as session:
        return await advance_shipment(session, actor, order_id, "ship", payload.expected_version)


@router.post("/merchant/orders/{order_id}/deliver", response_model=OrderDTO)
async def deliver(request: Request, actor: Actor, order_id: UUID, payload: ShipmentRequest):
    async with request.app.state.sessions.begin() as session:
        return await advance_shipment(session, actor, order_id, "deliver", payload.expected_version)
