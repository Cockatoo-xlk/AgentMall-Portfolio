"""Merchant drafts and explicit, versioned indexing jobs; no seed or product rewrite."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "catalog_imports",
        *common(),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("parser_mode", sa.String(32), nullable=False),
        sa.Column("draft_ids", JSONB(), nullable=False),
        sa.Column("errors", JSONB(), nullable=False),
        sa.UniqueConstraint("store_id", "actor_id", "request_id", name="uq_catalog_import_request"),
    )
    op.create_table(
        "product_drafts",
        *common(),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("import_id", sa.UUID(), sa.ForeignKey("catalog_imports.id")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("source", JSONB(), nullable=False),
        sa.Column("extraction", JSONB(), nullable=False),
        sa.Column("extraction_attempts", sa.Integer(), nullable=False),
        sa.Column("target_product_id", sa.UUID(), sa.ForeignKey("products.id")),
        sa.Column("target_version", sa.Integer()),
        sa.Column("approved_hash", sa.String(64)),
        sa.Column("approved_version", sa.Integer()),
        sa.Column("approved_by", sa.UUID(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("published_product_id", sa.UUID(), sa.ForeignKey("products.id")),
        sa.Column("index_job_id", sa.UUID()),
        sa.Column("history", JSONB(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','READY_FOR_REVIEW','APPROVED','REJECTED','PUBLISHED')",
            name="ck_draft_status",
        ),
        sa.CheckConstraint("version>=1", name="ck_draft_version"),
    )
    op.create_table(
        "catalog_commands",
        *common(),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("result", JSONB()),
        sa.UniqueConstraint(
            "store_id", "actor_id", "request_id", name="uq_catalog_command_request"
        ),
    )
    op.create_table(
        "catalog_index_jobs",
        *common(),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("requested_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint("product_id", "requested_version", name="uq_catalog_index_version"),
        sa.ForeignKeyConstraint(["product_id", "store_id"], ["products.id", "products.store_id"]),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','STALE')",
            name="ck_catalog_index_status",
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_catalog_index_attempts"),
    )


def downgrade():
    if any(
        op.get_bind().scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {name})"))
        for name in ["catalog_imports", "product_drafts", "catalog_commands", "catalog_index_jobs"]
    ):
        raise RuntimeError(
            "Catalog operation evidence exists; explicit archival migration required"
        )
    for name in ["catalog_index_jobs", "catalog_commands", "product_drafts", "catalog_imports"]:
        op.drop_table(name)
