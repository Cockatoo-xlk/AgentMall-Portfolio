"""R4: lexical intent, preflight and fenced activation failures over real PostgreSQL."""

from uuid import uuid4

import pytest
from conftest import row
from multiagent_helpers import install, make_models, route
from sqlalchemy import text
from t09_helpers import durable_env as durable_env
from t09_helpers import start, thread

from agentmall.agents import run_service
from agentmall.agents.purchase_intent import purchase_intent
from agentmall.infra.errors import DomainError


@pytest.mark.parametrize(
    "message,want",
    [
        ("修改买家身份", None),
        ("不允许修改买家账号", None),
        ("请帮我修改买家资料", None),
        ("不允许更改买家身份", None),
        ("查询键盘，不允许修改买家身份", None),
        ("我要买键盘", True),
        ("我要买家电", True),
        ("改买另一款键盘", True),
        ("不要购买", False),
    ],
)
def test_intent_respects_action_word_boundary(message, want):
    assert purchase_intent(message).requested is want


@pytest.mark.parametrize(
    "message", ["买第二款，不要购买", "我要买第一款，再买第二款", "我要买第一款，不要买第一款"]
)
def test_real_purchase_conflicts_still_require_clarification(message):
    with pytest.raises(DomainError) as exc:
        purchase_intent(message)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


async def prepare(env, buyer):
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    return await thread(env, buyer)


@pytest.mark.parametrize("deferred", [False, True])
async def test_ambiguous_intent_rejected_before_run_or_job_commit(durable_env, buyer, deferred):
    env = durable_env
    tid = await prepare(env, buyer)
    env[2].state.settings = env[3].model_copy()
    # Call the same service for both sync and durable dispatch, without changing HTTP mode.
    from sqlalchemy import select

    from agentmall.agents.run_schemas import RunCreate
    from agentmall.identity.models import User
    from agentmall.identity.service import actor_for

    async with env[2].state.sessions() as session:
        user = await session.scalar(select(User).where(User.login == "buyer1"))
        actor = actor_for(user, env[3])
    with pytest.raises(DomainError) as exc:
        await run_service.start_run(
            env[2],
            actor,
            __import__("uuid").UUID(tid),
            RunCreate(request_id=uuid4(), message="我要买键盘，不要购买"),
            deferred=deferred,
        )
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM agent_jobs")["n"] == 0
    assert row(env[1], f'SELECT count(*) n FROM "{env[3].checkpoint_schema}".checkpoints')["n"] == 0
    good = await start(env, buyer, tid, message="推荐键盘，不要购买")
    assert good.status_code == 201 and good.json()["status"] in {"COMPLETED", "WAITING_INPUT"}, (
        good.text
    )


