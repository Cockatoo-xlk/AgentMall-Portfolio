import asyncio
from uuid import UUID, uuid4

import pytest
from conftest import row
from multiagent_helpers import install, make_models, route
from sqlalchemy import text
from t09_helpers import confirm, purchase_models, resume, start, thread  # noqa: F401
from t09_helpers import durable_env as durable_env


async def test_same_thread_conflict_different_threads_parallel_and_no_leaked_locks(
    durable_env, buyer
):
    env = durable_env
    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0

    async def delayed(messages):
        nonlocal count
        count += 1
        if count == 2:
            entered.set()
        await release.wait()
        return route("finish")(messages)

    await install(env, make_models(supervisor=[delayed, delayed]), indexed=False)
    first = await thread(env, buyer)
    second = await thread(env, buyer)
    tasks = [
        asyncio.create_task(start(env, buyer, tid, message="结束本次测试，不要购买"))
        for tid in [first, second]
    ]
    try:
        await asyncio.wait_for(entered.wait(), 5)
        conflict = await start(env, buyer, first)
        assert conflict.status_code == 409, conflict.text
    finally:
        release.set()
    results = await asyncio.gather(*tasks)
    assert all(r.status_code == 201 and r.json()["status"] == "COMPLETED" for r in results)
    assert (
        row(
            env[1],
            "SELECT count(*) n FROM pg_stat_activity WHERE application_name IN (:a,:b)",
            a=f"agentmall:lock:{first}",
            b=f"agentmall:lock:{second}",
        )["n"]
        == 0
    )


async def test_same_thread_concurrent_resume_and_lost_connection_fences_old_worker(
    durable_env, buyer, monkeypatch
):
    from agentmall.agents import durable_graph

    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    entered = asyncio.Event()
    release = asyncio.Event()
    original = durable_graph.execute_confirmation

    async def delayed(runtime, payload):
        entered.set()
        await release.wait()
        return await original(runtime, payload)

    monkeypatch.setattr(durable_graph, "execute_confirmation", delayed)
    resume_id = str(uuid4())
    task = asyncio.create_task(resume(env, buyer, tid, run, cid, resume_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert (await resume(env, buyer, tid, run, cid, resume_id)).status_code == 409
        pid = row(env[1], "SELECT lock_pid pid FROM agent_runs WHERE id=:id", id=run["id"])["pid"]
        with env[1].begin() as c:
            assert c.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}) is True
        monkeypatch.setattr(durable_graph, "execute_confirmation", original)
        recovered = await resume(env, buyer, tid, run, cid, resume_id)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == "COMPLETED"
    finally:
        release.set()
    stale = await task
    assert stale.status_code == 409, stale.text
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 1
    print(
        "LOCK_CONNECTION_TERMINATED owned PID; replacement completed; stale executor=409; orders=1"
    )


async def test_budget_atomic_reservation_survives_runtime_reconstruction(durable_env, buyer):
    from agentmall.agents.budgets import RunStopped
    from agentmall.agents.durable_budget import DurableBudget, node_key
    from agentmall.agents.locking import claim_execution, thread_lock
    from agentmall.agents.models import AgentRun

    env = durable_env
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    async with thread_lock(env[3], tid) as lock:
        async with env[2].state.sessions.begin() as session:
            record = await session.get(AgentRun, UUID(run["id"]))
            fence = await claim_execution(session, record, lock, env[2].state.sessions)
        first = DurableBudget(fence)
        second = DurableBudget(fence)
        tokens = await asyncio.gather(first.start_model(), second.start_model())
        assert len(set(tokens)) == 2
        await second.reload()
        assert second.used["models"] == run["budget"]["models"] + 2
        assert second.used["output_tokens"] == run["budget"]["output_tokens"] + 4096
        token = node_key.set("replayed-node")
        try:
            await first.take("steps")
            await second.take("steps")
        finally:
            node_key.reset(token)
        rebuilt = DurableBudget(fence)
        await rebuilt.reload()
        assert rebuilt.used["steps"] == run["budget"]["steps"] + 1
        assert rebuilt.seconds_left > 80
        while True:
            try:
                await rebuilt.start_model()
            except RunStopped:
                break
        before = dict(rebuilt.used)
        again = DurableBudget(fence)
        await again.reload()
        with pytest.raises(RunStopped):
            await again.start_model()
        assert again.used == before
        assert before["output_tokens"] == 12000


async def test_tool_reservations_are_atomic_across_parallel_branch_budgets(durable_env, buyer):
    from agentmall.agents.budgets import RunStopped
    from agentmall.agents.durable_budget import DurableBudget
    from agentmall.agents.locking import claim_execution, thread_lock
    from agentmall.agents.models import AgentRun

    env = durable_env
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    async with thread_lock(env[3], tid) as lock:
        async with env[2].state.sessions.begin() as session:
            record = await session.get(AgentRun, UUID(run["id"]))
            fence = await claim_execution(session, record, lock, env[2].state.sessions)
        budgets = [DurableBudget(fence), DurableBudget(fence)]
        await asyncio.gather(
            *(b.claim_tools([str(i)], ["same-tool"]) for i, b in enumerate(budgets))
        )
        rebuilt = DurableBudget(fence)
        await rebuilt.reload()
        assert rebuilt.used["tools"] == 2
        with pytest.raises(RunStopped, match="REPEATED_TOOL_CALL"):
            await rebuilt.claim_tools(["third"], ["same-tool"])
        with pytest.raises(RunStopped, match="INVALID_TOOL_BATCH"):
            await rebuilt.claim_tools(["0"], ["different-tool"])
        await rebuilt.reload()
        assert rebuilt.used["tools"] == 2
