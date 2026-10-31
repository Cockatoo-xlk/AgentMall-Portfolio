from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from agentmall.cart.models import Cart, CartItem
from agentmall.cart.schemas import CartDTO, CartItemDTO, CheckoutCartSource, SetQuantity
from agentmall.catalog.models import Product
from agentmall.identity.service import ActorContext, require_buyer
from agentmall.infra.errors import DomainError, not_found


async def locked_cart(session, actor: ActorContext) -> Cart:
    require_buyer(actor)
    # This also serializes simultaneous first requests through the unique key.
    await session.execute(
        insert(Cart)
        .values(
            id=uuid4(),
            user_id=actor.user_id,
            store_id=actor.store_id,
            version=0,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "store_id"])
    )
    return await session.scalar(
        select(Cart)
        .where(
            Cart.user_id == actor.user_id,
            Cart.store_id == actor.store_id,
        )
        .with_for_update()
    )


async def snapshot(session, actor: ActorContext, cart: Cart) -> CartDTO:
    rows = (
        await session.execute(
            select(CartItem, Product)
            .join(
                Product,
                (Product.id == CartItem.product_id) & (Product.store_id == CartItem.store_id),
            )
            .join(Cart, (Cart.id == CartItem.cart_id) & (Cart.store_id == CartItem.store_id))
            .where(
                Cart.id == cart.id, Cart.user_id == actor.user_id, Cart.store_id == actor.store_id
            )
            .order_by(CartItem.product_id)
        )
    ).all()
    return CartDTO(
        id=cart.id,
        user_id=cart.user_id,
        store_id=cart.store_id,
        version=cart.version,
        items=[
            CartItemDTO(
                product_id=item.product_id,
                quantity=item.quantity,
                name=p.name,
                unit_price_cents=p.price_cents,
                available=p.on_hand - p.reserved,
                active=p.active,
            )
            for item, p in rows
        ],
    )


async def get_cart(session, actor: ActorContext) -> CartDTO:
    return await snapshot(session, actor, await locked_cart(session, actor))


async def set_cart_quantity(session, actor: ActorContext, product_id, quantity, expected_version):
    # Keep validation at the service boundary too, for future in-process callers.
    payload = SetQuantity(quantity=quantity, expected_version=expected_version)
    cart = await locked_cart(session, actor)
    if cart.version != payload.expected_version:
        raise DomainError(409, "STALE_VERSION", "购物车已变化，请先 GET 核对，再由用户决定是否修改")
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.store_id == actor.store_id,
        )
    )
    if product is None or (payload.quantity > 0 and not product.active):
        raise not_found()
    item = await session.scalar(
        select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.store_id == actor.store_id,
            CartItem.product_id == product_id,
        )
    )
    if payload.quantity == 0:
        if item is not None:
            await session.delete(item)
    elif item is not None:
        item.quantity = payload.quantity
    else:
        count = await session.scalar(
            select(func.count())
            .select_from(CartItem)
            .where(
                CartItem.cart_id == cart.id,
                CartItem.store_id == actor.store_id,
            )
        )
        if count >= 20:
            raise DomainError(409, "CART_FULL", "购物车最多包含 20 件不同商品")
        session.add(
            CartItem(
                cart_id=cart.id,
                product_id=product_id,
                store_id=actor.store_id,
                quantity=payload.quantity,
            )
        )
    cart.version += 1
    await session.flush()
    return await snapshot(session, actor, cart)


async def lock_checkout_cart(session, actor, source):
    """Acquire cart before idempotency/proposal/product locks for cart checkout.

    CartItem INSERT has an implicit product FK KEY SHARE lock. Cart preparation
    can lock an existing proposal on duplicate-origin recovery. Cart must precede
    both, while the existing key/proposal/confirmation/sorted-products order stays.
    """
    if source is None:
        return None, None
    require_buyer(actor)
    try:
        source = CheckoutCartSource.model_validate(source)
    except ValidationError as error:
        raise DomainError(409, "STALE_PROPOSAL", "购物车来源快照无效，请重新生成提案") from error
    if source.user_id != actor.user_id or source.store_id != actor.store_id:
        raise not_found()
    cart = await session.scalar(
        select(Cart)
        .where(
            Cart.id == source.cart_id,
            Cart.user_id == actor.user_id,
            Cart.store_id == actor.store_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return source, cart


async def consume_checkout_cart(session, actor, source, items, cart):
    """Consume an already-locked cart, atomically with the order; replay skips it."""
    if source is None:
        return "NOT_APPLICABLE"
    if cart is None or cart.version != source.version:
        return "SKIPPED_CART_CHANGED"
    rows = list(
        await session.scalars(
            select(CartItem)
            .where(CartItem.cart_id == cart.id, CartItem.store_id == actor.store_id)
            .order_by(CartItem.product_id)
            .with_for_update()
        )
    )
    quoted = {i["product_id"]: i["quantity"] for i in items}
    if {str(i.product_id): i.quantity for i in rows} != quoted:
        return "SKIPPED_CART_CHANGED"
    # Delete the quoted products only, never unconditionally clear a user's cart.
    await session.execute(
        delete(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.store_id == actor.store_id,
            CartItem.product_id.in_([i.product_id for i in rows]),
        )
    )
    cart.version += 1
    await session.flush()
    return "CONSUMED"
