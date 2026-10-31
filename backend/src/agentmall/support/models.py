from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class SupportTicket(Record, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("user_id", "store_id", "request_id", name="uq_ticket_request"),
        ForeignKeyConstraint(
            ["order_id", "user_id", "store_id"], ["orders.id", "orders.user_id", "orders.store_id"]
        ),
        ForeignKeyConstraint(
            ["case_id", "order_id", "store_id"],
            ["aftersales_cases.id", "aftersales_cases.order_id", "aftersales_cases.store_id"],
        ),
        CheckConstraint("status IN ('OPEN','IN_PROGRESS','RESOLVED')", name="ck_ticket_status"),
        CheckConstraint("version >= 1", name="ck_ticket_version"),
        CheckConstraint(
            "(order_id IS NOT NULL AND conversation_scope IS NULL) OR "
            "(order_id IS NULL AND case_id IS NULL "
            "AND conversation_scope IS NOT NULL "
            "AND conversation_scope = 'after_sales_question')",
            name="ck_ticket_scope",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('EXPLAINED','DECLINED','RETRY_ALLOWED')",
            name="ck_ticket_resolution",
        ),
        Index("ix_ticket_order_status", "order_id", "status"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[UUID]
    request_id: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[UUID | None]
    case_id: Mapped[UUID | None]
    conversation_scope: Mapped[str | None] = mapped_column(String(40))
    blocked_action_types: Mapped[list] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20))
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(String(30))
    resolution_summary: Mapped[str | None] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(server_default="1")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
