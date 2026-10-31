from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class Order(Record, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_order_proposal"),
        UniqueConstraint("id", "store_id", name="uq_order_store"),
        UniqueConstraint("id", "user_id", "store_id", name="uq_order_owner_store"),
        ForeignKeyConstraint(
            ["proposal_id", "user_id", "store_id"],
            ["action_proposals.id", "action_proposals.actor_id", "action_proposals.store_id"],
        ),
        CheckConstraint(
            "status IN ('PENDING_PAYMENT','PAID','CANCELLED','EXPIRED',"
            "'SHIPPED','DELIVERED','REFUNDED')",
            name="ck_order_status",
        ),
        CheckConstraint("currency = 'CNY'", name="ck_order_currency"),
        CheckConstraint("total_cents >= 0", name="ck_order_total"),
        CheckConstraint("version >= 1", name="ck_order_version"),
        CheckConstraint("address_label IN ('demo_dorm','demo_home')", name="ck_order_address"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_status_expires", "status", "expires_at"),
    )
    user_id: Mapped[UUID]
    store_id: Mapped[UUID]
    proposal_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(30))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    address_label: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(server_default="1")
    policy_version: Mapped[str] = mapped_column(String(40))


class OrderItem(Record, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_item_product"),
        ForeignKeyConstraint(["order_id", "store_id"], ["orders.id", "orders.store_id"]),
        ForeignKeyConstraint(["product_id", "store_id"], ["products.id", "products.store_id"]),
        CheckConstraint("quantity BETWEEN 1 AND 10", name="ck_order_item_quantity"),
        CheckConstraint("unit_price_cents >= 0", name="ck_order_item_price"),
    )
    order_id: Mapped[UUID]
    store_id: Mapped[UUID]
    product_id: Mapped[UUID]
    name_snapshot: Mapped[str] = mapped_column(String(200))
    unit_price_cents: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int]
    attributes_snapshot: Mapped[dict] = mapped_column(JSONB)
