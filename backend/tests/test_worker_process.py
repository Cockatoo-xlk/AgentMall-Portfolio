"""Real independent OS workers + actual SIGKILL; business assertions query PostgreSQL."""

import asyncio
import json
import os
import signal
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from retrieval_helpers import index
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from t09_helpers import confirm, thread  # noqa: F401
from t09_helpers import durable_env as durable_env
from worker_process_helpers import configure


@pytest.fixture
async def worker_env(durable_env):
    await index(durable_env)
    await configure(durable_env[2])
    try:
        yield durable_env
    finally:
        await durable_env[2].state.worker_close()


@asynccontextmanager
async def process(env, tmp_path, boundary=None, once=True, api_port=None, **extra):
    ident = uuid4().hex
    marker = tmp_path / (ident + ".marker")
    config = tmp_path / (ident + ".json")
    config.write_text(
        json.dumps(
            {
                "schema": env[3].db_schema,
                "checkpoint": env[3].checkpoint_schema,
                "marker": str(marker),
                "boundary": boundary,
                **extra,
            }
        )
    )
    config.chmod(0o600)
    path = tmp_path / (ident + ".log")
    with path.open("wb") as log:
        path.chmod(0o600)
        command = [
            sys.executable,
            "-m",
            "agentmall.agents.worker",
            "--factory",
            "worker_process_helpers:create_app",
            *(["--once"] if once else []),
        ]
        if api_port is not None:
            command = [sys.executable, "-m", "worker_process_helpers", "--api-port", str(api_port)]
        child = await asyncio.create_subprocess_exec(
            *command,
            env={
                **os.environ,
                "PYTHONPATH": "backend/tests:backend/src",
                "AGENTMALL_WORKER_TEST_CONFIG": str(config),
            },
            stdout=log,
            stderr=log,
        )
        try:
            yield child, marker, path
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()
            evidence = os.environ.get("AGENTMALL_WORKER_EVIDENCE_DIR")
            if evidence:
                import hashlib
                from pathlib import Path

                out = Path(evidence)
                await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True, mode=0o700)
                raw = await asyncio.to_thread(path.read_bytes)
                (out / (ident + ".log")).write_bytes(raw)
                (out / (ident + ".log")).chmod(0o600)
                record = {
                    "pid": child.pid,
                    "exit_code": child.returncode,
                    "boundary": boundary,
                    "marker_observed": marker.exists(),
                    "process_role": "API" if api_port is not None else "Worker",
                    "log_sha256": hashlib.sha256(raw).hexdigest(),
                }
                target = out / (ident + ".json")
                target.write_text(json.dumps(record, indent=2))
                target.chmod(0o600)


async def marked(child, marker, path):
    async with asyncio.timeout(20):
        while not marker.exists():
            assert child.returncode is None, path.read_text()
            await asyncio.sleep(0.025)


async def finish(env, tmp_path):
    # Wait for original fixed discovery delay; never alter persisted timestamps to force takeover.
    await asyncio.sleep(5.1)
    async with process(env, tmp_path) as (child, _, path):
        assert await asyncio.wait_for(child.wait(), 35) == 0, path.read_text()


async def start(env, buyer, tid, purchase=False):
    r = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/async",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "message": "找一款300元以内的静音键盘准备购买，送演示宿舍"
            if purchase
            else "推荐300元以内静音键盘，不要购买。",
        },
    )
    assert r.status_code == 202, r.text
    return r.json()


