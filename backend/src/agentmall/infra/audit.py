from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base


class BusinessEvent(Base):
    __tablename__ = "business_events"
    __table_args__ = (UniqueConstraint("action_id", "event_type", name="uq_business_action_event"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(30))
    aggregate_id: Mapped[UUID]
    action_id: Mapped[UUID | None] = mapped_column(ForeignKey("action_proposals.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    payload_summary: Mapped[dict] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


async def write_order_event(session, order, occurred_at):
    session.add(
        BusinessEvent(
            aggregate_type="order",
            aggregate_id=order.id,
            action_id=order.proposal_id,
            event_type="ORDER_CREATED",
            payload_summary={"status": order.status, "total_cents": order.total_cents},
            occurred_at=occurred_at,
        )
    )
    await session.flush()
