from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmall.aftersales.schemas import (
    RefundPayload,
    RefundReceipt,
    ReturnCancelPayload,
    ReturnPayload,
    ReturnReceipt,
)
from agentmall.cart.schemas import CartConsumption

PositiveQuantity = Annotated[int, Field(strict=True, ge=1, le=10)]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class ItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    quantity: PositiveQuantity


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    proposal_slot: str = Field(
        default="checkout", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    items: list[ItemRequest] | None = Field(default=None, min_length=1, max_length=20)
    cart_id: UUID | None = None
    expected_cart_version: int | None = Field(default=None, strict=True, ge=0)
    address_label: Literal["demo_dorm", "demo_home"]

    @model_validator(mode="after")
    def exactly_one_source(self):
        if self.items is not None:
            if self.cart_id is not None or self.expected_cart_version is not None:
                raise ValueError("Choose explicit items OR cart with expected version")
        elif self.cart_id is None or self.expected_cart_version is None:
            raise ValueError("A cart id and expected version are both required")
        return self


class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


class ConfirmationDTO(BaseModel):
    confirmation_id: UUID
    proposal_id: UUID
    decision: Literal["approve", "reject"]
    decided_at: datetime
    consumed_at: datetime | None
    result_ref: UUID | None


class ActionReceipt(BaseModel):
    # Missing on historical receipts; never infer historical cart consumption.
    cart_consumption: CartConsumption | None = None
    action_id: UUID
    resource_id: UUID
    order_id: UUID
    status: Literal["PENDING_PAYMENT"]
    total_cents: int
    currency: Literal["CNY"] = "CNY"
    created_at: datetime


class OrderActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    proposal_slot: str = Field(
        default="order_action", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    expected_version: int = Field(strict=True, ge=1)


class OrderActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    order_id: UUID
    expected_version: int = Field(strict=True, ge=1)
    total_cents: int = Field(strict=True, ge=0)
    currency: Literal["CNY"]
    policy_version: str


class PaymentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["MOCK_PAYMENT"] = "MOCK_PAYMENT"
    action_id: UUID
    resource_id: UUID
    order_id: UUID
    payment_id: UUID | None
    status: Literal["SUCCEEDED", "DECLINED", "EXPIRED"]
    order_status: Literal["PAID", "PENDING_PAYMENT", "EXPIRED"]
    total_cents: int
    currency: Literal["CNY"] = "CNY"
    created_at: datetime


class CancelReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["CANCEL_ORDER"] = "CANCEL_ORDER"
    action_id: UUID
    resource_id: UUID
    order_id: UUID
    status: Literal["CANCELLED", "EXPIRED"]
    total_cents: int
    currency: Literal["CNY"] = "CNY"
    created_at: datetime


class ProposalDTO(BaseModel):
    proposal_id: UUID
    action_type: Literal[
        "CHECKOUT", "MOCK_PAYMENT", "CANCEL_ORDER", "RETURN_REQUEST", "RETURN_CANCEL", "MOCK_REFUND"
    ]
    canonical_payload: dict
    payload_hash: str
    schema_version: int
    expires_at: datetime
    status: Literal["PENDING", "APPROVED", "REJECTED", "EXECUTED", "EXPIRED"]
    confirmation: ConfirmationDTO | None
    result: ActionReceipt | PaymentReceipt | CancelReceipt | ReturnReceipt | RefundReceipt | None

    @model_validator(mode="after")
    def validate_order_action_snapshot(self):
        # Preserve the T02 checkout dictionary API; new actions are strictly typed.
        validators = {
            "MOCK_PAYMENT": OrderActionPayload,
            "CANCEL_ORDER": OrderActionPayload,
            "RETURN_REQUEST": ReturnPayload,
            "RETURN_CANCEL": ReturnCancelPayload,
            "MOCK_REFUND": RefundPayload,
        }
        if self.action_type in validators:
            validators[self.action_type].model_validate(self.canonical_payload)
        return self
