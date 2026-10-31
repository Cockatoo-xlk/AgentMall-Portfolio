from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class Cart(Record, Base):
    __tablename__ = "carts"
    __table_args__ = (
        UniqueConstraint("user_id", "store_id", name="uq_carts_user_store"),
        UniqueConstraint("id", "store_id", name="uq_carts_id_store"),
        CheckConstraint("version >= 0", name="ck_carts_version"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(server_default="0")


class CartItem(Record, Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        CheckConstraint("quantity BETWEEN 1 AND 10", name="ck_cart_items_quantity"),
        ForeignKeyConstraint(["cart_id", "store_id"], ["carts.id", "carts.store_id"]),
        ForeignKeyConstraint(["product_id", "store_id"], ["products.id", "products.store_id"]),
    )
    cart_id: Mapped[UUID]
    product_id: Mapped[UUID]
    store_id: Mapped[UUID]
    quantity: Mapped[int]
