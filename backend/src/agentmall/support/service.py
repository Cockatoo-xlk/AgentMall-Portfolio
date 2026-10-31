"""Scoped human handoff; all ticket writes share the caller's business transaction."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from agentmall.actions.service import claim_key, complete_key, conflict, database_now, payload_hash
from agentmall.aftersales.models import AfterSalesCase
from agentmall.identity.service import require_buyer
from agentmall.infra.audit import BusinessEvent
from agentmall.infra.errors import DomainError, not_found
from agentmall.orders.lifecycle import owned_order
from agentmall.support.models import SupportTicket
from agentmall.support.schemas import ClaimRequest, ResolveRequest, TicketDTO, TicketRequest

DISPUTED_ACTIONS = (
    "RETURN_REQUEST",
    "RETURN_CANCEL",
    "MOCK_REFUND",
    "REVIEW_CASE",
    "RECEIVE_CASE",
)


async def owned_ticket(session, actor, ticket_id, *, merchant=False, lock=False):
    if merchant or actor.role == "merchant":
        if actor.role != "merchant" or actor.user_id is None:
            raise DomainError(403, "FORBIDDEN", "此接口仅供所属店铺商家使用")
    else:
        require_buyer(actor)
    query = select(SupportTicket).where(
        SupportTicket.id == ticket_id, SupportTicket.store_id == actor.store_id
    )
    if actor.role != "merchant":
        query = query.where(SupportTicket.user_id == actor.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    ticket = await session.scalar(query)
    if ticket is None:
        raise not_found()
    return ticket


async def get_ticket(session, actor, ticket_id):
    return TicketDTO.model_validate(await owned_ticket(session, actor, ticket_id))


async def ticket_event(session, ticket, event_type, actor_id, now, previous=None):
    session.add(
        BusinessEvent(
            aggregate_type="support_ticket",
            aggregate_id=ticket.id,
            action_id=None,
            event_type=event_type,
            payload_summary={
                "order_id": str(ticket.order_id) if ticket.order_id else None,
                "case_id": str(ticket.case_id) if ticket.case_id else None,
                "from_status": previous,
                "status": ticket.status,
                "version": ticket.version,
                "actor_id": str(actor_id),
                "resolution": ticket.resolution,
            },
            occurred_at=now,
        )
    )
    await session.flush()


async def create_support_ticket(
    session,
    actor,
    request_id,
    reason,
    summary,
    idempotency_key,
    *,
    order_id=None,
    case_id=None,
    conversation_scope=None,
):
    require_buyer(actor)
    request = TicketRequest(
        request_id=request_id,
        reason=reason,
        summary=summary,
        order_id=order_id,
        case_id=case_id,
        conversation_scope=conversation_scope,
    )
    digest = payload_hash(
        {"schema_version": 1, **request.model_dump(mode="json", exclude_none=True)}
    )
    key, new = await claim_key(session, actor, "create_support_ticket", idempotency_key, digest)
    if not new:
        return await get_ticket(session, actor, UUID(key.result["ticket_id"])), False

    request_scope = (
        SupportTicket.user_id == actor.user_id,
        SupportTicket.store_id == actor.store_id,
        SupportTicket.request_id == request.request_id,
    )
    existing = await session.scalar(select(SupportTicket).where(*request_scope))
    if existing is not None:
        if existing.request_hash != digest:
            raise conflict()
        await complete_key(session, key, {"ticket_id": str(existing.id)})
        return TicketDTO.model_validate(existing), False

    # A case lookup is read-only until its parent order is locked. Every disputed
    # write also takes that order lock, so opening/resolving a pause is serialized.
    if request.case_id is not None:
        case = await session.scalar(
            select(AfterSalesCase).where(
                AfterSalesCase.id == request.case_id,
                AfterSalesCase.user_id == actor.user_id,
                AfterSalesCase.store_id == actor.store_id,
            )
        )
        if case is None:
            raise not_found()
        order_id = case.order_id
    if order_id is not None:
        await owned_order(session, actor, order_id, lock=True)
        if request.case_id is None:
            case_id = await session.scalar(
                select(AfterSalesCase.id).where(
                    AfterSalesCase.order_id == order_id,
                    AfterSalesCase.user_id == actor.user_id,
                    AfterSalesCase.store_id == actor.store_id,
                    AfterSalesCase.status.not_in(("REJECTED", "CANCELLED")),
                )
            )

    now = await database_now(session)
    ticket_id = await session.scalar(
        insert(SupportTicket)
        .values(
            id=uuid4(),
            user_id=actor.user_id,
            store_id=actor.store_id,
            request_id=request.request_id,
            request_hash=digest,
            order_id=order_id,
            case_id=case_id,
            conversation_scope=request.conversation_scope,
            blocked_action_types=list(DISPUTED_ACTIONS) if order_id is not None else [],
            reason=request.reason,
            summary=request.summary,
            status="OPEN",
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_ticket_request")
        .returning(SupportTicket.id)
    )
    created = ticket_id is not None
    ticket = await session.scalar(select(SupportTicket).where(*request_scope))
    if ticket.request_hash != digest:
        raise conflict()
    if created:
        await ticket_event(session, ticket, "TICKET_OPENED", actor.user_id, now)
    await complete_key(session, key, {"ticket_id": str(ticket.id)})
    return TicketDTO.model_validate(ticket), created


async def resolve_ticket(session, actor, ticket_id, expected_version, resolution, summary):
    request = ResolveRequest(
        expected_version=expected_version, resolution=resolution, summary=summary
    )
    ticket = await owned_ticket(session, actor, ticket_id, merchant=True)
    if ticket.order_id is not None:
        await owned_order(session, actor, ticket.order_id, lock=True, merchant=True)
    ticket = await owned_ticket(session, actor, ticket_id, merchant=True, lock=True)
    if ticket.version != request.expected_version:
        raise conflict("STALE_VERSION")
    if ticket.status not in {"OPEN", "IN_PROGRESS"}:
        raise conflict("INVALID_TICKET_STATE")
    previous = ticket.status
    now = await database_now(session)
    ticket.status = "RESOLVED"
    ticket.assigned_to = actor.user_id
    ticket.resolution = request.resolution
    ticket.resolution_summary = request.summary
    ticket.resolved_at = ticket.updated_at = now
    ticket.version += 1
    await session.flush()
    await ticket_event(session, ticket, "TICKET_RESOLVED", actor.user_id, now, previous)
    return TicketDTO.model_validate(ticket)


async def claim_ticket(session, actor, ticket_id, expected_version):
    request = ClaimRequest(expected_version=expected_version)
    ticket = await owned_ticket(session, actor, ticket_id, merchant=True)
    if ticket.order_id is not None:
        await owned_order(session, actor, ticket.order_id, lock=True, merchant=True)
    ticket = await owned_ticket(session, actor, ticket_id, merchant=True, lock=True)
    if ticket.version != request.expected_version:
        raise conflict("STALE_VERSION")
    if ticket.status != "OPEN":
        raise conflict("INVALID_TICKET_STATE")
    now = await database_now(session)
    ticket.status = "IN_PROGRESS"
    ticket.assigned_to = actor.user_id
    ticket.updated_at = now
    ticket.version += 1
    await session.flush()
    await ticket_event(session, ticket, "TICKET_CLAIMED", actor.user_id, now, "OPEN")
    return TicketDTO.model_validate(ticket)


async def check_handoff(session, order_id, action_type):
    """Call after acquiring the verified order lock and before disputed writes."""
    ticket_id = await session.scalar(
        select(SupportTicket.id)
        .where(
            SupportTicket.order_id == order_id,
            SupportTicket.status.in_(("OPEN", "IN_PROGRESS")),
            SupportTicket.blocked_action_types.contains([action_type]),
        )
        .limit(1)
    )
    if ticket_id is not None:
        raise DomainError(409, "HUMAN_HANDOFF_REQUIRED", "相关售后动作已暂停，请等待人工工单处理")
