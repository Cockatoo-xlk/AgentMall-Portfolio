"""Session advisory ownership plus a short transaction fence for stale executors."""

import hashlib
from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg import AsyncConnection, OperationalError
from psycopg.rows import dict_row
from sqlalchemy import select, text

from agentmall.agents.models import AgentRun
from agentmall.agents.persistence import connection_info
from agentmall.infra.errors import DomainError


def lock_key(thread_id):
    return int.from_bytes(
        hashlib.sha256(("agentmall:" + str(thread_id)).encode()).digest()[:8], "big", signed=True
    )


@asynccontextmanager
async def thread_lock(settings, thread_id):
    key = lock_key(thread_id)
    async with await AsyncConnection.connect(
        connection_info(settings),
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=3,
        application_name=f"agentmall:lock:{thread_id}",
    ) as conn:
        row = await (
            await conn.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (key,))
        ).fetchone()
        if not row["acquired"]:
            raise DomainError(409, "THREAD_BUSY", "此会话已有运行中的请求")
        try:
            yield conn
        finally:
            if not conn.closed and not conn.broken:
                try:
                    await conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
                except OperationalError:
                    # A terminated connection has already released its locks. Preserve
                    # the original stale-executor response instead of masking it here.
                    await conn.close()
            # Dedicated connections are closed, never returned with a session lock to a pool.


class RunFence:
    def __init__(self, sessions, run_id, thread_id, token, epoch, pid):
        self.sessions, self.run_id, self.thread_id = sessions, run_id, thread_id
        self.token, self.epoch, self.pid = token, epoch, pid

    async def check(self, session, *, exclusive=False):
        run = await session.scalar(
            select(AgentRun)
            .where(AgentRun.id == self.run_id)
            .with_for_update(read=not exclusive)
            .execution_options(populate_existing=True)
        )
        if (
            run is None
            or run.status != "RUNNING"
            or run.worker_token != self.token
            or run.epoch != self.epoch
        ):
            raise DomainError(409, "STALE_EXECUTOR", "运行执行者已失效")
        held = await advisory_held(session, self.thread_id, self.pid)
        if not held:
            raise DomainError(409, "STALE_EXECUTOR", "会话锁连接已丢失")
        return run


async def claim_execution(session, run, connection, sessions):
    run.epoch += 1
    run.worker_token = uuid4()
    run.lock_pid = connection.info.backend_pid
    run.status = "RUNNING"
    run.finished_at = None
    await session.flush()
    return RunFence(sessions, run.id, run.thread_id, run.worker_token, run.epoch, run.lock_pid)


async def advisory_held(session, thread_id, pid):
    key = lock_key(thread_id) & ((1 << 64) - 1)
    held = await session.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' "
            "AND pid=:pid AND classid=:hi AND objid=:lo AND objsubid=1 AND granted "
            "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()))"
        ),
        {"pid": pid, "hi": key >> 32, "lo": key & 0xFFFFFFFF},
    )
    return held
