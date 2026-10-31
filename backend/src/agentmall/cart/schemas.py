from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Version = Annotated[int, Field(strict=True, ge=0)]
Quantity = Annotated[int, Field(strict=True, ge=0, le=10)]


class NoQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeleteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Version


class SetQuantity(DeleteItem):
    quantity: Quantity


class CartItemDTO(BaseModel):
    product_id: UUID
    quantity: int
    name: str
    unit_price_cents: int
    available: int
    active: bool


class CartDTO(BaseModel):
    id: UUID
    user_id: UUID
    store_id: UUID
    version: int
    items: list[CartItemDTO]
