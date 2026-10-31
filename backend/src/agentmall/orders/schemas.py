from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal[
    "PENDING_PAYMENT", "PAID", "CANCELLED", "EXPIRED", "SHIPPED", "DELIVERED", "REFUNDED"
]


class ExecuteOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    confirmation_id: UUID


class OrderItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: UUID
    name_snapshot: str
    unit_price_cents: int
    quantity: int
    attributes_snapshot: dict


class OrderDTO(BaseModel):
    id: UUID
    user_id: UUID
    store_id: UUID
    proposal_id: UUID
    status: OrderStatus
    total_cents: int
    currency: Literal["CNY"]
    address_label: Literal["demo_dorm", "demo_home"]
    expires_at: datetime
    created_at: datetime
    paid_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    version: int
    policy_version: str
    items: list[OrderItemDTO]


class OrderFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: OrderStatus | None = None
    cursor: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class OrderPage(BaseModel):
    items: list[OrderDTO]
    next_cursor: UUID | None


class ShipmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=1)


class ShipmentEvent(BaseModel):
    status: Literal["PAID", "SHIPPED", "DELIVERED"]
    occurred_at: datetime


class ShipmentDTO(BaseModel):
    order_id: UUID
    status: OrderStatus
    events: list[ShipmentEvent]


class ExpiryResult(BaseModel):
    order_id: UUID
    status: OrderStatus
    changed: bool
