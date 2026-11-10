from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReasonCode = Literal[
    "QUALITY_ISSUE",
    "NOT_NEEDED",
    "QUALITY_DISPUTE",
    "POLICY_DISPUTE",
    "INSUFFICIENT_INFORMATION",
    "OTHER",
]
CaseStatus = Literal["REQUESTED", "APPROVED", "RECEIVED", "REFUNDED", "REJECTED", "CANCELLED"]


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class EligibilityResult(StrictDTO):
    eligible: bool
    reason_codes: list[str]
    requires_human: bool
    policy_version: str


class CaseActionRequest(StrictDTO):
    request_id: UUID
    expected_version: int = Field(strict=True, ge=1)
    proposal_slot: str = Field(
        default="aftersales", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    )


class ReturnRequest(CaseActionRequest):
    order_id: UUID
    reason_code: ReasonCode
    description: str = Field(min_length=1, max_length=1000)


class ReturnPayload(StrictDTO):
    schema_version: Literal[1]
    order_id: UUID
    expected_order_version: int = Field(strict=True, ge=1)
    reason_code: ReasonCode
    description: str = Field(min_length=1, max_length=1000)
    policy_version: str
    eligibility_snapshot: EligibilityResult


class ReturnCancelPayload(StrictDTO):
    schema_version: Literal[1]
    order_id: UUID
    case_id: UUID
    expected_version: int = Field(strict=True, ge=1)
    policy_version: str


class RefundPayload(ReturnCancelPayload):
    payment_id: UUID
    expected_order_version: int = Field(strict=True, ge=1)
    amount_cents: int = Field(strict=True, ge=0)
    currency: Literal["CNY"]


class ReturnReceipt(StrictDTO):
    action_type: Literal["RETURN_REQUEST", "RETURN_CANCEL"]
    action_id: UUID
    resource_id: UUID
    case_id: UUID
    order_id: UUID
    status: Literal["REQUESTED", "CANCELLED"]
    created_at: datetime


class RefundReceipt(StrictDTO):
    action_type: Literal["MOCK_REFUND"] = "MOCK_REFUND"
    action_id: UUID
    resource_id: UUID
    refund_id: UUID
    case_id: UUID
    order_id: UUID
    payment_id: UUID
    amount_cents: int = Field(strict=True, ge=0)
    currency: Literal["CNY"] = "CNY"
    status: Literal["SUCCEEDED"] = "SUCCEEDED"
    order_status: Literal["REFUNDED"] = "REFUNDED"
    created_at: datetime


class CaseDTO(StrictDTO):
    id: UUID
    order_id: UUID
    user_id: UUID
    store_id: UUID
    proposal_id: UUID
    status: CaseStatus
    reason_code: ReasonCode
    description: str
    policy_version: str
    eligibility_snapshot: EligibilityResult
    restockable: Literal[False]
    version: int
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_reason: str | None
    received_by: UUID | None
    received_at: datetime | None
    refunded_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CaseFilters(StrictDTO):
    status: CaseStatus | None = None
    cursor: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CasePage(StrictDTO):
    items: list[CaseDTO]
    next_cursor: UUID | None


class ReviewRequest(StrictDTO):
    expected_version: int = Field(strict=True, ge=1)
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=1000)


class ReceiveRequest(StrictDTO):
    expected_version: int = Field(strict=True, ge=1)
