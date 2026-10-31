"""Chinese FTS and exact vectors, isolated from business data.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # Extension lives outside per-test schemas and survives their cleanup.
    op.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    op.execute("""DO $$ BEGIN
      IF NOT EXISTS (SELECT FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
                     WHERE e.extname='vector' AND n.nspname='extensions') THEN
        RAISE EXCEPTION 'vector must be provisioned in extensions schema';
      END IF;
    END $$""")
    op.execute("SELECT set_config('search_path', current_schema() || ',extensions', true)")

    def record():
        return [
            sa.Column("id", sa.UUID(), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        ]

    def embedding():
        return [
            sa.Column("embedding", Vector(512), nullable=False),
            sa.Column("embedding_model", sa.String(100), nullable=False),
            sa.Column("embedding_revision", sa.String(100), nullable=False),
            sa.Column("search_tsv", sa.dialects.postgresql.TSVECTOR(), nullable=False),
            sa.Column("tokenizer_version", sa.String(80), nullable=False),
        ]

    def checks(prefix):
        return [
            sa.CheckConstraint(
                "abs(extensions.vector_norm(embedding) - 1) < 0.0001", name=f"ck_{prefix}_norm"
            ),
            sa.CheckConstraint(
                "(embedding_model = 'BAAI/bge-small-zh-v1.5' AND "
                "embedding_revision = '7999e1d3359715c523056ef9478215996d62a620') OR "
                "(embedding_model = 'agentmall/fixture' AND embedding_revision = 'unit-v1')",
                name=f"ck_{prefix}_model",
            ),
        ]

    op.create_table(
        "knowledge_documents",
        *record(),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("source_uri", sa.String(500), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("store_id", "kind", "title", "version", name="uq_knowledge_version"),
        sa.CheckConstraint("visibility IN ('public','internal')", name="ck_knowledge_visibility"),
        sa.CheckConstraint("kind = 'policy'", name="ck_knowledge_kind"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_knowledge_dates"),
    )
    op.create_index(
        "ix_knowledge_scope", "knowledge_documents", ["store_id", "version", "visibility"]
    )
    op.create_table(
        "knowledge_chunks",
        *record(),
        *embedding(),
        sa.Column(
            "document_id", sa.UUID(), sa.ForeignKey("knowledge_documents.id"), nullable=False
        ),
        sa.Column("section_id", sa.String(80), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_id", "section_id", name="uq_chunk_section"),
        sa.CheckConstraint("token_count > 0", name="ck_chunk_tokens"),
        *checks("chunk"),
    )
    op.create_index("ix_chunks_fts", "knowledge_chunks", ["search_tsv"], postgresql_using="gin")
    op.create_table(
        "product_search",
        *embedding(),
        sa.Column("product_id", sa.UUID(), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("source_version >= 1", name="ck_product_search_version"),
        *checks("product_search"),
    )
    op.create_index(
        "ix_product_search_fts", "product_search", ["search_tsv"], postgresql_using="gin"
    )
    # Keep policy source immutable, while permitting vector/tokenizer rebuilds.
    op.execute("""CREATE FUNCTION immutable_knowledge() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'knowledge_documents' OR
         (NEW.document_id,NEW.section_id,NEW.text) IS DISTINCT FROM
         (OLD.document_id,OLD.section_id,OLD.text) THEN
        RAISE EXCEPTION 'policy source is immutable; create a new version' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    for table in ("knowledge_documents", "knowledge_chunks"):
        op.execute(
            f"CREATE TRIGGER immutable_source BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION immutable_knowledge()"
        )


def downgrade():
    op.drop_table("product_search")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.execute("DROP FUNCTION immutable_knowledge()")
    # Shared extension and other schemas are deliberately retained.
