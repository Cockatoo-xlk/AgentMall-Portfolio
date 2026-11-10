from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class CatalogImport(Record, Base):
    __tablename__ = "catalog_imports"
    __table_args__ = (
        UniqueConstraint("store_id", "actor_id", "request_id", name="uq_catalog_import_request"),
    )
    store_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(8))
    source_hash: Mapped[str] = mapped_column(String(64))
    parser_mode: Mapped[str] = mapped_column(String(32))
    draft_ids: Mapped[list] = mapped_column(JSONB)
    errors: Mapped[list] = mapped_column(JSONB)


class ProductDraft(Record, Base):
    __tablename__ = "product_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','READY_FOR_REVIEW','APPROVED','REJECTED','PUBLISHED')",
            name="ck_draft_status",
        ),
        CheckConstraint("version>=1", name="ck_draft_version"),
    )
    store_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    import_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalog_imports.id"))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONB)
    source: Mapped[dict] = mapped_column(JSONB)
    extraction: Mapped[dict] = mapped_column(JSONB, default=dict)
    extraction_attempts: Mapped[int] = mapped_column(Integer, default=0)
    target_product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    target_version: Mapped[int | None]
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_version: Mapped[int | None]
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id"))
    index_job_id: Mapped[UUID | None]
    history: Mapped[list] = mapped_column(JSONB, default=list)


class CatalogCommand(Record, Base):
    __tablename__ = "catalog_commands"
    __table_args__ = (
        UniqueConstraint("store_id", "actor_id", "request_id", name="uq_catalog_command_request"),
    )
    store_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[UUID]
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(JSONB)


class CatalogIndexJob(Record, Base):
    __tablename__ = "catalog_index_jobs"
    __table_args__ = (
        UniqueConstraint("product_id", "requested_version", name="uq_catalog_index_version"),
        ForeignKeyConstraint(["product_id", "store_id"], ["products.id", "products.store_id"]),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','STALE')",
            name="ck_catalog_index_status",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_catalog_index_attempts"),
    )
    store_id: Mapped[UUID]
    product_id: Mapped[UUID]
    requested_version: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
