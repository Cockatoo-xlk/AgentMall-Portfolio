"""Confirmed mock payment/cancel actions on the existing T02 authorization ledger."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from agentmall.actions.models import ActionProposal, Confirmation, IdempotencyRequest
from agentmall.actions.schemas import (
    CancelReceipt,
    OrderActionPayload,
    OrderActionRequest,
    PaymentReceipt,
)
from agentmall.actions.service import (
    claim_key,
    complete_key,
    conflict,
    database_now,
    get_proposal,
    owned_proposal,
    payload_hash,
)
from agentmall.infra.errors import not_found
from agentmall.orders.lifecycle import (
    close_pending_order,
    locked_inventory,
    owned_order,
    write_lifecycle_event,
)
from agentmall.payments.models import Payment

ActionType = Literal["MOCK_PAYMENT", "CANCEL_ORDER"]


@dataclass(frozen=True)
class MockPaymentAdapter:
    """Local deterministic adapter; HTTP clients cannot select its result."""

    result: Literal["SUCCEEDED", "DECLINED"] = "SUCCEEDED"

    def decide(self):
        if self.result not in {"SUCCEEDED", "DECLINED"}:
            raise ValueError("Invalid controlled mock payment outcome")
        return self.result


async def prepare_order_action(
    session, actor, order_id, action_type: ActionType, request: OrderActionRequest, idempotency_key
):
    if action_type not in {"MOCK_PAYMENT", "CANCEL_ORDER"}:
        raise conflict("UNSUPPORTED_ACTION")
    # Read-only authorization before idempotency; no order lock is held while claiming a key.
    await owned_order(session, actor, order_id)
    normalized = {
        "schema_version": 1,
        "action_type": action_type,
        "order_id": str(order_id),
        **request.model_dump(mode="json"),
    }
    digest = payload_hash(normalized)
    key, new = await claim_key(
        session, actor, "prepare_" + action_type.lower(), idempotency_key, digest
    )
    if not new:
        return await get_proposal(session, actor, UUID(key.result["proposal_id"])), False
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
        await complete_key(session, key, {"proposal_id": str(existing.id)})
        return await get_proposal(session, actor, existing.id), False
    # Proposal preparation is a coherent, immutable quote, not a stock reservation.
    order = await owned_order(session, actor, order_id)
    now = await database_now(session)
    if order.status != "PENDING_PAYMENT" or now >= order.expires_at:
        raise conflict("INVALID_ORDER_STATE")
    if order.version != request.expected_version:
        raise conflict("STALE_VERSION")
    payload = OrderActionPayload(
        schema_version=1,
        order_id=order.id,
        expected_version=order.version,
        total_cents=order.total_cents,
        currency=order.currency,
        policy_version=order.policy_version,
    ).model_dump(mode="json")
    pid = await session.scalar(
        insert(ActionProposal)
        .values(
            id=uuid4(),
            actor_id=actor.user_id,
            store_id=actor.store_id,
            action_type=action_type,
            canonical_payload=payload,
            payload_hash=payload_hash(payload),
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
        existing = await session.scalar(
            select(ActionProposal).where(
                ActionProposal.actor_id == actor.user_id,
                ActionProposal.origin_request_id == request.request_id,
                ActionProposal.proposal_slot == request.proposal_slot,
            )
        )
        if existing.store_id != actor.store_id:
            raise not_found()
        if existing.request_hash != digest:
            raise conflict()
        pid = existing.id
    await complete_key(session, key, {"proposal_id": str(pid)})
    return await get_proposal(session, actor, pid), created


async def execute_order_action(
    session,
    actor,
    action_id,
    confirmation_id,
    idempotency_key,
    *,
    order_id=None,
    expected_action=None,
    adapter=None,
):
    proposal = await owned_proposal(session, actor, action_id)
    if proposal.action_type not in {"MOCK_PAYMENT", "CANCEL_ORDER"} or (
        expected_action and proposal.action_type != expected_action
    ):
        raise conflict("UNSUPPORTED_ACTION")
    payload = OrderActionPayload.model_validate(proposal.canonical_payload)
    if order_id is not None and payload.order_id != order_id:
        raise not_found()
    await owned_order(session, actor, payload.order_id)
    receipt_type = PaymentReceipt if proposal.action_type == "MOCK_PAYMENT" else CancelReceipt
    digest = payload_hash(
        {
            "schema_version": 1,
            "proposal_id": str(action_id),
            "confirmation_id": str(confirmation_id),
        }
    )
    key, new = await claim_key(
        session, actor, "execute_" + proposal.action_type.lower(), idempotency_key, digest
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
        or confirmation.consumed_at is not None
        or proposal.status != "APPROVED"
    ):
        raise conflict("CONFIRMATION_REQUIRED")
    if (
        proposal.schema_version != 1
        or payload_hash(proposal.canonical_payload) != proposal.payload_hash
    ):
        raise conflict("STALE_PROPOSAL")
    # No existing-order path locks products before this shared order lock.
    order = await owned_order(session, actor, payload.order_id, lock=True)
    now = await database_now(session)
    if now >= proposal.expires_at:
        raise conflict("STALE_PROPOSAL")
    payment_id = None
    result = None
    if order.status == "EXPIRED":
        result = "EXPIRED"
    elif order.status != "PENDING_PAYMENT":
        raise conflict("INVALID_ORDER_STATE")
    else:
        items, products = await locked_inventory(session, order)
        now = await database_now(session)  # Also guard a deadline crossed waiting on shared stock.
        if now >= proposal.expires_at:
            raise conflict("STALE_PROPOSAL")
        if now >= order.expires_at:
            await close_pending_order(session, order, items, products, "EXPIRED", now)
            result = "EXPIRED"
        else:
            if (
                order.version != payload.expected_version
                or order.total_cents != payload.total_cents
                or order.currency != payload.currency
                or order.policy_version != payload.policy_version
            ):
                raise conflict("STALE_VERSION")
            if proposal.action_type == "CANCEL_ORDER":
                await close_pending_order(
                    session,
                    order,
                    items,
                    products,
                    "CANCELLED",
                    now,
                    action_id=action_id,
                    actor_id=actor.user_id,
                )
                result = "CANCELLED"
            else:
                result = (adapter or MockPaymentAdapter()).decide()
                if result not in {"SUCCEEDED", "DECLINED"}:
                    raise ValueError("Invalid mock adapter result")
                if result == "SUCCEEDED":
                    payment_id = uuid4()
                    for item in items:
                        product = products[item.product_id]
                        product.on_hand -= item.quantity
                        product.reserved -= item.quantity
                    order.status, order.paid_at, order.updated_at = "PAID", now, now
                    order.version += 1
                    session.add(
                        Payment(
                            id=payment_id,
                            order_id=order.id,
                            store_id=order.store_id,
                            amount_cents=order.total_cents,
                            status="SUCCEEDED",
                            provider="mock",
                            action_id=action_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
    common = dict(
        action_id=action_id,
        resource_id=order.id,
        order_id=order.id,
        total_cents=order.total_cents,
        currency=order.currency,
        created_at=now,
    )
    if proposal.action_type == "MOCK_PAYMENT":
        receipt = PaymentReceipt(
            **common, status=result, payment_id=payment_id, order_status=order.status
        )
    else:
        receipt = CancelReceipt(**common, status=result)
    confirmation.consumed_at, confirmation.result_ref = now, order.id
    proposal.status = "EXECUTED"
    await complete_key(session, key, receipt.model_dump(mode="json"), action_id=action_id)
    if result != "CANCELLED":
        event = (
            "ORDER_PAID"
            if result == "SUCCEEDED"
            else ("PAYMENT_" if proposal.action_type == "MOCK_PAYMENT" else "CANCEL_") + result
        )
        await write_lifecycle_event(
            session,
            order,
            event,
            now,
            action_id=action_id,
            actor_id=actor.user_id,
            previous="PENDING_PAYMENT" if result != "EXPIRED" else None,
            result=result,
        )
    return receipt, True


async def pay_mock_order(
    session, actor, action_id, confirmation_id, idempotency_key, *, adapter=None, order_id=None
):
    return await execute_order_action(
        session,
        actor,
        action_id,
        confirmation_id,
        idempotency_key,
        expected_action="MOCK_PAYMENT",
        order_id=order_id,
        adapter=adapter,
    )
