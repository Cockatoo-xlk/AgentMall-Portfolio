"""PostgreSQL dispatch index. No model decisions, approvals or business commands here."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from agentmall.actions.service import database_now
from agentmall.agents.models import AgentJob


def job_view(job):
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "attempts": job.attempts,
        "last_error": job.last_error,
        "available_at": job.available_at,
        "finished_at": job.finished_at,
    }


async def latest_job(session, run_id):
    return await session.scalar(
        select(AgentJob)
        .where(AgentJob.run_id == run_id)
        .order_by(AgentJob.created_at.desc(), AgentJob.id.desc())
        .limit(1)
    )


async def intent_job(session, run_id, key):
    return await session.scalar(
        select(AgentJob).where(AgentJob.run_id == run_id, AgentJob.intent_key == key)
    )


async def enqueue(session, run, kind, key, resume_request_id=None):
    from agentmall.agents.run_service import add_event

    job = AgentJob(
        id=uuid4(),
        run_id=run.id,
        thread_id=run.thread_id,
        kind=kind,
        intent_key=key,
        resume_request_id=resume_request_id,
        status="QUEUED",
        attempts=0,
    )
    session.add(job)
    add_event(session, run, "job_queued", {"status": "QUEUED", "resource_id": str(job.id)})
    await session.flush()
    return job


async def claim(session, job_id, *, max_attempts):
    """Caller MUST hold the original thread advisory lock, not merely a lease."""
    job = await session.scalar(
        select(AgentJob)
        .where(AgentJob.id == job_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    now = await database_now(session)
    if job is None or job.status not in {"QUEUED", "EXECUTING"} or job.available_at > now:
        return None
    if job.attempts >= max_attempts:
        job.status, job.last_error, job.finished_at = "BLOCKED", "ATTEMPTS_EXHAUSTED", now
        return None
    job.status, job.claim_token = "EXECUTING", uuid4()
    job.attempts += 1
    # Discovery delay only. An expired timestamp NEVER revokes an executor's lock.
    job.available_at = now + timedelta(seconds=5)
    return job
