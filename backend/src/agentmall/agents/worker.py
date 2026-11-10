"""Independent trusted local Worker: at-least-once attempts, original durable executor."""

import argparse
import asyncio
import importlib
import inspect
import json
import signal
from datetime import timedelta

from psycopg import OperationalError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from agentmall.actions.service import database_now
from agentmall.agents import run_service
from agentmall.agents.jobs import claim
from agentmall.agents.locking import advisory_held, thread_lock
from agentmall.agents.models import AgentJob, AgentRun, AgentThread
from agentmall.identity.models import User
from agentmall.identity.service import actor_for
from agentmall.infra.errors import DomainError

DATABASE_ERRORS = (DBAPIError, OperationalError, OSError)


def report(status, **values):
    # Only identifiers/codes; never repr(exc), SQL, prompts or provider bodies.
    print(json.dumps({"worker_status": status, **values}), flush=True)


async def execute_job(app, job_id, thread_id, *, max_attempts=3):
    async with thread_lock(app.state.settings, thread_id) as connection:
        sessions = app.state.sessions
        async with sessions.begin() as session:
            job = await claim(session, job_id, max_attempts=max_attempts)
            if job is None:
                return False
            token = job.claim_token
            run = await session.get(AgentRun, job.run_id)
            thread = await session.get(AgentThread, job.thread_id)
            user = await session.get(User, thread.user_id)
            actor = actor_for(user, app.state.settings) if user and not user.disabled else None
            error = None
            if actor is None or actor.role != "buyer" or actor.store_id != thread.store_id:
                error = "EXECUTION_OWNER_UNAVAILABLE"
            elif run.prompt_version != run_service.prompt_version(
                bool(run.context_snapshot)
            ) or run.model_id != run_service.model_identity(app, thread.mode):
                error = "RUN_VERSION_MISMATCH"
            elif (thread.mode == "single" and app.state.durable_single_model is None) or (
                thread.mode == "multi" and not app.state.multi_models
            ):
                error = "MODEL_DISABLED"
            payload = None
            if job.kind == "RESUME":
                entry = run.resume_journal.get(str(job.resume_request_id))
                if entry is None:
                    error = "RESUME_INTENT_MISSING"
                elif not entry["completed"]:
                    payload = entry["payload"]
            if error:
                job.status, job.last_error, job.finished_at = (
                    "BLOCKED",
                    error,
                    await database_now(session),
                )
                run_service.add_event(
                    session, run, "job_blocked", {"status": "BLOCKED", "error_code": error}
                )
                return True
            run_id = run.id
            should_execute = (
                run.status == "RUNNING"
                or run.last_error in run_service.RECOVERABLE_ERRORS
                or (run.status == "WAITING_INPUT" and payload is not None)
            )
            run_service.add_event(
                session, run, "job_executing", {"status": "EXECUTING", "attempt": job.attempts}
            )
        report("EXECUTING", job_id=str(job_id))
        error = None
        if should_execute:
            try:
                await run_service.activate(app, actor, run_id, thread, connection, payload)
            except DomainError as exc:
                # A stale process cannot finalize either Run OR dispatch state.
                if exc.code == "STALE_EXECUTOR":
                    report("STALE_EXECUTOR", job_id=str(job_id))
                    return True
                error = exc.code
        async with sessions.begin() as session:
            if not await advisory_held(session, thread_id, connection.info.backend_pid):
                report("STALE_EXECUTOR", job_id=str(job_id))
                return True
            job = await session.scalar(
                select(AgentJob).where(AgentJob.id == job_id).with_for_update()
            )
            if job.claim_token != token:
                report("STALE_EXECUTOR", job_id=str(job_id))
                return True
            run = await session.get(AgentRun, run_id)
            job.last_error = error or run.last_error
            now = await database_now(session)
            if (
                not error
                and run.last_error in run_service.RECOVERABLE_ERRORS
                and job.attempts < max_attempts
            ):
                job.status, job.available_at = "QUEUED", now + timedelta(seconds=2 * job.attempts)
            else:
                job.status = (
                    "BLOCKED"
                    if error or run.status == "RUNNING"
                    else "FAILED"
                    if run.status in {"PARTIAL", "FAILED"}
                    else run.status
                )
                job.finished_at = now
            run_service.add_event(
                session, run, "job_state", {"status": job.status, "error_code": job.last_error}
            )
            report(job.status, job_id=str(job.id))
        return True


async def tick(app, *, max_attempts=3):
    async with app.state.sessions.begin() as session:
        now = await database_now(session)
        rows = (
            await session.execute(
                select(AgentJob.id, AgentJob.thread_id)
                .where(AgentJob.status.in_(["QUEUED", "EXECUTING"]), AgentJob.available_at <= now)
                .order_by(AgentJob.available_at, AgentJob.id)
                .limit(20)
            )
        ).all()
    for job_id, thread_id in rows:
        try:
            if await execute_job(app, job_id, thread_id, max_attempts=max_attempts):
                return True
        except DomainError as exc:
            if exc.code != "THREAD_BUSY":
                raise
    return False


async def serve(app, *, concurrency=1, poll_seconds=0.5, max_attempts=3, once=False):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    async def consumer():
        failures = 0
        while not stop.is_set():
            try:
                worked = await tick(app, max_attempts=max_attempts)
                failures = 0
            except DATABASE_ERRORS:
                failures += 1
                worked = False
                report("DATABASE_UNAVAILABLE", consecutive_failures=failures)
                if once or failures >= 5:
                    stop.set()
                    raise RuntimeError("DATABASE_UNAVAILABLE") from None
            if once:
                return
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=min(5, poll_seconds * 2**failures)
                    if failures
                    else poll_seconds
                    if not worked
                    else 0.05,
                )
            except TimeoutError:
                pass

    try:
        await asyncio.gather(*(consumer() for _ in range(concurrency)))
    finally:
        await app.state.engine.dispose()
        close = getattr(app.state, "worker_close", None)
        if close:
            await close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--factory",
        default="agentmall.main:create_app",
        help="Trusted operator composition root, identical to API; never an HTTP input",
    )
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--max-attempts", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 0.1 <= args.poll_seconds <= 5:
        parser.error("poll-seconds must be 0.1..5")
    module, name = args.factory.split(":", 1)
    app = getattr(importlib.import_module(module), name)()
    if inspect.isawaitable(app):
        app = await app
    await serve(
        app,
        concurrency=args.concurrency,
        poll_seconds=args.poll_seconds,
        max_attempts=args.max_attempts,
        once=args.once,
    )


if __name__ == "__main__":
    asyncio.run(main())
