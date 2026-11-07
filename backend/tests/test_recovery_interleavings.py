import asyncio
from uuid import uuid4

import pytest
from multiagent_helpers import ai, call, final, install, make_models, route
from recovery_diagnostics import capture
from t09_helpers import durable_env as durable_env
from t09_helpers import start, thread


@pytest.mark.parametrize("repetition", range(5))
@pytest.mark.parametrize("order", ["order_journal_first", "shopping_journal_first"])
async def test_parallel_journals_recover_without_repeating_completed_calls(
    durable_env, buyer, monkeypatch, order, repetition, recovery_db_failure=False
):
    from langgraph.pregel.main import Pregel

    from agentmall.agents import run_service

    env = durable_env

    def parallel(messages):
        a = route("shopping", "find_products", "shop")(messages).tool_calls[0]["args"]["tasks"][0]
        b = route("order", "inspect_orders", "inspect")(messages).tool_calls[0]["args"]["tasks"][0]
        return ai(call("route", {"tasks": [a, b]}))

    models = make_models(
        supervisor=[parallel, route("finish")],
        shopping=[ai(call("retrieve_products", {"query": "键盘"})), final()],
        order=[ai(call("list_orders")), final()],
    )
    order_ready = asyncio.Event()
    shopping_ready = asyncio.Event()
    response_ready = asyncio.Event()
    if order == "shopping_journal_first":

        async def interrupted_final(messages):
            order_ready.set()
            await shopping_ready.wait()
            # Cancellation lands after tool completion but before final-model completion.
            await response_ready.wait()
            return final()

        models["order"].script[-1] = interrupted_final
    await install(env, models)
    original = run_service.NodeStore.save
    exceptions = []

    async def save(self, key, output, trace):
        if key == "order:inspect":
            if order == "order_journal_first":
                await original(self, key, output, trace)
                order_ready.set()
                return
            order_ready.set()
            await shopping_ready.wait()
            # Force the sibling to hit the checkpoint/journal cancellation window.
            await original(self, key, output, trace)
            return
        await original(self, key, output, trace)
        if key == "shopping:shop":
            shopping_ready.set()
            await order_ready.wait()
            response_ready.set()
            raise RuntimeError("controlled journal/checkpoint gap")

    original_invoke = Pregel.ainvoke

    async def invoke(self, *args, **kwargs):
        try:
            return await original_invoke(self, *args, **kwargs)
        except BaseException as exc:
            exceptions.append({"stage": "graph.ainvoke", "type": type(exc).__name__})
            raise

    monkeypatch.setattr(Pregel, "ainvoke", invoke)
    monkeypatch.setattr(run_service.NodeStore, "save", save)
    tid = await thread(env, buyer)
    rid = str(uuid4())
    goal = "推荐键盘并查询本人的订单，不要购买"
    first = (await start(env, buyer, tid, rid, message=goal)).json()
    assert first["status"] == "PARTIAL"
    before = await capture(env, tid, first, models, order + "-before", exceptions)
    counts = {k: len(m.seen) for k, m in models.items()}
    monkeypatch.setattr(run_service.NodeStore, "save", original)
    if recovery_db_failure:
        from sqlalchemy.exc import OperationalError

        cached = run_service.NodeStore.cached

        async def unavailable(self, key):
            raise OperationalError("synthetic recovery disconnect", {}, None)

        monkeypatch.setattr(run_service.NodeStore, "cached", unavailable)
        failed = (await start(env, buyer, tid, rid, message=goal)).json()
        assert failed["last_error"] == "DATABASE_UNAVAILABLE"
        assert {k: len(m.seen) for k, m in models.items()} == counts
        monkeypatch.setattr(run_service.NodeStore, "cached", cached)
    done = (await start(env, buyer, tid, rid, message=goal)).json()
    after = await capture(env, tid, done, models, order + "-after", exceptions)
    assert done["status"] == "COMPLETED", after
    assert {x["subtask_id"] for x in done["result"]["results"]} == {"shop", "inspect"}
    assert all(x["status"] == "done" for x in done["result"]["results"]), after
    for role in ("shopping", "order"):
        assert len(models[role].seen) == counts[role], (before, after)
    assert done["id"] == first["id"] and done["epoch"] == first["epoch"] + (
        2 if recovery_db_failure else 1
    )
    assert done["budget"]["models"] == first["budget"]["models"] + 1
    assert done["budget"]["delegations"] == 2 and done["budget"]["tools"] == 2


async def test_legacy_send_payload_recovers_without_new_metadata(durable_env, buyer, monkeypatch):
    from agentmall.agents import durable_graph

    original = durable_graph.Send

    def legacy(target, payload):
        return original(target, {k: v for k, v in payload.items() if k != "branch_ids"})

    monkeypatch.setattr(durable_graph, "Send", legacy)
    await test_parallel_journals_recover_without_repeating_completed_calls(
        durable_env, buyer, monkeypatch, "order_journal_first", 0
    )


async def test_branch_database_error_survives_bounded_drain_deadline(
    durable_env, buyer, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from agentmall.agents import run_service
    from agentmall.agents.durable_budget import DurableBudget

    env = durable_env
    failed = asyncio.Event()

    def parallel(messages):
        a = route("shopping", "find_products", "shop")(messages).tool_calls[0]["args"]["tasks"][0]
        b = route("order", "inspect_orders", "inspect")(messages).tool_calls[0]["args"]["tasks"][0]
        return ai(call("route", {"tasks": [a, b]}))

    async def stalled(messages):
        await failed.wait()
        await asyncio.Event().wait()

    models = make_models(
        supervisor=[parallel],
        shopping=[ai(call("retrieve_products", {"query": "键盘"})), final()],
        order=[ai(call("list_orders")), stalled],
    )
    await install(env, models)
    original = run_service.NodeStore.save
    from agentmall.agents.budgets import Limits

    initialize = DurableBudget.__init__

    def short_run(self, fence, limits=None):
        initialize(self, fence, Limits(seconds=3))

    monkeypatch.setattr(DurableBudget, "__init__", short_run)

    async def save(self, key, output, trace):
        await original(self, key, output, trace)
        if key == "shopping:shop":
            failed.set()
            raise OperationalError("synthetic branch disconnect", {}, None)

    monkeypatch.setattr(run_service.NodeStore, "save", save)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    assert run["status"] == "PARTIAL" and run["last_error"] == "DATABASE_UNAVAILABLE", run


async def test_same_request_recovers_after_one_recovery_database_failure(
    durable_env, buyer, monkeypatch
):
    await test_parallel_journals_recover_without_repeating_completed_calls(
        durable_env, buyer, monkeypatch, "order_journal_first", 0, recovery_db_failure=True
    )
