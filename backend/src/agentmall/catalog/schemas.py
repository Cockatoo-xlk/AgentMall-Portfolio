from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentmall.catalog.categories import Category  # noqa: F401 - shared public type


class ProductFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, max_length=500)
    category: Category | None = None
    max_price_cents: int | None = Field(default=None, ge=0)
    cursor: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ProductDTO(BaseModel):
    id: UUID
    name: str
    category: Category
    attributes: dict
    description: str
    price_cents: int
    currency: Literal["CNY"] = "CNY"
    available: int
    catalog_version: int


class ProductPage(BaseModel):
    items: list[ProductDTO]
    next_cursor: UUID | None
