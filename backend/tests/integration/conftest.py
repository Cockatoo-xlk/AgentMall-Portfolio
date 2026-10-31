"""T11-only bounded instrumentation; production has no fault switches."""

import asyncio
import hashlib
import inspect
import json
import os
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from conftest import ROOT
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from t09_helpers import durable_env as durable_env  # noqa: F401

from agentmall.infra.config import Settings

participant_id = ContextVar("t11_participant", default=None)


def bounded(function, seconds=120):
    @wraps(function)
    async def run(*args, **kwargs):
        # This must execute in the test Task, not in an async fixture's setup Task.
        async with asyncio.timeout(seconds):
            return await function(*args, **kwargs)

    return run


def pytest_collection_modifyitems(items):
    directory = Path(__file__).parent
    for item in items:
        if Path(item.path).is_relative_to(directory) and inspect.iscoroutinefunction(item.obj):
            item.obj = bounded(item.obj)


@pytest.fixture(autouse=True)
def t11_boundary():
    settings = Settings()
    url = make_url(settings.test_database_url.get_secret_value())
    assert (url.host, url.port, url.database, url.username) == (
        "127.0.0.1",
        55433,
        "agentmall_test",
        "agentmall",
    ), "T11 refuses any database other than local 55433 agentmall_test"
    matrix = ROOT / "evals/data/business_cases.jsonl"
    frozen = json.loads((ROOT / "evals/evidence/t11/matrix-freeze.json").read_text())
    assert hashlib.sha256(matrix.read_bytes()).hexdigest() == frozen["sha256"]


@pytest.fixture
async def env(env, request):
    # Reuse parent's migrations/seed/cleanup; constrain only the test observation pool.
    db = create_engine(
        env[3].database_url.get_secret_value(),
        pool_size=3,
        max_overflow=0,
        pool_timeout=3,
        connect_args={
            "options": f"-csearch_path={env[3].db_schema},extensions "
            "-cstatement_timeout=10000 -clock_timeout=3000"
        },
    )
    try:
        owned = getattr(request.config, "t11_owned", [])
        request.config.t11_owned = owned
        names = {"business": env[3].db_schema}
        owned.append(names)
        yield env[0], db, env[2], env[3]
    finally:
        names["checkpoint"] = env[2].state.settings.checkpoint_schema
        db.dispose()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, "t11_" + report.when, report)


