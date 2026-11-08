"""Durable dispatch intent, separate from business execution truth."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("intent_key", sa.String(128), nullable=False),
        sa.Column("resume_request_id", sa.UUID()),
        sa.Column("status", sa.String(24), nullable=False, server_default="QUEUED"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("claim_token", sa.UUID()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(80)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["run_id", "thread_id"], ["agent_runs.id", "agent_runs.thread_id"]),
        sa.UniqueConstraint("run_id", "intent_key", name="uq_job_intent"),
        sa.CheckConstraint("kind IN ('START','RESUME','RECOVER')", name="ck_job_kind"),
        sa.CheckConstraint(
            "status IN ('QUEUED','EXECUTING','WAITING_INPUT','COMPLETED','FAILED','BLOCKED')",
            name="ck_job_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_job_attempts"),
    )
    op.create_index("ix_job_ready", "agent_jobs", ["status", "available_at"])


def downgrade():
    op.drop_table("agent_jobs")
