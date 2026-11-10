"""Versioned thread preferences and immutable verified candidate lists."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_run_thread", "agent_runs", ["id", "thread_id"])
    op.add_column(
        "agent_runs", sa.Column("context_snapshot", JSONB(), nullable=False, server_default="{}")
    )
    op.create_table(
        "agent_thread_contexts",
        sa.Column("thread_id", sa.UUID(), sa.ForeignKey("agent_threads.id"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        *[
            sa.Column(
                n, JSONB(), nullable=False, server_default="[]" if n == "offered_ids" else "{}"
            )
            for n in ("preferences", "offered_ids", "focus", "provenance")
        ],
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("version >= 0", name="ck_context_version"),
    )
    for table in ("agent_candidate_sets", "agent_context_mutations"):
        cols = [
            sa.Column("id", sa.UUID(), primary_key=True),
            *[
                sa.Column(
                    n, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
                )
                for n in ("created_at", "updated_at")
            ],
            sa.Column("thread_id", sa.UUID(), sa.ForeignKey("agent_threads.id"), nullable=False),
        ]
        if table == "agent_candidate_sets":
            cols += [
                sa.Column("run_id", sa.UUID(), nullable=False),
                sa.ForeignKeyConstraint(
                    ["run_id", "thread_id"],
                    ["agent_runs.id", "agent_runs.thread_id"],
                    name="fk_candidate_run_thread",
                ),
                sa.Column("preferences_digest", sa.String(64), nullable=False),
                sa.Column("items", JSONB(), nullable=False),
            ]
        else:
            cols += [
                sa.Column("request_id", sa.UUID(), nullable=False),
                sa.Column("digest", sa.String(64), nullable=False),
                sa.Column("receipt", JSONB(), nullable=False),
                sa.UniqueConstraint("thread_id", "request_id", name="uq_context_request"),
            ]
        op.create_table(table, *cols)


def downgrade():
    op.drop_table("agent_context_mutations")
    op.drop_table("agent_candidate_sets")
    op.drop_table("agent_thread_contexts")
    op.drop_column("agent_runs", "context_snapshot")
    op.drop_constraint("uq_run_thread", "agent_runs", type_="unique")
