"""Caller commits the receipt and all business effects together, before returning HTTP success."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from agentmall.actions.models import Confirmation, IdempotencyRequest
from agentmall.actions.schemas import ActionReceipt
from agentmall.actions.service import (
    claim_key,
    complete_key,
    conflict,
    database_now,
    owned_proposal,
    payload_hash,
)
from agentmall.cart.service import consume_checkout_cart, lock_checkout_cart
from agentmall.catalog.models import Product
from agentmall.identity.service import require_buyer, require_merchant
from agentmall.infra.audit import write_order_event
from agentmall.infra.errors import not_found
from agentmall.orders.models import Order, OrderItem
from agentmall.orders.schemas import OrderDTO, OrderItemDTO, OrderPage


async def execute_confirmed_action(
    session,
    actor,
    action_id,
    confirmation_id,
    idempotency_key,
    *,
    expected_action=None,
    order_id=None,
    adapter=None,
    case_id=None,
):
    proposal = await owned_proposal(session, actor, action_id)
    if expected_action is not None and proposal.action_type != expected_action:
        raise conflict("UNSUPPORTED_ACTION")
    if proposal.action_type == "CHECKOUT":
        return await _execute_checkout(session, actor, action_id, confirmation_id, idempotency_key)
    if proposal.action_type in {"RETURN_REQUEST", "RETURN_CANCEL", "MOCK_REFUND"}:
        from agentmall.aftersales.service import execute_aftersales_action

        return await execute_aftersales_action(
            session,
            actor,
            action_id,
            confirmation_id,
            idempotency_key,
            expected_action=expected_action,
            case_id=case_id,
        )
    from agentmall.payments.service import execute_order_action

    return await execute_order_action(
        session,
        actor,
        action_id,
        confirmation_id,
        idempotency_key,
        order_id=order_id,
        expected_action=expected_action,
        adapter=adapter,
    )


async def _execute_checkout(session, actor, action_id, confirmation_id, idempotency_key):
    # Authorization precedes replay. Neither an opaque confirmation id nor a key is authority.
    initial = await owned_proposal(session, actor, action_id)
    if payload_hash(initial.canonical_payload) != initial.payload_hash:
        raise conflict("STALE_PROPOSAL")
    source, cart = await lock_checkout_cart(
        session, actor, initial.canonical_payload.get("cart_source")
    )
    digest = payload_hash(
        {
            "schema_version": 1,
            "proposal_id": str(action_id),
            "confirmation_id": str(confirmation_id),
        }
    )
    key, new = await claim_key(session, actor, "execute_checkout", idempotency_key, digest)
    if not new:
        return ActionReceipt.model_validate(key.result), False
    proposal = await owned_proposal(session, actor, action_id, lock=True)
    # Serialize by proposal, so a new key cannot bypass the one-action business identity.
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
        # Bind the additional key, but only the canonical receipt owns UNIQUE(action_id).
        await complete_key(session, key, prior.result)
        return ActionReceipt.model_validate(prior.result), False
    confirmation = await session.scalar(
        select(Confirmation)
        .where(
            Confirmation.id == confirmation_id,
            Confirmation.proposal_id == proposal.id,
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
    if proposal.action_type != "CHECKOUT" or proposal.schema_version != 1:
        raise conflict("UNSUPPORTED_ACTION")
    if await database_now(session) >= proposal.expires_at:
        raise conflict("STALE_PROPOSAL")
    payload = proposal.canonical_payload
    if payload_hash(payload) != proposal.payload_hash:
        raise conflict("STALE_PROPOSAL")
    items = payload["items"]
    # All execution paths acquire products in UUID order after the proposal/confirmation.
    products = {
        str(p.id): p
        for p in await session.scalars(
            select(Product)
            .where(
                Product.id.in_([UUID(i["product_id"]) for i in items]),
                Product.store_id == actor.store_id,
            )
            .order_by(Product.id)
            .with_for_update()
        )
    }
    cart_consumption = await consume_checkout_cart(session, actor, source, items, cart)
    now = await database_now(
        session
    )  # Actual time AFTER product AND cart lock waits, never transaction-start now().
    if now >= proposal.expires_at:
        raise conflict("STALE_PROPOSAL")
    for item in items:
        product = products.get(item["product_id"])
        if product is None:
            raise not_found()
        if (
            not product.active
            or product.price_cents != item["unit_price_cents"]
            or product.catalog_version != item["catalog_version"]
            or product.name != item["name_snapshot"]
            or product.attributes != item["attributes_snapshot"]
        ):
            raise conflict("STALE_PROPOSAL")
        if product.on_hand - product.reserved < item["quantity"]:
            raise conflict("INSUFFICIENT_STOCK")
    total = sum(i["quantity"] * i["unit_price_cents"] for i in items)
    if total != payload["total_cents"]:
        raise conflict("STALE_PROPOSAL")
    for item in items:
        products[item["product_id"]].reserved += item["quantity"]
    await session.flush()
    order = Order(
        id=uuid4(),
        user_id=actor.user_id,
        store_id=actor.store_id,
        proposal_id=proposal.id,
        status="PENDING_PAYMENT",
        total_cents=total,
        currency="CNY",
        address_label=payload["address_label"],
        expires_at=now + timedelta(minutes=15),
        policy_version=payload["policy_version"],
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    await session.flush()
    for item in items:
        session.add(
            OrderItem(
                order_id=order.id,
                store_id=actor.store_id,
                product_id=UUID(item["product_id"]),
                name_snapshot=item["name_snapshot"],
                unit_price_cents=item["unit_price_cents"],
                quantity=item["quantity"],
                attributes_snapshot=item["attributes_snapshot"],
            )
        )
    proposal.status = "EXECUTED"
    confirmation.consumed_at = now
    confirmation.result_ref = order.id
    receipt = ActionReceipt(
        cart_consumption=cart_consumption,
        action_id=proposal.id,
        resource_id=order.id,
        order_id=order.id,
        status="PENDING_PAYMENT",
        total_cents=total,
        created_at=now,
    )
    await complete_key(session, key, receipt.model_dump(mode="json"), action_id=proposal.id)
    # A test can fail this real write to exercise the entire pre-commit rollback window.
    await write_order_event(session, order, now)
    return receipt, True


async def order_view(session, order):
    items = await session.scalars(
        select(OrderItem)
        .where(OrderItem.order_id == order.id, OrderItem.store_id == order.store_id)
        .order_by(OrderItem.product_id)
    )
    return order_dto(order, items)


def order_dto(order, items):
    return OrderDTO(
        id=order.id,
        user_id=order.user_id,
        store_id=order.store_id,
        proposal_id=order.proposal_id,
        status=order.status,
        total_cents=order.total_cents,
        currency=order.currency,
        address_label=order.address_label,
        expires_at=order.expires_at,
        created_at=order.created_at,
        version=order.version,
        paid_at=order.paid_at,
        shipped_at=order.shipped_at,
        delivered_at=order.delivered_at,
        policy_version=order.policy_version,
        items=[OrderItemDTO.model_validate(i) for i in items],
    )


async def get_order(session, actor, order_id):
    require_buyer(actor)
    order = await session.scalar(
        select(Order).where(
            Order.id == order_id, Order.user_id == actor.user_id, Order.store_id == actor.store_id
        )
    )
    if order is None:
        raise not_found()
    return await order_view(session, order)


async def list_orders(session, actor, filters):
    require_buyer(actor)
    return await _order_page(session, actor.store_id, filters, buyer_id=actor.user_id)


async def list_merchant_orders(session, actor, filters):
    require_merchant(actor)
    return await _order_page(session, actor.store_id, filters)


async def _order_page(session, store_id, filters, *, buyer_id=None):
    query = select(Order).where(Order.store_id == store_id)
    if buyer_id is not None:
        query = query.where(Order.user_id == buyer_id)
    if filters.cursor:
        query = query.where(Order.id > filters.cursor)
    if filters.status:
        query = query.where(Order.status == filters.status)
    orders = list(await session.scalars(query.order_by(Order.id).limit(filters.limit + 1)))
    page = orders[: filters.limit]
    items = {order.id: [] for order in page}
    if page:
        for item in await session.scalars(
            select(OrderItem)
            .where(OrderItem.store_id == store_id, OrderItem.order_id.in_(items))
            .order_by(OrderItem.product_id)
        ):
            items[item.order_id].append(item)
    return OrderPage(
        items=[order_dto(order, items[order.id]) for order in page],
        next_cursor=orders[filters.limit - 1].id if len(orders) > filters.limit else None,
    )