@pytest.mark.parametrize("phase", ["runtime", "budget"])
async def test_early_domain_error_keeps_original_code_and_finishes_owned_run(
    durable_env, buyer, monkeypatch, phase
):
    env = durable_env
    tid = await prepare(env, buyer)

    def fail(*args, **kwargs):
        raise DomainError(409, "CONTEXT_CLARIFICATION_REQUIRED", "synthetic init failure")

    async def fail_async(*args, **kwargs):
        fail()

    with monkeypatch.context() as patch:
        if phase == "runtime":
            patch.setattr(run_service, "RunContext", fail)
        else:
            patch.setattr(run_service.DurableBudget, "reload", fail_async)
        response = await start(env, buyer, tid, message="推荐键盘，不要购买")
    assert (
        response.status_code == 409 and response.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
    )
    run = row(
        env[1],
        "SELECT id,status,last_error,worker_token,lock_pid,budget,node_journal,resume_journal "
        "FROM agent_runs",
    )
    assert run["status"] == "PARTIAL" and run["last_error"] == "CONTEXT_CLARIFICATION_REQUIRED"
    assert run["worker_token"] is None and run["lock_pid"] is None
    assert run["budget"] == run["node_journal"] == run["resume_journal"] == {}
    event = row(env[1], "SELECT payload_summary FROM run_events WHERE event_type='run_state'")[
        "payload_summary"
    ]
    assert event == {"status": "PARTIAL", "error_code": "CONTEXT_CLARIFICATION_REQUIRED"}
    assert row(env[1], f'SELECT count(*) n FROM "{env[3].checkpoint_schema}".checkpoints')["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    good = await start(env, buyer, tid, message="推荐键盘，不要购买")
    assert good.status_code == 201 and good.json()["status"] in {"COMPLETED", "WAITING_INPUT"}, (
        good.text
    )


async def actor_in(env):
    from sqlalchemy import select

    from agentmall.identity.models import User
    from agentmall.identity.service import actor_for

    async with env[2].state.sessions() as session:
        user = await session.scalar(select(User).where(User.login == "buyer1"))
        return actor_for(user, env[3])


@pytest.mark.parametrize("phase", ["runtime", "reload", "render", "checkpoint"])
async def test_unexpected_activation_failure_is_recoverable_on_same_run(
    durable_env, buyer, monkeypatch, phase
):
    env = durable_env
    tid = await prepare(env, buyer)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic activation failure: never persist this text")

    async def fail_async(*args, **kwargs):
        fail()

    with monkeypatch.context() as patch:
        if phase == "runtime":
            patch.setattr(run_service, "RunContext", fail)
        elif phase == "reload":
            patch.setattr(run_service.DurableBudget, "reload", fail_async)
        elif phase == "render":
            patch.setattr(run_service, "render", fail)
        else:
            patch.setattr(run_service, "checkpoint_saver", fail)
        response = await start(env, buyer, tid, message="推荐键盘，不要购买")
    assert response.status_code == 201, response.text
    failed = response.json()
    assert failed["status"] == "PARTIAL" and failed["last_error"] == "EXECUTION_INTERRUPTED"
    stored = row(env[1], "SELECT worker_token,lock_pid FROM agent_runs")
    assert stored["worker_token"] is None and stored["lock_pid"] is None
    assert "synthetic activation" not in str(
        row(env[1], "SELECT jsonb_agg(payload_summary) payloads FROM run_events")
    )
    # A recoverable failed Run reserves the thread until explicit, same-identity recovery.
    busy = await start(env, buyer, tid, message="推荐键盘，不要购买")
    assert busy.status_code == 409 and busy.json()["code"] == "THREAD_BUSY"
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    recovered = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/{failed['id']}/recover",
        headers=buyer,
        json={"request_id": failed["request_id"]},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["id"] == failed["id"] and recovered.json()["status"] != "RUNNING"
    assert recovered.json()["epoch"] == 2
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0


@pytest.mark.parametrize("lost", ["epoch", "lock"])
async def test_failed_old_executor_cannot_finalize_successor_or_write_without_lock(
    durable_env, buyer, monkeypatch, lost
):
    env = durable_env
    tid = await prepare(env, buyer)
    successor = uuid4()

    def fail(*args, **kwargs):
        with env[1].begin() as conn:
            if lost == "epoch":
                conn.execute(
                    text("UPDATE agent_runs SET epoch=epoch+1,worker_token=:token"),
                    {"token": successor},
                )
            else:
                conn.execute(text("SELECT pg_terminate_backend(lock_pid) FROM agent_runs"))
        raise DomainError(409, "CONTEXT_CLARIFICATION_REQUIRED", "synthetic failure")

    monkeypatch.setattr(run_service, "RunContext", fail)
    response = await start(env, buyer, tid, message="推荐键盘，不要购买")
    assert response.status_code == 409 and response.json()["code"] == "STALE_EXECUTOR"
    stored = row(env[1], "SELECT status,last_error,epoch,worker_token FROM agent_runs")
    assert stored["status"] == "RUNNING" and stored["last_error"] is None
    if lost == "epoch":
        assert stored["epoch"] == 2 and stored["worker_token"] == successor
    assert row(env[1], "SELECT count(*) n FROM run_events WHERE event_type='run_state'")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0


async def test_deferred_activation_domain_failure_finishes_run_and_blocks_job(
    durable_env, buyer, monkeypatch
):
    from uuid import UUID

    from agentmall.agents.run_schemas import RunCreate
    from agentmall.agents.worker import execute_job

    env = durable_env
    tid = await prepare(env, buyer)
    run, created = await run_service.start_run(
        env[2],
        await actor_in(env),
        UUID(tid),
        RunCreate(request_id=uuid4(), message="推荐键盘，不要购买"),
        deferred=True,
    )
    assert created and run["job"]["status"] == "QUEUED"

    def fail(*args, **kwargs):
        raise DomainError(409, "CONTEXT_CLARIFICATION_REQUIRED", "synthetic init")

    monkeypatch.setattr(run_service, "RunContext", fail)
    job = row(env[1], "SELECT id FROM agent_jobs")
    assert await execute_job(env[2], job["id"], UUID(tid))
    stored = row(env[1], "SELECT status,last_error,worker_token,lock_pid FROM agent_runs")
    assert (
        stored["status"] == "PARTIAL" and stored["last_error"] == "CONTEXT_CLARIFICATION_REQUIRED"
    )
    assert stored["worker_token"] is None and stored["lock_pid"] is None
    job = row(env[1], "SELECT status,last_error,claim_token FROM agent_jobs")
    assert job["status"] == "BLOCKED" and job["last_error"] == stored["last_error"]
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
