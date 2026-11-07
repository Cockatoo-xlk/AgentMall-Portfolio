from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.catalog.categories import CATEGORIES
from agentmall.infra.db import Base, Record


class Product(Record, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("0 <= reserved AND reserved <= on_hand", name="ck_products_inventory"),
        CheckConstraint("price_cents >= 0", name="ck_products_price"),
        CheckConstraint("catalog_version >= 1", name="ck_products_version"),
        CheckConstraint(
            "category IN (" + ",".join(repr(c) for c in CATEGORIES) + ")",
            name="ck_products_category",
        ),
        UniqueConstraint("id", "store_id", name="uq_products_id_store"),
        Index("ix_products_public_filter", "store_id", "active", "category", "price_cents"),
    )
    store_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30))
    attributes: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    description: Mapped[str] = mapped_column(server_default="")
    price_cents: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    on_hand: Mapped[int] = mapped_column(server_default="0")
    reserved: Mapped[int] = mapped_column(server_default="0")
    catalog_version: Mapped[int] = mapped_column(server_default="1")
