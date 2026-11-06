"""Deterministic aftersales transactions on the existing action ledger."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from agentmall.actions.models import ActionProposal, Confirmation, IdempotencyRequest
from agentmall.actions.service import (
    claim_key,
    complete_key,
    conflict,
    database_now,
    owned_proposal,
    payload_hash,
    proposal_view,
)
from agentmall.aftersales.models import AfterSalesCase, Refund
from agentmall.aftersales.policy import POLICY_WINDOWS, evaluate_eligibility
from agentmall.aftersales.schemas import (
    CaseDTO,
    CasePage,
    RefundPayload,
    RefundReceipt,
    ReturnCancelPayload,
    ReturnPayload,
    ReturnReceipt,
)
from agentmall.identity.service import require_buyer, require_merchant
from agentmall.infra.audit import BusinessEvent
from agentmall.infra.errors import not_found
from agentmall.orders.lifecycle import owned_order
from agentmall.payments.models import Payment
from agentmall.support.models import SupportTicket

PAYLOADS = {
    "RETURN_REQUEST": ReturnPayload,
    "RETURN_CANCEL": ReturnCancelPayload,
    "MOCK_REFUND": RefundPayload,
}


async def owned_case(session, actor, case_id, *, merchant=False, lock=False):
    if merchant:
        require_merchant(actor)
    else:
        require_buyer(actor)
    query = select(AfterSalesCase).where(
        AfterSalesCase.id == case_id,
        AfterSalesCase.store_id == actor.store_id,
    )
    if not merchant:
        query = query.where(AfterSalesCase.user_id == actor.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    case = await session.scalar(query)
    if case is None:
        raise not_found()
    return case


async def get_case(session, actor, case_id, *, merchant=False):
    return CaseDTO.model_validate(await owned_case(session, actor, case_id, merchant=merchant))


async def list_merchant_cases(session, actor, filters):
    require_merchant(actor)
    query = select(AfterSalesCase).where(AfterSalesCase.store_id == actor.store_id)
    if filters.cursor:
        query = query.where(AfterSalesCase.id > filters.cursor)
    if filters.status:
        query = query.where(AfterSalesCase.status == filters.status)
    cases = list(await session.scalars(query.order_by(AfterSalesCase.id).limit(filters.limit + 1)))
    return CasePage(
        items=[CaseDTO.model_validate(case) for case in cases[: filters.limit]],
        next_cursor=cases[filters.limit - 1].id if len(cases) > filters.limit else None,
    )


async def payment_for(session, order, *, lock=False):
    query = select(Payment).where(
        Payment.order_id == order.id,
        Payment.store_id == order.store_id,
        Payment.status == "SUCCEEDED",
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(query)


async def eligibility_for(session, order, reason_code, *, now=None):
    payment = await payment_for(session, order)
    active = await session.scalar(
        select(AfterSalesCase.id).where(
            AfterSalesCase.order_id == order.id,
            AfterSalesCase.status.not_in(("REJECTED", "CANCELLED")),
        )
    )
    result = evaluate_eligibility(
        status=order.status,
        delivered_at=order.delivered_at,
        policy_version=order.policy_version,
        has_payment=payment is not None and order.paid_at is not None,
        has_active_case=active is not None,
        reason_code=reason_code,
        now=now if now is not None else await database_now(session),
    )
    ticket = await session.scalar(
        select(SupportTicket.id)
        .where(
            SupportTicket.order_id == order.id,
            SupportTicket.status.in_(("OPEN", "IN_PROGRESS")),
            SupportTicket.blocked_action_types.contains(["RETURN_REQUEST"]),
        )
        .limit(1)
    )
    if ticket:
        result.eligible = False
        result.requires_human = True
        result.reason_codes.append("HUMAN_HANDOFF_REQUIRED")
    return result


async def check_eligibility(session, actor, order_id, reason_code, *, now=None):
    order = await owned_order(session, actor, order_id)
    return await eligibility_for(session, order, reason_code, now=now)


async def check_handoff(session, order_id, action_type):
    # Lazy import keeps support's object authorization independent of this module.
    from agentmall.support.service import check_handoff as check

    await check(session, order_id, action_type)


async def write_aftersales_event(session, case, event_type, now, *, actor_id, action_id=None):
    session.add(
        BusinessEvent(
            aggregate_type="aftersales_case",
            aggregate_id=case.id,
            action_id=action_id or case.proposal_id,
            event_type=event_type,
            payload_summary={
                "case_id": str(case.id),
                "order_id": str(case.order_id),
                "status": case.status,
                "version": case.version,
                "actor_id": str(actor_id),
            },
            occurred_at=now,
        )
    )
    await session.flush()


async def _existing_proposal(session, actor, request, digest):
    existing = await session.scalar(
        select(ActionProposal).where(
            ActionProposal.actor_id == actor.user_id,
            ActionProposal.origin_request_id == request.request_id,
            ActionProposal.proposal_slot == request.proposal_slot,
        )
    )
    if existing:
        if existing.store_id != actor.store_id:
            raise not_found()
        if existing.request_hash != digest:
            raise conflict()
    return existing


async def prepare_action(session, actor, target_id, action_type, request, idempotency_key):
    if action_type not in PAYLOADS:
        raise conflict("UNSUPPORTED_ACTION")
    merchant = action_type == "MOCK_REFUND"
    # Authorize the target even when returning a historical proposal.
    if action_type == "RETURN_REQUEST":
        order_id = target_id
        await owned_order(session, actor, order_id)
    else:
        case = await owned_case(session, actor, target_id, merchant=merchant)
        order_id = case.order_id
        await owned_order(session, actor, order_id, merchant=merchant)
    digest = payload_hash(
        {
            "schema_version": 1,
            "action_type": action_type,
            "target_id": str(target_id),
            **request.model_dump(mode="json"),
        }
    )
    key, new = await claim_key(
        session, actor, "prepare_" + action_type.lower(), idempotency_key, digest
    )
    existing = await _existing_proposal(session, actor, request, digest)
    if existing:
        if new:
            await complete_key(session, key, {"proposal_id": str(existing.id)})
        return await proposal_view(session, existing), False
    order = await owned_order(session, actor, order_id, lock=True, merchant=merchant)
    # A different key with the same origin may have committed while we waited on order.
    existing = await _existing_proposal(session, actor, request, digest)
    if existing:
        await complete_key(session, key, {"proposal_id": str(existing.id)})
        return await proposal_view(session, existing), False
    payment = await payment_for(session, order, lock=True) if merchant else None
    case = (
        None
        if action_type == "RETURN_REQUEST"
        else await owned_case(
            session,
            actor,
            target_id,
            merchant=merchant,
            lock=True,
        )
    )
    await check_handoff(session, order.id, action_type)
    now = await database_now(session)
    if action_type == "RETURN_REQUEST":
        eligibility = await eligibility_for(session, order, request.reason_code, now=now)
        if not eligibility.eligible:
            raise conflict("AFTERSALES_INELIGIBLE")
        if order.version != request.expected_version:
            raise conflict("STALE_VERSION")
        payload = ReturnPayload(
            schema_version=1,
            order_id=order.id,
            expected_order_version=order.version,
            reason_code=request.reason_code,
            description=request.description,
            policy_version=order.policy_version,
            eligibility_snapshot=eligibility,
        )
    else:
        if case.version != request.expected_version:
            raise conflict("STALE_VERSION")
        if order.status != "DELIVERED" or case.status != ("RECEIVED" if merchant else "REQUESTED"):
            raise conflict("INVALID_CASE_STATE")
        common = dict(
            schema_version=1,
            order_id=order.id,
            case_id=case.id,
            expected_version=case.version,
            policy_version=case.policy_version,
        )
        if merchant:
            if payment is None or case.policy_version not in POLICY_WINDOWS:
                raise conflict("REFUND_PREREQUISITE_FAILED")
            payload = RefundPayload(
                **common,
                payment_id=payment.id,
                expected_order_version=order.version,
                amount_cents=payment.amount_cents,
                currency=order.currency,
            )
        else:
            payload = ReturnCancelPayload(**common)
    body = payload.model_dump(mode="json")
    pid = await session.scalar(
        insert(ActionProposal)
        .values(
            id=uuid4(),
            actor_id=actor.user_id,
            store_id=actor.store_id,
            action_type=action_type,
            canonical_payload=body,
            payload_hash=payload_hash(body),
            request_hash=digest,
            schema_version=1,
            expires_at=now + timedelta(minutes=5),
            status="PENDING",
            origin_request_id=request.request_id,
            proposal_slot=request.proposal_slot,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_proposal_request_slot")
        .returning(ActionProposal.id)
    )
    created = pid is not None
    if not created:
        proposal = await _existing_proposal(session, actor, request, digest)
        pid = proposal.id
    else:
        proposal = await session.get(ActionProposal, pid)
    await complete_key(session, key, {"proposal_id": str(pid)})
    return await proposal_view(session, proposal), created


async def execute_aftersales_action(
    session,
    actor,
    action_id,
    confirmation_id,
    idempotency_key,
    *,
    expected_action=None,
    case_id=None,
):
    proposal = await owned_proposal(session, actor, action_id)
    if proposal.action_type not in PAYLOADS or (
        expected_action is not None and proposal.action_type != expected_action
    ):
        raise conflict("UNSUPPORTED_ACTION")
    action_type = proposal.action_type
    payload = PAYLOADS[action_type].model_validate(proposal.canonical_payload)
    merchant = action_type == "MOCK_REFUND"
    await owned_order(session, actor, payload.order_id, merchant=merchant)
    if action_type != "RETURN_REQUEST":
        if case_id is not None and payload.case_id != case_id:
            raise not_found()
        await owned_case(session, actor, payload.case_id, merchant=merchant)
    receipt_type = RefundReceipt if merchant else ReturnReceipt
    digest = payload_hash(
        {
            "schema_version": 1,
            "proposal_id": str(action_id),
            "confirmation_id": str(confirmation_id),
        }
    )
    key, new = await claim_key(
        session, actor, "execute_" + action_type.lower(), idempotency_key, digest
    )
    if not new:
        return receipt_type.model_validate(key.result), False
    proposal = await owned_proposal(session, actor, action_id, lock=True)
    prior = await session.scalar(
        select(IdempotencyRequest).where(
            IdempotencyRequest.action_id == action_id,
            IdempotencyRequest.actor_id == actor.user_id,
            IdempotencyRequest.store_id == actor.store_id,
        )
    )
    if prior:
        if prior.payload_hash != digest:
            raise conflict()
        await complete_key(session, key, prior.result)
        return receipt_type.model_validate(prior.result), False
    confirmation = await session.scalar(
        select(Confirmation)
        .where(
            Confirmation.id == confirmation_id,
            Confirmation.proposal_id == action_id,
            Confirmation.actor_id == actor.user_id,
            Confirmation.store_id == actor.store_id,
        )
        .with_for_update()
    )
    if confirmation is None:
        raise not_found()
    if (
        confirmation.decision != "approve"
        or confirmation.consumed_at
        or proposal.status != "APPROVED"
    ):
        raise conflict("CONFIRMATION_REQUIRED")
    if (
        proposal.schema_version != 1
        or payload_hash(proposal.canonical_payload) != proposal.payload_hash
    ):
        raise conflict("STALE_PROPOSAL")
    order = await owned_order(session, actor, payload.order_id, lock=True, merchant=merchant)
    payment = await payment_for(session, order, lock=True)
    case = (
        None
        if action_type == "RETURN_REQUEST"
        else await owned_case(
            session,
            actor,
            payload.case_id,
            merchant=merchant,
            lock=True,
        )
    )
    await check_handoff(session, order.id, action_type)
    now = await database_now(session)
    if now >= proposal.expires_at:
        raise conflict("STALE_PROPOSAL")
    if order.policy_version != payload.policy_version:
        raise conflict("STALE_PROPOSAL")
    if action_type == "RETURN_REQUEST":
        eligibility = await eligibility_for(session, order, payload.reason_code, now=now)
        if not eligibility.eligible:
            raise conflict("AFTERSALES_INELIGIBLE")
        if order.version != payload.expected_order_version:
            raise conflict("STALE_VERSION")
        case = AfterSalesCase(
            id=uuid4(),
            order_id=order.id,
            user_id=actor.user_id,
            store_id=actor.store_id,
            proposal_id=action_id,
            status="REQUESTED",
            reason_code=payload.reason_code,
            description=payload.description,
            policy_version=order.policy_version,
            eligibility_snapshot=eligibility.model_dump(mode="json"),
            restockable=False,
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(case)
        result_status, event = "REQUESTED", "RETURN_REQUESTED"
    else:
        if case.version != payload.expected_version:
            raise conflict("STALE_VERSION")
        if order.status != "DELIVERED" or case.status != ("RECEIVED" if merchant else "REQUESTED"):
            raise conflict("INVALID_CASE_STATE")
        if case.policy_version != order.policy_version:
            raise conflict("STALE_PROPOSAL")
        if merchant:
            if (
                payment is None
                or payment.id != payload.payment_id
                or payment.amount_cents != payload.amount_cents
                or order.version != payload.expected_order_version
                or case.policy_version not in POLICY_WINDOWS
            ):
                raise conflict("REFUND_PREREQUISITE_FAILED")
            if await session.scalar(select(Refund.id).where(Refund.payment_id == payment.id)):
                raise conflict("ALREADY_REFUNDED")
            refund_id = uuid4()
            session.add(
                Refund(
                    id=refund_id,
                    case_id=case.id,
                    order_id=order.id,
                    store_id=order.store_id,
                    payment_id=payment.id,
                    amount_cents=payment.amount_cents,
                    status="SUCCEEDED",
                    action_id=action_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            case.status, case.refunded_at = "REFUNDED", now
            order.status, order.updated_at = "REFUNDED", now
            order.version += 1
            event = "REFUND_SUCCEEDED"
        else:
            case.status, case.cancelled_at = "CANCELLED", now
            result_status, event = "CANCELLED", "RETURN_CANCELLED"
        case.version += 1
        case.updated_at = now
    if merchant:
        receipt = RefundReceipt(
            action_id=action_id,
            resource_id=refund_id,
            refund_id=refund_id,
            case_id=case.id,
            order_id=order.id,
            payment_id=payment.id,
            amount_cents=payment.amount_cents,
            created_at=now,
        )
    else:
        receipt = ReturnReceipt(
            action_type=action_type,
            action_id=action_id,
            resource_id=case.id,
            case_id=case.id,
            order_id=order.id,
            status=result_status,
            created_at=now,
        )
    confirmation.consumed_at, confirmation.result_ref = now, receipt.resource_id
    proposal.status = "EXECUTED"
    await complete_key(session, key, receipt.model_dump(mode="json"), action_id=action_id)
    await write_aftersales_event(
        session, case, event, now, actor_id=actor.user_id, action_id=action_id
    )
    return receipt, True


async def _merchant_case(session, actor, case_id, expected_version, action_type):
    case = await owned_case(session, actor, case_id, merchant=True)
    order = await owned_order(session, actor, case.order_id, lock=True, merchant=True)
    case = await owned_case(session, actor, case_id, lock=True, merchant=True)
    await check_handoff(session, order.id, action_type)
    if case.version != expected_version:
        raise conflict("STALE_VERSION")
    if order.status != "DELIVERED":
        raise conflict("INVALID_ORDER_STATE")
    return case


async def review_case(session, actor, case_id, expected_version, decision, reason):
    case = await _merchant_case(session, actor, case_id, expected_version, "REVIEW_CASE")
    if case.status != "REQUESTED" or decision not in {"approve", "reject"}:
        raise conflict("INVALID_CASE_STATE")
    now = await database_now(session)
    case.status = "APPROVED" if decision == "approve" else "REJECTED"
    case.version += 1
    case.reviewed_by, case.reviewed_at, case.review_reason = actor.user_id, now, reason
    case.updated_at = now
    await write_aftersales_event(session, case, "CASE_" + case.status, now, actor_id=actor.user_id)
    return CaseDTO.model_validate(case)


async def receive_case(session, actor, case_id, expected_version):
    case = await _merchant_case(session, actor, case_id, expected_version, "RECEIVE_CASE")
    if case.status != "APPROVED":
        raise conflict("INVALID_CASE_STATE")
    now = await database_now(session)
    case.status, case.version = "RECEIVED", case.version + 1
    case.received_by, case.received_at, case.updated_at = actor.user_id, now, now
    await write_aftersales_event(session, case, "CASE_RECEIVED", now, actor_id=actor.user_id)
    return CaseDTO.model_validate(case)
