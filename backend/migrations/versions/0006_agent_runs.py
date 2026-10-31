"""Durable application threads, runs and ordered events; saver tables are separate."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
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

    op.create_table(
        "agent_threads",
        *record(),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("store_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.CheckConstraint("mode IN ('single','multi')", name="ck_thread_mode"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','HUMAN_HANDOFF','CLOSED')", name="ck_thread_status"
        ),
    )
    op.create_index("ix_thread_owner", "agent_threads", ["user_id", "store_id"])
    op.create_table(
        "agent_runs",
        *record(),
        sa.Column("thread_id", sa.UUID(), sa.ForeignKey("agent_threads.id"), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(80)),
        sa.Column("request_payload", JSONB(), nullable=False),
        *[
            sa.Column(name, JSONB(), nullable=False, server_default="{}")
            for name in ("budget", "node_journal", "resume_journal")
        ],
        sa.Column("result", JSONB()),
        sa.Column("pending_confirmation", JSONB()),
        sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_token", sa.UUID()),
        sa.Column("lock_pid", sa.Integer()),
        sa.UniqueConstraint("thread_id", "request_id", name="uq_run_request"),
        sa.CheckConstraint(
            "status IN ('RUNNING','WAITING_INPUT','COMPLETED','PARTIAL','FAILED')",
            name="ck_run_status",
        ),
        sa.CheckConstraint("epoch >= 0 AND event_seq >= 0", name="ck_run_counters"),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("run_id", sa.UUID(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("agent", sa.String(30)),
        sa.Column("action_id", sa.UUID()),
        sa.Column("payload_summary", JSONB(), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
        sa.CheckConstraint("seq > 0", name="ck_run_event_seq"),
    )


def downgrade():
    op.drop_table("run_events")
    op.drop_table("agent_runs")
    op.drop_table("agent_threads")
