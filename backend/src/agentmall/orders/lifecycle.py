"""Existing-order transitions. Lock order before any product; caller owns commit."""

from sqlalchemy import select

from agentmall.actions.service import conflict, database_now
from agentmall.catalog.models import Product
from agentmall.identity.service import require_buyer
from agentmall.infra.audit import BusinessEvent
from agentmall.infra.errors import DomainError, not_found
from agentmall.orders.models import Order, OrderItem
from agentmall.orders.schemas import ExpiryResult, ShipmentDTO, ShipmentEvent
from agentmall.orders.service import order_view


async def owned_order(session, actor, order_id, *, lock=False, merchant=False):
    if merchant:
        if actor.role != "merchant" or actor.user_id is None:
            raise DomainError(403, "FORBIDDEN", "此接口仅供所属店铺商家使用")
    else:
        require_buyer(actor)
    query = select(Order).where(Order.id == order_id, Order.store_id == actor.store_id)
    if not merchant:
        query = query.where(Order.user_id == actor.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    order = await session.scalar(query)
    if order is None:
        raise not_found()
    return order


async def locked_inventory(session, order):
    items = list(
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id, OrderItem.store_id == order.store_id)
            .order_by(OrderItem.product_id)
        )
    )
    products = {
        p.id: p
        for p in await session.scalars(
            select(Product)
            .where(
                Product.id.in_([i.product_id for i in items]), Product.store_id == order.store_id
            )
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    if not items or any(
        i.product_id not in products or products[i.product_id].reserved < i.quantity for i in items
    ):
        raise conflict("INVENTORY_INCONSISTENT")
    return items, products


async def write_lifecycle_event(
    session, order, event_type, now, *, action_id=None, actor_id=None, previous=None, result=None
):
    session.add(
        BusinessEvent(
            aggregate_type="order",
            aggregate_id=order.id,
            action_id=action_id or order.proposal_id,
            event_type=event_type,
            payload_summary={
                "from_status": previous,
                "status": order.status,
                "version": order.version,
                "total_cents": order.total_cents,
                "actor_id": str(actor_id) if actor_id else None,
                "result": result,
            },
            occurred_at=now,
        )
    )
    await session.flush()


async def close_pending_order(
    session, order, items, products, status, now, *, action_id=None, actor_id=None
):
    if order.status != "PENDING_PAYMENT" or status not in {"CANCELLED", "EXPIRED"}:
        raise conflict("INVALID_ORDER_STATE")
    for item in items:
        products[item.product_id].reserved -= item.quantity
    order.status, order.updated_at = status, now
    order.version += 1
    await session.flush()
    await write_lifecycle_event(
        session,
        order,
        "ORDER_" + status,
        now,
        action_id=action_id,
        actor_id=actor_id,
        previous="PENDING_PAYMENT",
    )


async def expire_order(session, order_id):
    """Internal maintenance entry; no actor-free HTTP endpoint exposes it."""
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        raise not_found()
    if order.status != "PENDING_PAYMENT" or await database_now(session) < order.expires_at:
        return ExpiryResult(order_id=order.id, status=order.status, changed=False)
    items, products = await locked_inventory(session, order)
    now = await database_now(session)
    await close_pending_order(session, order, items, products, "EXPIRED", now)
    return ExpiryResult(order_id=order.id, status="EXPIRED", changed=True)


async def advance_shipment(session, actor, order_id, event, expected_version):
    order = await owned_order(session, actor, order_id, lock=True, merchant=True)
    transitions = {
        "ship": ("PAID", "SHIPPED", "shipped_at"),
        "deliver": ("SHIPPED", "DELIVERED", "delivered_at"),
    }
    if event not in transitions:
        raise conflict("INVALID_SHIPMENT_EVENT")
    source, target, timestamp = transitions[event]
    if order.version != expected_version:
        raise conflict("STALE_VERSION")
    if order.status != source:
        raise conflict("INVALID_ORDER_STATE")
    now = await database_now(session)
    order.status, order.updated_at = target, now
    order.version += 1
    setattr(order, timestamp, now)
    await write_lifecycle_event(
        session, order, "ORDER_" + target, now, actor_id=actor.user_id, previous=source
    )
    return await order_view(session, order)


async def shipment(session, actor, order_id):
    order = await owned_order(session, actor, order_id)
    return ShipmentDTO(
        order_id=order.id,
        status=order.status,
        events=[
            ShipmentEvent(status=status, occurred_at=when)
            for status, when in (
                ("PAID", order.paid_at),
                ("SHIPPED", order.shipped_at),
                ("DELIVERED", order.delivered_at),
            )
            if when is not None
        ],
    )
