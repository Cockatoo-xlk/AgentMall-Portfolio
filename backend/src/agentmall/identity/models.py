from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class User(Record, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('buyer','merchant')", name="ck_users_role"),
        CheckConstraint("role != 'merchant' OR store_id IS NOT NULL", name="ck_merchant_store"),
    )
    login: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    store_id: Mapped[UUID | None]
    disabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
