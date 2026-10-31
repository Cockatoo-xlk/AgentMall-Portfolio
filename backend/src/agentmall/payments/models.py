from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class Payment(Record, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payment_order"),
        UniqueConstraint("id", "order_id", "store_id", name="uq_payment_order_store"),
        UniqueConstraint("action_id", name="uq_payment_action"),
        ForeignKeyConstraint(["order_id", "store_id"], ["orders.id", "orders.store_id"]),
        CheckConstraint("amount_cents >= 0", name="ck_payment_amount"),
        CheckConstraint("status = 'SUCCEEDED'", name="ck_payment_status"),
        CheckConstraint("provider = 'mock'", name="ck_payment_provider"),
    )
    order_id: Mapped[UUID]
    store_id: Mapped[UUID]
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    action_id: Mapped[UUID] = mapped_column(ForeignKey("action_proposals.id"))
