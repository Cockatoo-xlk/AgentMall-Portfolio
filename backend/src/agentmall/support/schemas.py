from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TicketReason = Literal[
    "NOT_ELIGIBLE", "POLICY_DISPUTE", "INSUFFICIENT_INFORMATION", "QUALITY_DISPUTE", "EXPLANATION"
]
Resolution = Literal["EXPLAINED", "DECLINED", "RETRY_ALLOWED"]


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    order_id: UUID | None = None
    case_id: UUID | None = None
    conversation_scope: Literal["after_sales_question"] | None = None
    reason: TicketReason
    summary: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def one_scope(self):
        if sum(v is not None for v in (self.order_id, self.case_id, self.conversation_scope)) != 1:
            raise ValueError("Exactly one verified object or conversation scope is required")
        return self


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=1)
    resolution: Resolution
    summary: str = Field(min_length=1, max_length=1000)


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=1)


class TicketDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID
    request_id: UUID
    user_id: UUID
    store_id: UUID
    order_id: UUID | None
    case_id: UUID | None
    conversation_scope: Literal["after_sales_question"] | None
    blocked_action_types: list[
        Literal["RETURN_REQUEST", "RETURN_CANCEL", "MOCK_REFUND", "REVIEW_CASE", "RECEIVE_CASE"]
    ]
    reason: TicketReason
    summary: str
    status: Literal["OPEN", "IN_PROGRESS", "RESOLVED"]
    assigned_to: UUID | None
    resolution: Resolution | None
    resolution_summary: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
