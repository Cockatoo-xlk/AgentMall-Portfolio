from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class ActionProposal(Record, Base):
    __tablename__ = "action_proposals"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "origin_request_id", "proposal_slot", name="uq_proposal_request_slot"
        ),
        UniqueConstraint("id", "actor_id", "store_id", name="uq_proposal_scope"),
        CheckConstraint(
            "action_type IN ('CHECKOUT','MOCK_PAYMENT','CANCEL_ORDER',"
            "'RETURN_REQUEST','RETURN_CANCEL','MOCK_REFUND')",
            name="ck_proposal_action",
        ),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','EXECUTED','EXPIRED')",
            name="ck_proposal_status",
        ),
        CheckConstraint("schema_version = 1", name="ck_proposal_schema"),
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[UUID]
    action_type: Mapped[str] = mapped_column(String(30))
    canonical_payload: Mapped[dict] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    origin_request_id: Mapped[UUID]
    proposal_slot: Mapped[str] = mapped_column(String(64))


class Confirmation(Record, Base):
    __tablename__ = "confirmations"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_confirmation_proposal"),
        ForeignKeyConstraint(
            ["proposal_id", "actor_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        CheckConstraint("decision IN ('approve','reject')", name="ck_confirmation_decision"),
    )
    proposal_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    store_id: Mapped[UUID]
    decision: Mapped[str] = mapped_column(String(10))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_ref: Mapped[UUID | None]


class IdempotencyRequest(Record, Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (
        UniqueConstraint("store_id", "actor_id", "operation", "key", name="uq_idempotency_key"),
        UniqueConstraint("action_id", name="uq_idempotency_action"),
        ForeignKeyConstraint(
            ["action_id", "actor_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        CheckConstraint(
            "operation IN ('prepare_checkout','execute_checkout','prepare_mock_payment',"
            "'prepare_cancel_order','execute_mock_payment','execute_cancel_order',"
            "'prepare_return_request','execute_return_request','prepare_return_cancel',"
            "'execute_return_cancel','prepare_mock_refund','execute_mock_refund','create_support_ticket')",
            name="ck_idempotency_operation",
        ),
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(40))
    key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    action_id: Mapped[UUID | None]
    result: Mapped[dict | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
