from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentmall.catalog.categories import Category, ProductKind


class ProductCriteria(BaseModel):
    """Structured product filters shared by catalog pages and ranked retrieval."""

    model_config = ConfigDict(extra="forbid")
    category: Category | None = None
    screen_inches: str | None = Field(None, pattern=r"^\d{1,2}(?:\.\d)?$", max_length=4)
    usage: Literal["办公", "游戏", "宿舍"] | None = None
    activity: Literal["road_cycling"] | None = None
    product_kind: ProductKind | None = None
    max_price_cents: int | None = Field(None, ge=0)
    in_stock: bool = True
    noise_preference: Literal["quiet"] | None = None
    layout: str | None = Field(None, max_length=20)
    connection: Literal["有线", "无线", "双模", "三模"] | None = None
    excluded_connections: list[Literal["双模", "三模"]] = Field(default_factory=list, max_length=2)
    keyboard_type: Literal["mechanical", "membrane"] | None = None
    exclude_product_ids: list[UUID] = Field(default_factory=list, max_length=40)


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
