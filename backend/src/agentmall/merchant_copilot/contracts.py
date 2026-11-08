from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(Strict):
    question: str = Field(min_length=1, max_length=500, strict=True)
    case_id: UUID | None = None
    max_pages: int = Field(2, ge=1, le=5, strict=True)


ReadTool = Literal[
    "list_merchant_orders",
    "get_merchant_order",
    "list_merchant_after_sales",
    "get_merchant_after_sales",
    "list_merchant_products",
    "list_catalog_index_jobs",
    "get_applicable_policy",
]


class ToolCall(Strict):
    name: ReadTool
    arguments: dict = Field(default_factory=dict)


class Plan(Strict):
    calls: list[ToolCall] = Field(default_factory=list, max_length=6)
    clarification: Literal["SELECT_CASE", "UNSUPPORTED_QUESTION"] | None = None


class PageArgs(Strict):
    status: str | None = Field(None, max_length=30)
    limit: int = Field(20, ge=1, le=20, strict=True)
    cursor: UUID | None = None


class OrderID(Strict):
    order_id: UUID


class CaseID(Strict):
    case_id: UUID


class PolicyArgs(Strict):
    case_id: UUID | None = None


class Selection(Strict):
    evidence_id: str = Field(min_length=1, max_length=160)
    action: Literal["SHIP", "REVIEW", "RESTOCK", "CHECK_INDEX"]


class Advice(Strict):
    selections: list[Selection] = Field(default_factory=list, max_length=20)
    draft_tone: Literal["NEUTRAL", "EMPATHETIC"] = "NEUTRAL"


class EvidenceRef(Strict):
    case_id: UUID | None = None
    kind: Literal["order", "case", "product", "index_job", "policy"]
    id: UUID
    fingerprint: str = Field(pattern="^[a-f0-9]{64}$")


class CheckRequest(Strict):
    references: list[EvidenceRef] = Field(min_length=1, max_length=40)