@pytest.fixture
async def evidence(request, env, monkeypatch):
    from .oracle import inspect_database

    report = {
        "test": request.node.nodeid,
        "case_id": None,
        "events": [],
        "observations": [],
        "started_at": datetime.now(UTC).isoformat(),
        "paid_model_requests": 0,
        "provider": "OFFLINE_FIXTURE",
        "limits": {
            "inflight": 12,
            "business_pool": 15,
            "observer_pool": 3,
            "lock_timeout_ms": 3000,
            "statement_timeout_ms": 10000,
            "case_timeout_seconds": 120,
        },
        "initial": inspect_database(env),
        "sql_statements": 0,
        "http_requests": 0,
        "transaction_events": [],
        "http_responses": [],
        "database_errors": [],
    }
    request.node.t11_evidence = report
    engine = env[2].state.engine.sync_engine

    def count_sql(*args):
        report["sql_statements"] += 1

    def database_error(context):
        report["database_errors"].append(
            {
                "actor": participant_id.get(),
                "sqlstate": getattr(context.original_exception, "sqlstate", None),
                "exception": type(context.original_exception).__name__,
                "at": datetime.now(UTC).isoformat(),
            }
        )

    def began(session, transaction, connection):
        if connection.engine is not engine:
            return
        value = (
            connection.execute(
                text(
                    "SELECT pg_backend_pid() pid, txid_current() xid, clock_timestamp() at, "
                    "current_setting('lock_timeout') lock_timeout, "
                    "current_setting('statement_timeout') statement_timeout"
                )
            )
            .mappings()
            .one()
        )
        session.info["t11_transaction"] = dict(value)
        report["transaction_events"].append(
            {"actor": participant_id.get(), "phase": "BEGIN", **dict(value)}
        )

    def ended(session, phase):
        tx = session.info.pop("t11_transaction", None)
        if tx:
            report["transaction_events"].append(
                {
                    "actor": participant_id.get(),
                    "phase": phase,
                    "pid": tx["pid"],
                    "xid": tx["xid"],
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    def committed(session):
        ended(session, "COMMIT_ACK")

    def rolled_back(session):
        ended(session, "ROLLBACK")

    app = env[2]
    if app.middleware_stack is None:
        app.middleware_stack = app.build_middleware_stack()
    original_stack = app.middleware_stack
    original_send = httpx.AsyncClient.send

    async def tagged_send(self, req, *args, **kwargs):
        if participant_id.get() is not None:
            req.headers["X-T11-Participant"] = participant_id.get()
        return await original_send(self, req, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", tagged_send)

    async def http_count(scope, receive, send):
        if scope["type"] != "http":
            return await original_stack(scope, receive, send)
        report["http_requests"] += 1
        label = (
            dict(scope["headers"]).get(b"x-t11-participant", b"").decode() or participant_id.get()
        )
        token = participant_id.set(label)
        entry = {
            "actor": label,
            "method": scope["method"],
            "path": scope["path"],
            "started_at": datetime.now(UTC).isoformat(),
        }

        async def capture(message):
            if message["type"] == "http.response.start":
                entry["status"] = message["status"]
            await send(message)

        try:
            return await original_stack(scope, receive, capture)
        except Exception as exc:
            entry["exception"] = type(exc).__name__
            raise
        finally:
            entry["finished_at"] = datetime.now(UTC).isoformat()
            report["http_responses"].append(entry)
            participant_id.reset(token)

    get_connection = engine.pool._do_get

    def measured_checkout():
        began = time.monotonic()
        try:
            return get_connection()
        finally:
            report.setdefault("pool_waits", []).append(
                {"actor": participant_id.get(), "seconds": time.monotonic() - began}
            )

    monkeypatch.setattr(engine.pool, "_do_get", measured_checkout)

    listeners = [
        (engine, "before_cursor_execute", count_sql),
        (engine, "handle_error", database_error),
        (Session, "after_begin", began),
        (Session, "after_commit", committed),
        (Session, "after_rollback", rolled_back),
    ]
    for target, name, fn in listeners:
        event.listen(target, name, fn)
    app.middleware_stack = http_count
    try:
        yield report
    finally:
        app.middleware_stack = original_stack
        for target, name, fn in listeners:
            event.remove(target, name, fn)
        report["finished_at"] = datetime.now(UTC).isoformat()
        result = getattr(request.node, "t11_call", None)
        report["result"] = "PASS" if result and result.passed else "FAIL"
        if result and result.failed:
            report["failure"] = str(result.longrepr)
        try:
            report["final"] = inspect_database(env, report["initial"])
        except Exception as exc:
            report["oracle_error"] = type(exc).__name__
        destination = os.environ.get("AGENTMALL_R1_EVIDENCE_DIR") or os.environ.get(
            "AGENTMALL_T11_EVIDENCE_DIR"
        )
        if destination:
            path = await asyncio.to_thread(Path(destination).resolve)
            assert path.is_relative_to(
                ROOT
                / (
                    ".t13-r1"
                    if os.environ.get("AGENTMALL_R1_EVIDENCE_DIR")
                    else "evals/evidence/t11"
                )
            )
            path.mkdir(parents=True, exist_ok=True)
            ident = report["case_id"] or request.node.name
            if os.environ.get("AGENTMALL_R1_EVIDENCE_DIR"):
                ident += "-" + uuid4().hex
            (path / (ident + ".json")).write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
            )


def pytest_sessionfinish(session, exitstatus):
    owned = getattr(session.config, "t11_owned", [])
    if not owned:
        return
    engine = create_engine(Settings().test_database_url.get_secret_value())
    try:
        with engine.connect() as conn:
            remaining = list(conn.scalars(text("SELECT nspname FROM pg_namespace")))
        leaked = [n for pair in owned for n in pair.values() if n and n in remaining]
    finally:
        engine.dispose()
    destination = os.environ.get("AGENTMALL_R1_EVIDENCE_DIR") or os.environ.get(
        "AGENTMALL_T11_EVIDENCE_DIR"
    )
    if destination:
        path = Path(destination).resolve()
        assert path.is_relative_to(
            ROOT
            / (".t13-r1" if os.environ.get("AGENTMALL_R1_EVIDENCE_DIR") else "evals/evidence/t11")
        )
        path.mkdir(parents=True, exist_ok=True)
        (path / "resource-cleanup.json").write_text(
            json.dumps(
                {
                    "owned": owned,
                    "remaining_owned_schemas": leaked,
                    "pytest_exit_before_cleanup": exitstatus,
                },
                indent=2,
            )
            + "\n"
        )
    if leaked:
        session.exitstatus = 1
