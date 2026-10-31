from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class KnowledgeDocument(Record, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("store_id", "kind", "title", "version", name="uq_knowledge_version"),
        CheckConstraint("visibility IN ('public','internal')", name="ck_knowledge_visibility"),
        CheckConstraint("kind = 'policy'", name="ck_knowledge_kind"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_knowledge_dates"),
        Index("ix_knowledge_scope", "store_id", "version", "visibility"),
    )
    store_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    visibility: Mapped[str] = mapped_column(String(20))
    version: Mapped[str] = mapped_column(String(40))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_uri: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))


class EmbeddingColumns:
    embedding: Mapped[list[float]] = mapped_column(Vector(512))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_revision: Mapped[str] = mapped_column(String(100))
    search_tsv: Mapped[str] = mapped_column(TSVECTOR)
    tokenizer_version: Mapped[str] = mapped_column(String(80))


def embedding_checks(prefix):
    return (
        CheckConstraint(
            "abs(extensions.vector_norm(embedding) - 1) < 0.0001", name=f"ck_{prefix}_norm"
        ),
        CheckConstraint(
            "(embedding_model = 'BAAI/bge-small-zh-v1.5' AND "
            "embedding_revision = '7999e1d3359715c523056ef9478215996d62a620') OR "
            "(embedding_model = 'agentmall/fixture' AND embedding_revision = 'unit-v1')",
            name=f"ck_{prefix}_model",
        ),
    )


class KnowledgeChunk(Record, EmbeddingColumns, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "section_id", name="uq_chunk_section"),
        CheckConstraint("token_count > 0", name="ck_chunk_tokens"),
        Index("ix_chunks_fts", "search_tsv", postgresql_using="gin"),
        *embedding_checks("chunk"),
    )
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"))
    section_id: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int]


class ProductSearch(EmbeddingColumns, Base):
    __tablename__ = "product_search"
    __table_args__ = (
        CheckConstraint("source_version >= 1", name="ck_product_search_version"),
        Index("ix_product_search_fts", "search_tsv", postgresql_using="gin"),
        *embedding_checks("product_search"),
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), primary_key=True)
    source_version: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64))
