from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class AfterSalesCase(Record, Base):
    __tablename__ = "aftersales_cases"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_case_proposal"),
        UniqueConstraint("id", "order_id", "store_id", name="uq_case_order_store"),
        ForeignKeyConstraint(
            ["order_id", "user_id", "store_id"], ["orders.id", "orders.user_id", "orders.store_id"]
        ),
        ForeignKeyConstraint(
            ["proposal_id", "user_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        CheckConstraint(
            "status IN ('REQUESTED','APPROVED','RECEIVED','REFUNDED','REJECTED','CANCELLED')",
            name="ck_case_status",
        ),
        CheckConstraint("version >= 1", name="ck_case_version"),
        CheckConstraint("restockable = false", name="ck_case_no_restock"),
        Index(
            "uq_case_active_order",
            "order_id",
            unique=True,
            postgresql_where=text("status NOT IN ('REJECTED','CANCELLED')"),
        ),
    )
    order_id: Mapped[UUID]
    user_id: Mapped[UUID]
    store_id: Mapped[UUID]
    proposal_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(1000))
    policy_version: Mapped[str] = mapped_column(String(40))
    eligibility_snapshot: Mapped[dict] = mapped_column(JSONB)
    restockable: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(server_default="1")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(String(1000))
    received_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Refund(Record, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_refund_case"),
        UniqueConstraint("payment_id", name="uq_refund_payment"),
        UniqueConstraint("action_id", name="uq_refund_action"),
        ForeignKeyConstraint(
            ["case_id", "order_id", "store_id"],
            ["aftersales_cases.id", "aftersales_cases.order_id", "aftersales_cases.store_id"],
        ),
        ForeignKeyConstraint(
            ["payment_id", "order_id", "store_id"],
            ["payments.id", "payments.order_id", "payments.store_id"],
        ),
        CheckConstraint("amount_cents >= 0", name="ck_refund_amount"),
        CheckConstraint("status = 'SUCCEEDED'", name="ck_refund_status"),
    )
    case_id: Mapped[UUID]
    order_id: Mapped[UUID]
    store_id: Mapped[UUID]
    payment_id: Mapped[UUID]
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    action_id: Mapped[UUID] = mapped_column(ForeignKey("action_proposals.id"))
