"""Deterministic proposal and confirmation services; caller owns the transaction."""

import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from agentmall.actions.models import ActionProposal, Confirmation, IdempotencyRequest
from agentmall.actions.schemas import CheckoutRequest, ConfirmationDTO, ProposalDTO
from agentmall.cart.models import Cart, CartItem
from agentmall.catalog.models import Product
from agentmall.identity.service import require_buyer
from agentmall.infra.errors import DomainError, not_found


async def database_now(session):
    return await session.scalar(select(func.clock_timestamp()))


def payload_hash(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def conflict(code="IDEMPOTENCY_CONFLICT"):
    return DomainError(409, code, "请求与已有状态不一致，请查询原提案或业务回执")


def normalize_items(items):
    quantities = {}
    for item in items:
        pid = str(item.product_id)
        quantities[pid] = quantities.get(pid, 0) + item.quantity
    if not quantities or len(quantities) > 20 or any(q > 10 for q in quantities.values()):
        raise DomainError(422, "VALIDATION_ERROR", "每件商品合并数量须为 1..10，最多 20 件商品")
    return [{"product_id": pid, "quantity": q} for pid, q in sorted(quantities.items())]


async def claim_key(session, actor, operation, key, digest):
    inserted = await session.scalar(
        insert(IdempotencyRequest)
        .values(
            id=uuid4(),
            actor_id=actor.user_id,
            store_id=actor.store_id,
            operation=operation,
            key=key,
            payload_hash=digest,
        )
        .on_conflict_do_nothing(constraint="uq_idempotency_key")
        .returning(IdempotencyRequest.id)
    )
    record = await session.scalar(
        select(IdempotencyRequest)
        .where(
            IdempotencyRequest.actor_id == actor.user_id,
            IdempotencyRequest.store_id == actor.store_id,
            IdempotencyRequest.operation == operation,
            IdempotencyRequest.key == key,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record.payload_hash != digest:
        raise conflict()
    return record, inserted is not None


async def complete_key(session, record, result, *, action_id=None):
    record.action_id = action_id
    record.result = result
    record.completed_at = await database_now(session)
    await session.flush()


async def owned_proposal(session, actor, proposal_id, *, lock=False):
    allowed = {
        "buyer": ("CHECKOUT", "MOCK_PAYMENT", "CANCEL_ORDER", "RETURN_REQUEST", "RETURN_CANCEL"),
        "merchant": ("MOCK_REFUND",),
    }
    if actor.user_id is None or actor.role not in allowed:
        raise DomainError(403, "FORBIDDEN", "此接口需要有效业务身份")
    query = select(ActionProposal).where(
        ActionProposal.id == proposal_id,
        ActionProposal.action_type.in_(allowed[actor.role]),
        ActionProposal.actor_id == actor.user_id,
        ActionProposal.store_id == actor.store_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    proposal = await session.scalar(query)
    if proposal is None:
        raise not_found()
    return proposal


def confirmation_dto(c):
    return ConfirmationDTO(
        confirmation_id=c.id,
        proposal_id=c.proposal_id,
        decision=c.decision,
        decided_at=c.decided_at,
        consumed_at=c.consumed_at,
        result_ref=c.result_ref,
    )


async def proposal_view(session, proposal):
    confirmation = await session.scalar(
        select(Confirmation).where(
            Confirmation.proposal_id == proposal.id,
            Confirmation.actor_id == proposal.actor_id,
            Confirmation.store_id == proposal.store_id,
        )
    )
    receipt = await session.scalar(
        select(IdempotencyRequest).where(
            IdempotencyRequest.action_id == proposal.id,
            IdempotencyRequest.actor_id == proposal.actor_id,
            IdempotencyRequest.store_id == proposal.store_id,
        )
    )
    status = proposal.status
    if (
        status not in {"EXECUTED", "REJECTED"}
        and await database_now(session) >= proposal.expires_at
    ):
        status = "EXPIRED"
    return ProposalDTO(
        proposal_id=proposal.id,
        action_type=proposal.action_type,
        canonical_payload=proposal.canonical_payload,
        payload_hash=proposal.payload_hash,
        schema_version=proposal.schema_version,
        expires_at=proposal.expires_at,
        status=status,
        confirmation=confirmation_dto(confirmation) if confirmation else None,
        result=receipt.result if receipt else None,
    )


async def get_proposal(session, actor, proposal_id):
    return await proposal_view(
        session, await owned_proposal(session, actor, proposal_id, lock=True)
    )


async def prepare_checkout(
    session,
    actor,
    request_id,
    proposal_slot,
    items,
    address_label,
    idempotency_key,
    *,
    cart_id=None,
    expected_cart_version=None,
):
    require_buyer(actor)
    request = CheckoutRequest(
        request_id=request_id,
        proposal_slot=proposal_slot,
        items=items,
        address_label=address_label,
        cart_id=cart_id,
        expected_cart_version=expected_cart_version,
    )
    normalized = request.model_dump(mode="json", exclude_none=True)
    if request.items is not None:
        normalized["items"] = normalize_items(request.items)
    digest = payload_hash({"schema_version": 1, **normalized})
    key, new = await claim_key(session, actor, "prepare_checkout", idempotency_key, digest)
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
    if request.items is not None:
        source_items = normalized["items"]
    else:
        cart = await session.scalar(
            select(Cart)
            .where(
                Cart.id == request.cart_id,
                Cart.user_id == actor.user_id,
                Cart.store_id == actor.store_id,
            )
            .with_for_update()
        )
        if cart is None:
            raise not_found()
        if cart.version != request.expected_cart_version:
            raise conflict("STALE_CART")
        source_items = [
            {"product_id": str(item.product_id), "quantity": item.quantity}
            for item in await session.scalars(
                select(CartItem)
                .where(CartItem.cart_id == cart.id, CartItem.store_id == actor.store_id)
                .order_by(CartItem.product_id)
            )
        ]
        if not source_items:
            raise conflict("EMPTY_CART")
    # One statement gives a coherent catalogue snapshot. It does not reserve or lock inventory.
    products = {
        str(p.id): p
        for p in await session.scalars(
            select(Product).where(
                Product.id.in_([UUID(i["product_id"]) for i in source_items]),
                Product.store_id == actor.store_id,
                Product.active.is_(True),
            )
        )
    }
    snapshots = []
    for item in source_items:
        product = products.get(item["product_id"])
        if product is None:
            raise not_found()
        if product.on_hand - product.reserved < item["quantity"]:
            raise conflict("INSUFFICIENT_STOCK")
        snapshots.append(
            {
                **item,
                "name_snapshot": product.name,
                "unit_price_cents": product.price_cents,
                "catalog_version": product.catalog_version,
                "attributes_snapshot": product.attributes,
            }
        )
    total = sum(i["quantity"] * i["unit_price_cents"] for i in snapshots)
    if total > 9223372036854775807:
        raise DomainError(422, "AMOUNT_TOO_LARGE", "金额超出支持范围")
    payload = {
        "schema_version": 1,
        "items": snapshots,
        "total_cents": total,
        "currency": "CNY",
        "address_label": request.address_label,
        "policy_version": "demo-v1",
    }
    now = await database_now(session)
    pid = await session.scalar(
        insert(ActionProposal)
        .values(
            id=uuid4(),
            actor_id=actor.user_id,
            store_id=actor.store_id,
            action_type="CHECKOUT",
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


async def confirm_proposal(session, actor, proposal_id, decision):
    if decision not in {"approve", "reject"}:
        raise DomainError(422, "VALIDATION_ERROR", "decision 必须是 approve 或 reject")
    proposal = await owned_proposal(session, actor, proposal_id, lock=True)
    confirmation = await session.scalar(
        select(Confirmation)
        .where(
            Confirmation.proposal_id == proposal.id,
            Confirmation.actor_id == actor.user_id,
            Confirmation.store_id == actor.store_id,
        )
        .with_for_update()
    )
    if confirmation:
        if confirmation.decision != decision:
            raise conflict("CONFIRMATION_CONFLICT")
        return confirmation_dto(confirmation), False
    now = await database_now(session)
    if now >= proposal.expires_at:
        raise conflict("STALE_PROPOSAL")
    if proposal.status != "PENDING":
        raise conflict("PROPOSAL_NOT_PENDING")
    confirmation = Confirmation(
        proposal_id=proposal.id,
        actor_id=actor.user_id,
        store_id=actor.store_id,
        decision=decision,
        decided_at=now,
    )
    session.add(confirmation)
    proposal.status = "APPROVED" if decision == "approve" else "REJECTED"
    await session.flush()
    return confirmation_dto(confirmation), True