async def read(env, buyer, tid):
    return (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()["runs"][0]


@pytest.mark.parametrize(
    "boundary",
    [
        "before_claim",
        "model_inflight",
        "journal_committed",
        "checkpoint_waiting",
        "waiting_committed",
    ],
)
async def test_actual_sigkill_then_same_run_recovered(worker_env, buyer, tmp_path, boundary):
    env = worker_env
    tid = await thread(env, buyer)
    run = await start(
        env, buyer, tid, purchase=boundary in {"waiting_committed", "checkpoint_waiting"}
    )
    async with process(env, tmp_path, boundary) as (child, marker, path):
        await marked(child, marker, path)
        with env[1].connect() as c:
            saved = c.scalar(text("SELECT node_journal FROM agent_runs"))
            assert c.scalar(text("SELECT count(*) FROM orders")) == 0
            if boundary == "journal_committed":
                assert any(k.startswith("supervisor:") for k in saved)
        child.kill()
        assert await child.wait() == -signal.SIGKILL
    await finish(env, tmp_path)
    result = await read(env, buyer, tid)
    assert result["id"] == run["id"]
    assert result["status"] == (
        "WAITING_INPUT" if boundary in {"waiting_committed", "checkpoint_waiting"} else "COMPLETED"
    ), result
    assert result["job"]["status"] == result["status"]
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM agent_runs")) == 1
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0
        assert c.scalar(text("SELECT count(*) FROM confirmations")) == 0
        if boundary == "journal_committed":
            now = c.scalar(text("SELECT node_journal FROM agent_runs"))
            for k, v in saved.items():
                assert now[k] == v


@pytest.mark.parametrize("crash_boundary", ["business_committed", "execute_journal_committed"])
async def test_order_commit_sigkill_response_loss_and_duplicate_resume(
    worker_env, buyer, tmp_path, crash_boundary
):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid, purchase=True)
    await finish(env, tmp_path)
    run = await read(env, buyer, tid)
    assert run["status"] == "WAITING_INPUT", run
    pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, pid)
    body = {
        "request_id": str(uuid4()),
        "run_id": run["id"],
        "interrupt_id": run["pending_confirmation"]["interrupt_id"],
        "proposal_id": pid,
        "confirmation_id": cid,
    }
    endpoint = f"/api/v1/agent/threads/{tid}/resume/async"
    assert (await env[0].post(endpoint, headers=buyer, json=body)).status_code == 202
    assert (
        await env[0].post(endpoint, headers=buyer, json={**body, "request_id": str(uuid4())})
    ).status_code == 202
    async with process(env, tmp_path, crash_boundary) as (child, marker, path):
        await marked(child, marker, path)
        with env[1].connect() as c:
            assert c.scalar(text("SELECT count(*) FROM orders")) == 1
            assert c.scalar(text("SELECT status FROM orders")) == "PENDING_PAYMENT"
            inventory = c.execute(
                text("SELECT id,on_hand,reserved FROM products ORDER BY id")
            ).all()
        child.kill()
        assert await child.wait() == -signal.SIGKILL
    await finish(env, tmp_path)
    result = await read(env, buyer, tid)
    assert result["status"] == "COMPLETED", result
    assert (await env[0].post(endpoint, headers=buyer, json=body)).status_code == 202
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 1
        assert c.scalar(text("SELECT count(*) FROM payments")) == 0
        assert (
            c.scalar(text("SELECT count(*) FROM confirmations WHERE consumed_at IS NOT NULL")) == 1
        )
        assert (
            c.execute(text("SELECT id,on_hand,reserved FROM products ORDER BY id")).all()
            == inventory
        )
        assert c.scalar(text("SELECT count(*) FROM agent_jobs")) == 2
        order_id = c.scalar(text("SELECT id FROM orders"))
        assert c.scalar(text("SELECT result_ref FROM confirmations")) == order_id
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM idempotency_requests "
                    "WHERE operation='execute_checkout' AND completed_at IS NOT NULL"
                )
            )
            == 1
        )
        assert c.scalar(text("SELECT sum(quantity) FROM order_items")) == 1
        assert c.scalar(text("SELECT sum(reserved) FROM products")) == 1
    from uuid import UUID

    from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

    async with checkpoint_saver(env[3]) as saver:
        saved = await saver.aget_tuple(checkpoint_config(UUID(tid), UUID(run["id"])))
        assert saved is not None
        assert saved.checkpoint["channel_values"]["runtime_state"]
    with env[1].connect() as c:
        seq = list(c.scalars(text("SELECT seq FROM run_events ORDER BY seq")))
        assert seq == list(range(1, len(seq) + 1))


