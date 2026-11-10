from uuid import uuid4

from sqlalchemy import text
from t09_helpers import durable_env as durable_env
from t09_helpers import purchase_models, thread  # noqa: F401


async def test_async_acceptance_is_atomic_and_deduplicated(durable_env, buyer):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    body = {"request_id": str(uuid4()), "message": "推荐静音键盘，不要购买。"}
    path = f"/api/v1/agent/threads/{tid}/runs/async"
    first = await env[0].post(path, headers=buyer, json=body)
    assert first.status_code == 202, first.text
    replay = await env[0].post(path, headers=buyer, json=body)
    assert replay.status_code == 202
    assert replay.json()["id"] == first.json()["id"]
    assert first.json()["job"]["status"] == "QUEUED"
    assert first.json()["epoch"] == 0
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM agent_jobs")) == 1
        assert c.scalar(text("SELECT count(*) FROM agent_runs")) == 1
        assert c.scalar(text("SELECT count(*) FROM orders")) == 0
    state = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()
    assert state["runs"][0]["job"]["status"] == "QUEUED"
    changed = await env[0].post(path, headers=buyer, json={**body, "message": "改成鼠标"})
    assert changed.status_code == 409


async def test_async_scope_and_busy(durable_env, buyer, buyer2):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    path = f"/api/v1/agent/threads/{tid}/runs/async"
    body = {"request_id": str(uuid4()), "message": "推荐键盘"}
    assert (await env[0].post(path, headers=buyer2, json=body)).status_code == 404
    login = await env[0].post(
        "/api/v1/auth/login", json={"login": "merchant", "password": "AgentMall-demo-2026!"}
    )
    merchant = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (await env[0].post(path, headers=merchant, json=body)).status_code == 403
    assert (await env[0].post(path, headers=buyer, json=body)).status_code == 202
    assert (
        await env[0].post(path, headers=buyer, json={**body, "request_id": str(uuid4())})
    ).status_code == 409


async def test_enqueue_failure_rolls_back_run_and_memory(durable_env, buyer, monkeypatch):
    from agentmall.agents import jobs
    from agentmall.infra.errors import DomainError

    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)

    async def fail(*args, **kwargs):
        raise DomainError(503, "QUEUE_UNAVAILABLE", "Queue unavailable")

    monkeypatch.setattr(jobs, "enqueue", fail)
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/async",
        headers=buyer,
        json={"request_id": str(uuid4()), "message": "推荐300元以内静音键盘，不要购买。"},
    )
    assert response.status_code == 503
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM agent_runs")) == 0
        assert c.scalar(text("SELECT count(*) FROM agent_jobs")) == 0
        assert c.scalar(text("SELECT count(*) FROM agent_thread_contexts")) == 0


async def test_replayed_async_start_reads_state_while_worker_holds_thread_lock(durable_env, buyer):
    from uuid import UUID

    from agentmall.agents.locking import thread_lock

    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    path = f"/api/v1/agent/threads/{tid}/runs/async"
    body = {"request_id": str(uuid4()), "message": "推荐键盘，不要购买。"}
    original = await env[0].post(path, headers=buyer, json=body)
    assert original.status_code == 202
    async with thread_lock(env[3], UUID(tid)):
        replay = await env[0].post(path, headers=buyer, json=body)
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == original.json()["id"]
