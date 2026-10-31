"""Explicit PG barriers with bounded tasks and observable transaction acknowledgements."""

import asyncio
from collections import Counter
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from .conftest import participant_id
from .oracle import inspect_database, reader


def stamp():
    return datetime.now(UTC).isoformat()


def scalar(env, sql, **params):
    with reader(env) as conn:
        return conn.scalar(text(sql), params)


def outcome(result):
    if isinstance(result, BaseException):
        return {
            "class": "ENVIRONMENT_TIMEOUT"
            if isinstance(result, TimeoutError)
            else "TEST_HARNESS_FAILURE",
            "exception": type(result).__name__,
        }
    if hasattr(result, "status_code"):
        body = (
            result.json()
            if result.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        code, status = body.get("code"), result.status_code
        category = "SUCCESS"
        if status >= 500:
            category = (
                "TRANSIENT_DATABASE_ERROR"
                if code == "DATABASE_UNAVAILABLE"
                else "TEST_HARNESS_FAILURE"
            )
        elif status == 409:
            category = (
                "EXPECTED_CONCURRENCY_CONFLICT"
                if code
                in {
                    "IDEMPOTENCY_CONFLICT",
                    "THREAD_BUSY",
                    "STALE_INTERRUPT",
                    "STALE_VERSION",
                    "STALE_EXECUTOR",
                    "INVALID_ORDER_STATE",
                    "INVALID_CASE_STATE",
                }
                else "EXPECTED_BUSINESS_REJECTION"
            )
        elif status in {401, 403, 404}:
            category = "EXPECTED_AUTHORIZATION_REJECTION"
        elif status == 422:
            category = "EXPECTED_SCHEMA_REJECTION"
        return {"class": category, "http": status, "code": code, "body": body}
    return {"class": "SUCCESS", "domain": result.model_dump(mode="json")}


async def waiters(env, blocker, count, tasks, report):
    async with asyncio.timeout(2):
        while True:
            with reader(env) as conn:
                rows = [
                    dict(r)
                    for r in conn.execute(
                        text(
                            "SELECT "
                            "pid,backend_xid,query_start,wait_event,pg_blocking_pids(pid) "
                            "blockers,"
                            "clock_timestamp() observed_at FROM pg_stat_activity WHERE "
                            "application_name=:name "
                            "AND state='active' AND wait_event_type='Lock'"
                        ),
                        {"name": f"agentmall:{env[3].db_schema}"},
                    ).mappings()
                ]
                connections = conn.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:name"),
                    {"name": f"agentmall:{env[3].db_schema}"},
                )
            report["peak_observed_business_connections"] = max(
                report.get("peak_observed_business_connections", 0), connections
            )
            graph = {r["pid"]: r["blockers"] for r in rows}

            def rooted(pid, seen=frozenset(), graph=graph):
                return pid == blocker or (
                    pid not in seen
                    and any(rooted(parent, seen | {pid}) for parent in graph.get(pid, []))
                )

            if len(rows) == count and all(rooted(pid) for pid in graph):
                report["observations"].append({"blocker": blocker, "waiters": rows})
                return
            for task in tasks:
                assert not task.done(), f"Participant left barrier early: {outcome(task.result())}"
            await asyncio.sleep(0.02)


async def wait_clock(env, deadline):
    async with asyncio.timeout(4):
        while scalar(env, "SELECT clock_timestamp()") < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0.02)


async def race(
    env,
    report,
    sql,
    params,
    participants,
    *,
    cap=12,
    ordered=False,
    expires=None,
    injected_http_failures=None,
):
    tasks, active, peak = [], 0, 0
    semaphore = asyncio.Semaphore(cap)
    gate = asyncio.Event()
    observed = {}

    async def execute(label, call):
        nonlocal active, peak
        await gate.wait()
        async with semaphore:
            token = participant_id.set(label)
            active += 1
            peak = max(peak, active)
            report["events"].append({"actor": label, "phase": "REQUEST_START", "at": stamp()})
            try:
                try:
                    result = await call()
                except Exception as exc:
                    result = exc
                entry = outcome(result)
                expected = (injected_http_failures or {}).get(label)
                if expected is not None and entry.get("http") == expected:
                    entry["class"] = "TEST_INJECTED_FAILURE"
                if entry.get("code") == "DATABASE_UNAVAILABLE" and any(
                    error["actor"] == label and error["sqlstate"] in {"55P03", "57014"}
                    for error in report.get("database_errors", [])
                ):
                    entry["class"] = "ENVIRONMENT_TIMEOUT"
                observed[label] = entry
                report["events"].append(
                    {
                        "actor": label,
                        "phase": "REQUEST_END",
                        "at": stamp(),
                        "outcome": entry,
                    }
                )
                return result
            finally:
                active -= 1
                participant_id.reset(token)

    with env[1].connect() as blocker:
        tx = blocker.begin()
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        blocker.execute(text(sql), params)
        report["events"].append({"phase": "LOCK_ACQUIRED", "pid": pid, "at": stamp()})
        try:
            gate.set()
            if ordered:
                assert len(participants) <= cap
                # Establish the declared winner first, then release the rest as
                # one bounded group. Twelve sequential observations can consume
                # the first request's real 3s lock_timeout on a slower host.
                first, *rest = participants
                tasks.append(asyncio.create_task(execute(*first)))
                await waiters(env, pid, 1, tasks, report)
                tasks.extend(asyncio.create_task(execute(*item)) for item in rest)
                await waiters(env, pid, len(tasks), tasks, report)
            else:
                tasks = [asyncio.create_task(execute(label, call)) for label, call in participants]
                await waiters(env, pid, min(cap, len(tasks)), tasks, report)
            if expires:
                assert scalar(env, "SELECT clock_timestamp()") < expires
                await wait_clock(env, expires)
            report["released_db_time"] = scalar(env, "SELECT clock_timestamp()")
        finally:
            tx.rollback()
            report["events"].append({"phase": "LOCK_RELEASED", "pid": pid, "at": stamp()})
            try:
                results = await asyncio.wait_for(asyncio.gather(*tasks), 30)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    report["peak_inflight"] = peak
    report["request_count"] = len(results)
    report["outcomes"] = [observed[label] for label, _ in participants]
    report["class_counts"] = dict(Counter(r["class"] for r in report["outcomes"]))
    assert not any(isinstance(r, BaseException) for r in results), report["outcomes"]
    assert not any(
        r["class"] in {"TRANSIENT_DATABASE_ERROR", "ENVIRONMENT_TIMEOUT", "TEST_HARNESS_FAILURE"}
        for r in report["outcomes"]
    )
    return results


def verify(env, report):
    result = inspect_database(env, report["initial"])
    report["verified_oracle"] = result
    assert result["violations"] == [], result["violations"]
    return result


class DropResponse(httpx.AsyncBaseTransport):
    """Real loopback HTTP finishes; client deliberately loses one successful response."""

    def __init__(self):
        self.inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.receipt = None

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        await response.aread()
        try:
            assert response.status_code in {200, 201}, response.text
            self.receipt = response.json()
        finally:
            await response.aclose()
        raise httpx.ReadError("T11 controlled committed response loss", request=request)

    async def aclose(self):
        await self.inner.aclose()
