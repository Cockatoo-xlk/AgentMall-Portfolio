from sqlalchemy import or_, select

from agentmall.catalog.categories import bare_category
from agentmall.catalog.models import Product
from agentmall.catalog.schemas import ProductDTO, ProductFilters, ProductPage
from agentmall.identity.service import ActorContext
from agentmall.infra.errors import not_found


def product_dto(product: Product) -> ProductDTO:
    return ProductDTO(
        id=product.id,
        name=product.name,
        category=product.category,
        attributes=product.attributes,
        description=product.description,
        price_cents=product.price_cents,
        available=product.on_hand - product.reserved,
        catalog_version=product.catalog_version,
    )


async def search_products(session, actor: ActorContext, filters: ProductFilters) -> ProductPage:
    query = select(Product).where(Product.store_id == actor.store_id, Product.active.is_(True))
    if filters.query:
        inferred = bare_category(filters.query)
        query = query.where(
            or_(
                Product.name.icontains(filters.query, autoescape=True),
                Product.description.icontains(filters.query, autoescape=True),
                Product.category == inferred if inferred else False,
            )
        )
    if filters.category:
        query = query.where(Product.category == filters.category)
    if filters.max_price_cents is not None:
        query = query.where(Product.price_cents <= filters.max_price_cents)
    if filters.cursor:
        query = query.where(Product.id > filters.cursor)
    rows = list(await session.scalars(query.order_by(Product.id).limit(filters.limit + 1)))
    return ProductPage(
        items=[product_dto(p) for p in rows[: filters.limit]],
        next_cursor=rows[filters.limit - 1].id if len(rows) > filters.limit else None,
    )


async def get_product(session, actor: ActorContext, product_id) -> ProductDTO:
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id, Product.store_id == actor.store_id, Product.active.is_(True)
        )
    )
    if product is None:
        raise not_found()
    return product_dto(product)
