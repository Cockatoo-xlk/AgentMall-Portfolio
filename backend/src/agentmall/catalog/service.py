from sqlalchemy import func, or_, select

from agentmall.catalog.capabilities import connection_conditions
from agentmall.catalog.categories import KIND_ATTRIBUTES, bare_category, model_code_pattern
from agentmall.catalog.models import Product
from agentmall.catalog.schemas import ProductCriteria, ProductDTO, ProductFilters, ProductPage
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


def product_conditions(
    filters: ProductCriteria | None,
    *,
    unit_price_cents: int | None = None,
    model_code: str | None = None,
):
    """Qualify current product facts before pagination or either ranked recall."""
    conditions = []
    if unit_price_cents is not None:
        conditions.append(Product.price_cents == unit_price_cents)
    if model_code is not None:
        conditions.append(Product.name.op("~*")(model_code_pattern(model_code)))
    if filters is None:
        return conditions
    if filters.product_kind:
        category, attribute, term = KIND_ATTRIBUTES[filters.product_kind]
        conditions.extend(
            [
                Product.category == category,
                func.jsonb_typeof(Product.attributes[attribute]) == "string",
                Product.attributes[attribute].as_string().icontains(term, autoescape=True),
            ]
        )
    if filters.category:
        conditions.append(Product.category == filters.category)
    if filters.max_price_cents is not None:
        conditions.append(Product.price_cents <= filters.max_price_cents)
    if filters.in_stock:
        conditions.append(Product.on_hand > Product.reserved)
    if filters.usage:
        conditions.append(
            Product.attributes["usage"].as_string().icontains(filters.usage, autoescape=True)
        )
    if filters.screen_inches is not None:
        conditions.append(Product.attributes["screen_inches"].as_string() == filters.screen_inches)
    if filters.activity == "road_cycling":
        conditions.append(Product.attributes["usage"].as_string() == "公路车骑行")
    if filters.noise_preference:
        conditions.append(Product.attributes["noise"].as_string() == "较安静")
    if filters.layout:
        conditions.append(Product.attributes["size"].as_string() == filters.layout)
    conditions.extend(
        connection_conditions(Product.attributes, filters.connection, filters.excluded_connections)
    )
    if filters.exclude_product_ids:
        conditions.append(Product.id.not_in(filters.exclude_product_ids))
    if filters.keyboard_type:
        switches = (
            ["薄膜"]
            if filters.keyboard_type == "membrane"
            else ["静音轴", "线性轴", "段落轴", "青轴", "茶轴", "红轴"]
        )
        conditions.append(Product.attributes["switch"].as_string().in_(switches))
    return conditions


async def search_products(
    session,
    actor: ActorContext,
    filters: ProductFilters,
    *,
    unit_price_cents: int | None = None,
    model_code: str | None = None,
    criteria: ProductCriteria | None = None,
) -> ProductPage:
    query = select(Product).where(
        Product.store_id == actor.store_id,
        Product.active.is_(True),
        *product_conditions(criteria, unit_price_cents=unit_price_cents, model_code=model_code),
    )
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