async def test_version_mismatch_blocks_without_execution(worker_env, buyer, tmp_path):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid)
    async with process(env, tmp_path, version_mismatch=True) as (child, _, path):
        assert await asyncio.wait_for(child.wait(), 20) == 0, path.read_text()
    run = await read(env, buyer, tid)
    assert run["job"]["status"] == "BLOCKED"
    assert run["job"]["last_error"] == "RUN_VERSION_MISMATCH"
    assert run["epoch"] == 0


async def test_two_workers_lock_and_different_threads_parallel(worker_env, buyer, tmp_path):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid)
    async with process(env, tmp_path, "model_inflight") as (first, marker, path):
        await marked(first, marker, path)
        # Same job still live after its discovery timestamp expires: lock prevents theft.
        await asyncio.sleep(5.1)
        async with process(env, tmp_path) as (second, _, log):
            assert await asyncio.wait_for(second.wait(), 20) == 0, log.read_text()
        with env[1].connect() as c:
            assert c.scalar(text("SELECT attempts FROM agent_jobs")) == 1
        other = await thread(env, buyer)
        await start(env, buyer, other)
        async with process(env, tmp_path, "model_inflight") as (parallel, mark2, log2):
            await marked(parallel, mark2, log2)
            with env[1].connect() as c:
                assert (
                    c.scalar(text("SELECT count(*) FROM agent_jobs WHERE status='EXECUTING'")) == 2
                )
    await finish(env, tmp_path)
    await finish(env, tmp_path)
    assert (await read(env, buyer, tid))["status"] == "COMPLETED"
    assert (await read(env, buyer, other))["status"] == "COMPLETED"


async def test_stopped_old_worker_cannot_write_after_new_epoch(worker_env, buyer, tmp_path):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid)
    async with process(env, tmp_path, "model_inflight") as (old, marker, path):
        await marked(old, marker, path)
        old.send_signal(signal.SIGSTOP)
        with env[1].begin() as c:
            pid = c.scalar(text("SELECT lock_pid FROM agent_runs"))
            assert c.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        await finish(env, tmp_path)
        with env[1].connect() as c:
            before = c.execute(text("SELECT epoch,node_journal,result FROM agent_runs")).one()
            assert before.epoch == 2
        marker.with_suffix(".release").write_text("release")
        old.send_signal(signal.SIGCONT)
        assert await asyncio.wait_for(old.wait(), 25) == 0, path.read_text()
        assert "STALE_EXECUTOR" in path.read_text()
        with env[1].connect() as c:
            assert (
                c.execute(text("SELECT epoch,node_journal,result FROM agent_runs")).one() == before
            )


async def test_database_unavailable_worker_exits_bounded_then_original_job_recovers(
    worker_env, buyer, tmp_path
):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid)
    admin = create_engine(make_url(env[3].database_url.get_secret_value()).set(database="postgres"))
    with admin.begin() as c:
        c.execute(text("ALTER DATABASE agentmall_test ALLOW_CONNECTIONS false"))
    try:
        async with process(env, tmp_path) as (child, _, path):
            assert await asyncio.wait_for(child.wait(), 15) != 0
            assert path.read_text().count('"worker_status": "DATABASE_UNAVAILABLE"') == 1
        async with process(env, tmp_path, once=False) as (child, _, path):
            assert await asyncio.wait_for(child.wait(), 35) != 0
            log = path.read_text()
            assert log.count('"worker_status": "DATABASE_UNAVAILABLE"') == 5
    finally:
        with admin.begin() as c:
            c.execute(text("ALTER DATABASE agentmall_test ALLOW_CONNECTIONS true"))
        admin.dispose()
    await finish(env, tmp_path)
    assert (await read(env, buyer, tid))["status"] == "COMPLETED"


