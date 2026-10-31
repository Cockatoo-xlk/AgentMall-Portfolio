from uuid import UUID

from fastapi import APIRouter, Request, Response

from agentmall.actions.routes import Key
from agentmall.identity.routes import Actor
from agentmall.support.schemas import ClaimRequest, ResolveRequest, TicketDTO, TicketRequest
from agentmall.support.service import (
    claim_ticket,
    create_support_ticket,
    get_ticket,
    resolve_ticket,
)

router = APIRouter()


@router.post("/support-tickets", response_model=TicketDTO)
async def create(
    request: Request, response: Response, actor: Actor, payload: TicketRequest, key: Key
):
    async with request.app.state.sessions.begin() as session:
        dto, created = await create_support_ticket(
            session, actor, **payload.model_dump(), idempotency_key=key
        )
    response.status_code = 201 if created else 200
    return dto


@router.get("/support-tickets/{ticket_id}", response_model=TicketDTO)
async def ticket(request: Request, actor: Actor, ticket_id: UUID):
    async with request.app.state.sessions.begin() as session:
        return await get_ticket(session, actor, ticket_id)


@router.post("/merchant/tickets/{ticket_id}/resolve", response_model=TicketDTO)
async def resolve(request: Request, actor: Actor, ticket_id: UUID, payload: ResolveRequest):
    async with request.app.state.sessions.begin() as session:
        return await resolve_ticket(session, actor, ticket_id, **payload.model_dump())


@router.post("/merchant/tickets/{ticket_id}/claim", response_model=TicketDTO)
async def claim(request: Request, actor: Actor, ticket_id: UUID, payload: ClaimRequest):
    async with request.app.state.sessions.begin() as session:
        return await claim_ticket(session, actor, ticket_id, payload.expected_version)
