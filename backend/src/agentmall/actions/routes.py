from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request, Response

from agentmall.actions.schemas import (
    CheckoutRequest,
    ConfirmationDTO,
    ConfirmationRequest,
    IdempotencyKey,
    ProposalDTO,
)
from agentmall.actions.service import confirm_proposal, get_proposal, prepare_checkout
from agentmall.identity.routes import Actor

router = APIRouter()
Key = Annotated[IdempotencyKey, Header(alias="Idempotency-Key")]


@router.post("/checkout/proposals", response_model=ProposalDTO)
async def prepare(
    request: Request, response: Response, actor: Actor, payload: CheckoutRequest, key: Key
):
    async with request.app.state.sessions.begin() as session:
        dto, created = await prepare_checkout(
            session, actor, **payload.model_dump(), idempotency_key=key
        )
    response.status_code = 201 if created else 200
    return dto


@router.get("/proposals/{proposal_id}", response_model=ProposalDTO)
async def proposal(request: Request, actor: Actor, proposal_id: UUID):
    async with request.app.state.sessions.begin() as session:
        dto = await get_proposal(session, actor, proposal_id)
    return dto


@router.post("/proposals/{proposal_id}/confirmations", response_model=ConfirmationDTO)
async def confirmation(
    request: Request,
    response: Response,
    actor: Actor,
    proposal_id: UUID,
    payload: ConfirmationRequest,
):
    async with request.app.state.sessions.begin() as session:
        dto, created = await confirm_proposal(session, actor, proposal_id, payload.decision)
    response.status_code = 201 if created else 200
    return dto