async def test_expired_accepted_proposal_never_becomes_an_order(worker_env, buyer, tmp_path):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid, purchase=True)
    await finish(env, tmp_path)
    run = await read(env, buyer, tid)
    pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, pid)
    payload = {
        "run_id": run["id"],
        "request_id": str(uuid4()),
        "interrupt_id": run["pending_confirmation"]["interrupt_id"],
        "proposal_id": pid,
        "confirmation_id": cid,
    }
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/resume/async", headers=buyer, json=payload
    )
    assert response.status_code == 202, response.text
    async with process(env, tmp_path, advance_proposal_clock=True) as (child, _, path):
        assert await asyncio.wait_for(child.wait(), 25) == 0, path.read_text()
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0
        assert (
            c.scalar(text("SELECT count(*) FROM confirmations WHERE consumed_at IS NOT NULL")) == 0
        )
        assert c.scalar(text("SELECT sum(reserved) FROM products")) == 0


async def test_changed_thread_store_and_disabled_user_block_dispatch(worker_env, buyer, tmp_path):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid)
    with env[1].begin() as c:
        c.execute(text("UPDATE agent_threads SET store_id=:store"), {"store": uuid4()})
    async with process(env, tmp_path) as (child, _, path):
        assert await asyncio.wait_for(child.wait(), 20) == 0, path.read_text()
    with env[1].connect() as c:
        assert c.scalar(text("SELECT last_error FROM agent_jobs")) == "EXECUTION_OWNER_UNAVAILABLE"
        assert c.scalar(text("SELECT epoch FROM agent_runs")) == 0


async def test_single_agent_async_uses_same_durable_executor(worker_env, buyer, tmp_path):
    env = worker_env
    tid = await thread(env, buyer, "single")
    r = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/async",
        headers=buyer,
        json={"request_id": str(uuid4()), "message": "列出我的订单。"},
    )
    assert r.status_code == 202
    await finish(env, tmp_path)
    run = await read(env, buyer, tid)
    assert run["status"] == "COMPLETED", run
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0


async def test_bundle_replanning_and_purchase_through_independent_workers(
    worker_env, buyer, tmp_path
):
    from test_bundle_shopping import MESSAGE

    from agentmall.seed import seed

    env = worker_env
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    await index(env)
    tid = await thread(env, buyer)
    for message in [
        MESSAGE,
        "显示器不要换，键盘必须支持无线连接。",
        "就买修改后的这套，每样一件，送演示宿舍。",
    ]:
        view = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()
        body = {
            "request_id": str(uuid4()),
            "message": message,
            "expected_context_version": view["context"]["version"],
        }
        r = await env[0].post(f"/api/v1/agent/threads/{tid}/runs/async", headers=buyer, json=body)
        assert r.status_code == 202, r.text
        await finish(env, tmp_path)
    run = await read(env, buyer, tid)
    assert run["status"] == "WAITING_INPUT", run
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0
    pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, pid)
    payload = {
        "request_id": str(uuid4()),
        "run_id": run["id"],
        "interrupt_id": run["pending_confirmation"]["interrupt_id"],
        "proposal_id": pid,
        "confirmation_id": cid,
    }
    assert (
        await env[0].post(f"/api/v1/agent/threads/{tid}/resume/async", headers=buyer, json=payload)
    ).status_code == 202
    await finish(env, tmp_path)
    result = await read(env, buyer, tid)
    assert result["status"] == "COMPLETED", result
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 1
        assert c.scalar(text("SELECT count(*) FROM order_items")) == 4
        assert c.scalar(text("SELECT sum(reserved) FROM products")) == 4
        assert c.scalar(text("SELECT total_cents FROM orders")) <= 500000
        assert c.scalar(text("SELECT count(*) FROM payments")) == 0


