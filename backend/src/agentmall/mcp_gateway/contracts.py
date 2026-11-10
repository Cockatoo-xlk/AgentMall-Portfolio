from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model

from agentmall.aftersales.schemas import CaseDTO, CaseStatus, ReasonCode
from agentmall.catalog.categories import Category
from agentmall.catalog_operations.schemas import DraftCreate, ProductData
from agentmall.orders.schemas import OrderDTO, OrderStatus


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Search(Strict):
    query: str = Field("", max_length=500, strict=True)
    category: Category | None = None
    max_price_cents: int | None = Field(None, ge=0, le=100_000_000, strict=True)
    limit: int = Field(10, ge=1, le=20, strict=True)
    cursor: UUID | None = None


class ProductID(Strict):
    product_id: UUID


class Orders(Strict):
    status: OrderStatus | None = None
    cursor: UUID | None = None
    limit: int = Field(10, ge=1, le=20, strict=True)


class OrderID(Strict):
    order_id: UUID


class Eligibility(OrderID):
    reason_code: ReasonCode = "QUALITY_ISSUE"


class Policy(Strict):
    order_id: UUID | None = None
    policy_version: str | None = Field(
        None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$"
    )


class MerchantCatalog(Strict):
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    category: Category | None = None
    cursor: UUID | None = None
    limit: int = Field(10, ge=1, le=20, strict=True)


class Cases(Strict):
    status: CaseStatus | None = None
    cursor: UUID | None = None
    limit: int = Field(10, ge=1, le=20, strict=True)


class DraftReceipt(Strict):
    draft_id: UUID
    status: Literal["DRAFT"]
    version: int


class MerchantProduct(ProductData):
    id: UUID
    catalog_version: int
    reserved: int
    available: int
    active: bool
    index_status: Literal["INACTIVE", "INDEXED_CURRENT", "NOT_INDEXED_CURRENT"]


class Page[T](Strict):
    items: list[T]
    next_cursor: UUID | None


class Citation(Strict):
    document_id: UUID
    title: str
    text: str
    source_uri: str
    policy_version: str


class Policies(Strict):
    items: list[Citation]
    informational_only: Literal[True] = True


class Failure(Strict):
    code: str
    message: str
    retryable: bool = False
    outcome: Literal["NOT_EXECUTED", "UNKNOWN"] = "NOT_EXECUTED"


class Result[T](Strict):
    ok: bool
    data: T | None = None
    error: Failure | None = None


# Keep the V2.7 command schema and its field/owner restrictions unchanged.
CreateDraft = DraftCreate


def _view(name, domain_model, hidden):
    # Reuse authoritative DTO field types, defaults and enums, with an explicit
    # MCP projection. These classes never query or authorize business objects.
    return create_model(
        name,
        __base__=Strict,
        **{
            key: (field.annotation, deepcopy(field))
            for key, field in domain_model.model_fields.items()
            if key not in hidden
        },
    )


ORDER_INTERNAL = {"user_id", "store_id", "proposal_id"}
CASE_INTERNAL = ORDER_INTERNAL | {
    "reviewed_by",
    "received_by",
    "description",
    "review_reason",
    "eligibility_snapshot",
}
OrderInfo = _view("OrderInfo", OrderDTO, ORDER_INTERNAL)
CaseInfo = _view("CaseInfo", CaseDTO, CASE_INTERNAL)


def project(value, model):
    return model.model_validate(
        {k: v for k, v in value.model_dump().items() if k in model.model_fields}
    )
