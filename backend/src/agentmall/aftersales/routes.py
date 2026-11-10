from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from agentmall.actions.routes import Key
from agentmall.actions.schemas import ProposalDTO
from agentmall.aftersales import service
from agentmall.aftersales.schemas import (
    CaseActionRequest,
    CaseDTO,
    CaseFilters,
    CasePage,
    EligibilityResult,
    ReasonCode,
    ReceiveRequest,
    RefundReceipt,
    ReturnReceipt,
    ReturnRequest,
    ReviewRequest,
)
from agentmall.identity.routes import Actor
from agentmall.orders.schemas import ExecuteOrder
from agentmall.orders.service import execute_confirmed_action

router = APIRouter()


@router.get("/orders/{order_id}/after-sales-eligibility", response_model=EligibilityResult)
async def eligibility(
    request: Request, actor: Actor, order_id: UUID, reason_code: ReasonCode = "QUALITY_ISSUE"
):
    async with request.app.state.sessions.begin() as session:
        return await service.check_eligibility(session, actor, order_id, reason_code)


@router.post("/after-sales/proposals", response_model=ProposalDTO)
async def return_proposal(
    request: Request, response: Response, actor: Actor, payload: ReturnRequest, key: Key
):
    async with request.app.state.sessions.begin() as session:
        result, created = await service.prepare_action(
            session, actor, payload.order_id, "RETURN_REQUEST", payload, key
        )
    response.status_code = 201 if created else 200
    return result


@router.post("/after-sales", response_model=ReturnReceipt)
async def submit_return(
    request: Request, response: Response, actor: Actor, payload: ExecuteOrder, key: Key
):
    async with request.app.state.sessions.begin() as session:
        result, created = await execute_confirmed_action(
            session,
            actor,
            payload.proposal_id,
            payload.confirmation_id,
            key,
            expected_action="RETURN_REQUEST",
        )
    response.status_code = 201 if created else 200
    return result


@router.get("/after-sales/{case_id}", response_model=CaseDTO)
async def get_case(request: Request, actor: Actor, case_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await service.get_case(session, actor, case_id)


@router.post("/after-sales/{case_id}/cancel-proposals", response_model=ProposalDTO)
async def cancel_proposal(
    request: Request,
    response: Response,
    actor: Actor,
    case_id: UUID,
    payload: CaseActionRequest,
    key: Key,
):
    async with request.app.state.sessions.begin() as session:
        result, created = await service.prepare_action(
            session, actor, case_id, "RETURN_CANCEL", payload, key
        )
    response.status_code = 201 if created else 200
    return result


@router.post("/after-sales/{case_id}/cancel", response_model=ReturnReceipt)
async def cancel(request: Request, actor: Actor, case_id: UUID, payload: ExecuteOrder, key: Key):
    async with request.app.state.sessions.begin() as session:
        result, _ = await execute_confirmed_action(
            session,
            actor,
            payload.proposal_id,
            payload.confirmation_id,
            key,
            expected_action="RETURN_CANCEL",
            case_id=case_id,
        )
    return result


@router.get("/merchant/after-sales", response_model=CasePage)
async def merchant_cases(request: Request, actor: Actor, filters: Annotated[CaseFilters, Query()]):
    async with request.app.state.sessions.begin() as session:
        return await service.list_merchant_cases(session, actor, filters)


@router.get("/merchant/after-sales/{case_id}", response_model=CaseDTO)
async def merchant_case(request: Request, actor: Actor, case_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await service.get_case(session, actor, case_id, merchant=True)


@router.post("/merchant/after-sales/{case_id}/review", response_model=CaseDTO)
async def review(request: Request, actor: Actor, case_id: UUID, payload: ReviewRequest):
    async with request.app.state.sessions.begin() as session:
        return await service.review_case(session, actor, case_id, **payload.model_dump())


@router.post("/merchant/after-sales/{case_id}/receive", response_model=CaseDTO)
async def receive(request: Request, actor: Actor, case_id: UUID, payload: ReceiveRequest):
    async with request.app.state.sessions.begin() as session:
        return await service.receive_case(session, actor, case_id, payload.expected_version)


@router.post("/merchant/after-sales/{case_id}/refund-proposals", response_model=ProposalDTO)
async def refund_proposal(
    request: Request,
    response: Response,
    actor: Actor,
    case_id: UUID,
    payload: CaseActionRequest,
    key: Key,
):
    async with request.app.state.sessions.begin() as session:
        result, created = await service.prepare_action(
            session, actor, case_id, "MOCK_REFUND", payload, key
        )
    response.status_code = 201 if created else 200
    return result


@router.post("/merchant/after-sales/{case_id}/refund", response_model=RefundReceipt)
async def refund(
    request: Request,
    response: Response,
    actor: Actor,
    case_id: UUID,
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
            expected_action="MOCK_REFUND",
            case_id=case_id,
        )
    response.status_code = 201 if created else 200
    return result
