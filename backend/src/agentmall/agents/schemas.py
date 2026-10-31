from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentmall.actions.schemas import ItemRequest
from agentmall.catalog.schemas import Category


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(StrictInput):
    query: str | None = Field(default=None, max_length=100, strict=True)
    category: Category | None = None
    max_price_cents: int | None = Field(default=None, strict=True, ge=0, le=100_000_000)
    limit: int = Field(default=5, strict=True, ge=1, le=20)


class ProductInput(StrictInput):
    product_id: UUID


class PrepareInput(StrictInput):
    items: list[ItemRequest] = Field(min_length=1, max_length=20)
    address_label: Literal["demo_dorm", "demo_home"]


TOOL_SCHEMAS = {
    "search_products": SearchInput,
    "get_product": ProductInput,
    "prepare_checkout": PrepareInput,
}


class AgentRequest(StrictInput):
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000, strict=True)


class ResourceRef(StrictInput):
    type: Literal["product", "order"]
    id: UUID


class AgentResponse(StrictInput):
    answer: str
    proposal_refs: list[UUID] = Field(default_factory=list)
    resource_refs: list[ResourceRef] = Field(default_factory=list)
    status: Literal["done", "needs_input", "proposal", "blocked", "error"]