@pytest.mark.parametrize("resume_case", [False, True])
async def test_explicit_recovery_after_version_block_uses_original_intent(
    worker_env, buyer, tmp_path, resume_case
):
    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid, purchase=resume_case)
    if resume_case:
        await finish(env, tmp_path)
        run = await read(env, buyer, tid)
        pid = run["pending_confirmation"]["proposal_id"]
        cid = await confirm(env, buyer, pid)
        body = {
            "request_id": str(uuid4()),
            "run_id": run["id"],
            "interrupt_id": run["pending_confirmation"]["interrupt_id"],
            "proposal_id": pid,
            "confirmation_id": cid,
        }
        assert (
            await env[0].post(f"/api/v1/agent/threads/{tid}/resume/async", headers=buyer, json=body)
        ).status_code == 202
    async with process(env, tmp_path, version_mismatch=True) as (child, _, path):
        assert await asyncio.wait_for(child.wait(), 25) == 0, path.read_text()
    run = await read(env, buyer, tid)
    assert run["job"]["status"] == "BLOCKED"
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/{run['id']}/recover/async",
        headers=buyer,
        json={"request_id": run["request_id"]},
    )
    assert response.status_code == 202, response.text
    assert response.json()["job"]["status"] == "QUEUED", response.text
    if not resume_case:
        # Block again before activation: epoch remains unchanged; recovery key must
        # still distinguish the new explicit scheduling attempt.
        async with process(env, tmp_path, version_mismatch=True) as (child, _, path):
            assert await asyncio.wait_for(child.wait(), 25) == 0, path.read_text()
        response = await env[0].post(
            f"/api/v1/agent/threads/{tid}/runs/{run['id']}/recover/async",
            headers=buyer,
            json={"request_id": run["request_id"]},
        )
        assert response.status_code == 202, response.text
        assert response.json()["job"]["status"] == "QUEUED"
    await finish(env, tmp_path)
    result = await read(env, buyer, tid)
    assert result["status"] == "COMPLETED", result
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == int(resume_case)
        assert c.scalar(text("SELECT count(*) FROM confirmations")) == int(resume_case)


async def test_async_expired_unaccepted_wait_can_be_closed_without_approval(
    worker_env, buyer, tmp_path, monkeypatch
):
    from datetime import timedelta

    from agentmall.actions import service as actions

    env = worker_env
    tid = await thread(env, buyer)
    await start(env, buyer, tid, purchase=True)
    await finish(env, tmp_path)
    run = await read(env, buyer, tid)
    original_now = actions.database_now

    async def later(session):
        return await original_now(session) + timedelta(hours=1)

    monkeypatch.setattr(actions, "database_now", later)
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/{run['id']}/recover/async",
        headers=buyer,
        json={"request_id": run["request_id"]},
    )
    assert response.status_code == 202, response.text
    assert response.json()["job"]["status"] == "QUEUED", response.text
    async with process(env, tmp_path, advance_proposal_clock=True) as (child, _, path):
        assert await asyncio.wait_for(child.wait(), 25) == 0, path.read_text()
    result = await read(env, buyer, tid)
    assert result["status"] != "WAITING_INPUT", result
    # A fresh, explicit read-only goal may now be accepted in the same Thread.
    r = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/async",
        headers=buyer,
        json={"request_id": str(uuid4()), "message": "推荐键盘，不要购买。"},
    )
    assert r.status_code == 202, r.text
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0
        assert c.scalar(text("SELECT count(*) FROM confirmations")) == 0


async def test_committed_202_survives_real_api_process_sigkill(
    worker_env, buyer, tmp_path, unused_tcp_port
):
    import httpx

    env = worker_env
    tid = await thread(env, buyer)
    async with process(env, tmp_path, api_port=unused_tcp_port) as (api, _, log):
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{unused_tcp_port}", timeout=5
        ) as client:
            async with asyncio.timeout(20):
                while True:
                    try:
                        ready = await client.get("/openapi.json")
                        if ready.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert api.returncode is None, log.read_text()
                    await asyncio.sleep(0.05)
            r = await client.post(
                f"/api/v1/agent/threads/{tid}/runs/async",
                headers=buyer,
                json={"request_id": str(uuid4()), "message": "推荐键盘，不要购买。"},
            )
            assert r.status_code == 202, r.text
            run = r.json()
        api.kill()
        assert await api.wait() == -signal.SIGKILL
    await finish(env, tmp_path)
    result = await read(env, buyer, tid)
    assert result["id"] == run["id"]
    assert result["status"] == "COMPLETED", result
