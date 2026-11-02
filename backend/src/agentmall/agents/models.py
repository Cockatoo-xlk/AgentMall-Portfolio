from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentmall.infra.db import Base, Record


class AgentThread(Record, Base):
    __tablename__ = "agent_threads"
    __table_args__ = (
        CheckConstraint("mode IN ('single','multi')", name="ck_thread_mode"),
        CheckConstraint("status IN ('ACTIVE','HUMAN_HANDOFF','CLOSED')", name="ck_thread_status"),
        Index("ix_thread_owner", "user_id", "store_id"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    store_id: Mapped[UUID]
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), server_default="ACTIVE")


class AgentRun(Record, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("thread_id", "request_id", name="uq_run_request"),
        UniqueConstraint("id", "thread_id", name="uq_run_thread"),
        CheckConstraint(
            "status IN ('RUNNING','WAITING_INPUT','COMPLETED','PARTIAL','FAILED')",
            name="ck_run_status",
        ),
        CheckConstraint("epoch >= 0 AND event_seq >= 0", name="ck_run_counters"),
    )
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("agent_threads.id"))
    request_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(30))
    input_digest: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(80))
    request_payload: Mapped[dict] = mapped_column(JSONB)
    context_snapshot: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    budget: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    node_journal: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    resume_journal: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    result: Mapped[dict | None] = mapped_column(JSONB)
    pending_confirmation: Mapped[dict | None] = mapped_column(JSONB)
    event_seq: Mapped[int] = mapped_column(server_default="0")
    epoch: Mapped[int] = mapped_column(server_default="0")
    worker_token: Mapped[UUID | None]
    lock_pid: Mapped[int | None]


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_event_seq"),
        CheckConstraint("seq > 0", name="ck_run_event_seq"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"))
    seq: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str | None] = mapped_column(String(30))
    action_id: Mapped[UUID | None]
    payload_summary: Mapped[dict] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThreadContext(Base):
    __tablename__ = "agent_thread_contexts"
    __table_args__ = (CheckConstraint("version >= 0", name="ck_context_version"),)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("agent_threads.id"), primary_key=True)
    version: Mapped[int] = mapped_column(server_default="0")
    preferences: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    offered_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    focus: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    provenance: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateSet(Record, Base):
    __tablename__ = "agent_candidate_sets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "thread_id"],
            ["agent_runs.id", "agent_runs.thread_id"],
            name="fk_candidate_run_thread",
        ),
    )
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("agent_threads.id"))
    run_id: Mapped[UUID]
    preferences_digest: Mapped[str] = mapped_column(String(64))
    items: Mapped[list] = mapped_column(JSONB)


class ContextMutation(Record, Base):
    __tablename__ = "agent_context_mutations"
    __table_args__ = (UniqueConstraint("thread_id", "request_id", name="uq_context_request"),)
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("agent_threads.id"))
    request_id: Mapped[UUID]
    digest: Mapped[str] = mapped_column(String(64))
    receipt: Mapped[dict] = mapped_column(JSONB)
