import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmall.catalog.categories import Category, ProductKind, infer_category, infer_product_kind
from agentmall.catalog.schemas import ProductDTO

Mode = Literal["lexical", "vector", "hybrid"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    mode: Mode = "hybrid"


class ProductQuery(SearchQuery):
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

    @model_validator(mode="after")
    def infer_explicit_category(self):
        if self.category is None:
            self.category = infer_category(self.query)
        if self.screen_inches is None:
            screen = re.search(r"(?<!\d)(\d{1,2}(?:\.\d)?)\s*(?:英寸|寸)", self.query)
            if screen:
                self.screen_inches = screen[1]
        if self.activity is None and "公路车" in self.query:
            self.activity = "road_cycling"
        if self.product_kind is None:
            self.product_kind = infer_product_kind(self.query)
        return self


class PolicyQuery(SearchQuery):
    order_id: UUID | None = None


class SearchHit(BaseModel):
    id: UUID
    product: ProductDTO
    source_uri: str
    source_version: int
    score: float


class CitationChunk(BaseModel):
    id: UUID
    document_id: UUID
    title: str
    text: str
    section_id: str
    source_uri: str
    policy_version: str
    visibility: Literal["public"]
    score: float
    trusted: Literal[False] = False
