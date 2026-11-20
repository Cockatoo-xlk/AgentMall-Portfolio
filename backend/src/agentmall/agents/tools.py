"""Adapters own short sessions; the existing domain services own business rules."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from langchain_core.tools import StructuredTool
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from agentmall.actions import service as actions
from agentmall.actions.models import ActionProposal
from agentmall.agents.context import Constraints
from agentmall.agents.product_preferences import affirmative
from agentmall.agents.schemas import TOOL_SCHEMAS, PrepareInput, ProductInput, SearchInput
from agentmall.catalog import service as catalog
from agentmall.catalog.schemas import ProductCriteria, ProductFilters
from agentmall.identity.service import ActorContext, require_buyer
from agentmall.infra.errors import DomainError

SLOT = "agent_purchase"


def requests_available_products(message):
    request = (
        r"推荐(?!的|过)"
        r"|(?:只(?:要|看|找|选|列出|显示)|仅(?:限|看|选|列出|显示)|必须|要求|找|筛选|列出|显示)"
        r"(?:当前|现在|目前)?(?:有库存|有现货|有货|现货|在库|库存充足)"
    )
    return any(affirmative(message, match.start()) for match in re.finditer(request, message))


def search_criteria(
    constraints: Constraints,
    exclusions: Iterable[UUID],
    tool_max_price_cents: int | None = None,
    *,
    in_stock: bool = True,
) -> ProductCriteria:
    needs = constraints.product_needs
    bounds = (constraints.max_price_cents, needs.max_unit_price_cents, tool_max_price_cents)
    return ProductCriteria(
        category=constraints.category,
        max_price_cents=min((bound for bound in bounds if bound is not None), default=None),
        in_stock=in_stock,
        noise_preference=constraints.noise_preference,
        layout=needs.layout,
        screen_inches=needs.screen_inches,
        activity=needs.activity,
        product_kind=needs.product_kind,
        connection=needs.connection,
        excluded_connections=needs.excluded_connections,
        keyboard_type=needs.keyboard_type,
        exclude_product_ids=list(exclusions),
    )


@dataclass
class ToolContext:
    actor: ActorContext
    request_id: UUID
    sessions: object
    constraints: Constraints | None = None
    observed: dict = field(default_factory=dict)
    tool_errors: list = field(default_factory=list)
    available_products_requested: bool = False

    @property
    def requires_available_product(self):
        return self.available_products_requested or bool(
            self.constraints
            and (self.constraints.purchase_requested or self.constraints.recommendation)
        )

    async def recover(self):
        require_buyer(self.actor)
        async with self.sessions.begin() as session:
            pid = await session.scalar(
                select(ActionProposal.id).where(
                    ActionProposal.actor_id == self.actor.user_id,
                    ActionProposal.store_id == self.actor.store_id,
                    ActionProposal.origin_request_id == self.request_id,
                    ActionProposal.proposal_slot == SLOT,
                    ActionProposal.action_type == "CHECKOUT",
                )
            )
            return await actions.get_proposal(session, self.actor, pid) if pid else None

    async def execute(self, name, arguments):
        require_buyer(self.actor)
        args = TOOL_SCHEMAS[name].model_validate(arguments)
        try:
            async with self.sessions.begin() as session:
                if name == "search_products":
                    constraints = self.constraints or Constraints()
                    needs = constraints.product_needs
                    result = await catalog.search_products(
                        session,
                        self.actor,
                        ProductFilters(**args.model_dump()),
                        criteria=search_criteria(
                            constraints,
                            constraints.exclude_product_ids,
                            in_stock=self.requires_available_product,
                        ),
                        unit_price_cents=needs.unit_price_cents,
                        model_code=needs.model_code,
                    )
                    for product in result.items:
                        self.observed[str(product.id)] = product
                elif name == "get_product":
                    result = await catalog.get_product(session, self.actor, args.product_id)
                    if self.constraints and not self.constraints.matches_product(
                        result, require_stock=self.requires_available_product
                    ):
                        raise DomainError(409, "CONSTRAINT_MISMATCH", "商品不符合购买约束")
                    self.observed[str(result.id)] = result
                else:
                    if any(str(i.product_id) not in self.observed for i in args.items):
                        raise DomainError(409, "PRODUCT_NOT_OBSERVED", "请先查询商品")
                    if self.constraints:
                        total = 0
                        for item in args.items:
                            current = await catalog.get_product(
                                session, self.actor, item.product_id
                            )
                            if not self.constraints.matches_product(current):
                                raise DomainError(409, "CONSTRAINT_MISMATCH", "商品不符合购买约束")
                            total += current.price_cents * item.quantity
                        if (
                            self.constraints.max_price_cents is not None
                            and total > self.constraints.max_price_cents
                        ):
                            raise DomainError(409, "CONSTRAINT_MISMATCH", "不符合总预算")
                    result, _ = await actions.prepare_checkout(
                        session,
                        self.actor,
                        self.request_id,
                        SLOT,
                        args.items,
                        args.address_label,
                        f"agent:prepare:{self.request_id}",
                    )
                    # Check the exact snapshot prepared by T02, inside the same transaction.
                    # Any discrepancy rolls back BOTH the proposal and its idempotency row.
                    for item in result.canonical_payload["items"]:
                        seen = self.observed[item["product_id"]]
                        if (
                            item["unit_price_cents"] != seen.price_cents
                            or item["catalog_version"] != seen.catalog_version
                        ):
                            raise DomainError(
                                409, "PRODUCT_CHANGED_REQUOTE", "商品已变化，请重新报价"
                            )
            return {"ok": True, **result.model_dump(mode="json")}
        except DomainError as exc:
            code = exc.code
        except DBAPIError:
            code = "DATABASE_UNAVAILABLE"
        self.tool_errors.append(code)
        return {"ok": False, "error_code": code, "message": "操作未完成，请重新核对商品或提案"}


def build_tools(context):
    async def search_products(query=None, category=None, max_price_cents=None, limit=5):
        return await context.execute(
            "search_products",
            {
                "query": query,
                "category": category,
                "max_price_cents": max_price_cents,
                "limit": limit,
            },
        )

    async def get_product(product_id):
        return await context.execute("get_product", {"product_id": product_id})

    async def prepare_checkout(items, address_label):
        return await context.execute(
            "prepare_checkout", {"items": items, "address_label": address_label}
        )

    return [
        StructuredTool.from_function(
            coroutine=search_products,
            name="search_products",
            description="查询当前店铺在售商品，价格整数分，query为短关键词字面子串。",
            args_schema=SearchInput,
        ),
        StructuredTool.from_function(
            coroutine=get_product,
            name="get_product",
            description="读取当前店铺在售商品的价格、库存、属性和版本。",
            args_schema=ProductInput,
        ),
        StructuredTool.from_function(
            coroutine=prepare_checkout,
            name="prepare_checkout",
            description="为已查询商品创建购买提案；只报价，等待人工确认，不下单。必须独占工具批次。",
            args_schema=PrepareInput,
        ),
    ]
