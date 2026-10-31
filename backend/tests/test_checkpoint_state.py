from uuid import uuid4

from t09_helpers import durable_env as durable_env
from t09_helpers import purchase_models, start, thread  # noqa: F401


async def test_state_reopens_with_completed_tasks_references_and_budget(durable_env, buyer):
    from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    async with checkpoint_saver(env[3]) as saver:
        saved = await saver.aget_tuple(checkpoint_config(tid, run["id"]))
        state = saved.checkpoint["channel_values"]["runtime_state"]
        assert set(state["completed"]) == {"shop", "buy"}
        assert state["completed"]["buy"]["proposal_ids"] == run["result"]["proposal_ids"]
        assert state["pending"] == {}
        assert state["budget"]["used"]["models"] >= 5
        assert state["references"] and state["seen_tasks"]
        assert await saver.aget_tuple(checkpoint_config(str(uuid4()), run["id"])) is None


async def test_parallel_branches_keep_both_results_after_checkpoint_failure(
    durable_env, buyer, monkeypatch
):
    from multiagent_helpers import ai, call, final, install, make_models, route

    from agentmall.agents import run_service

    env = durable_env

    def parallel(messages):
        first = route("shopping", "find_products", "shop")(messages).tool_calls[0]["args"]["tasks"][
            0
        ]
        second = route("order", "inspect_orders", "inspect")(messages).tool_calls[0]["args"][
            "tasks"
        ][0]
        return ai(call("route", {"tasks": [first, second]}))

    models = make_models(
        supervisor=[parallel, route("finish")],
        shopping=[ai(call("retrieve_products", {"query": "键盘"})), final()],
        order=[ai(call("list_orders")), final()],
    )
    await install(env, models)
    original = run_service.NodeStore.save

    async def fail_after_journal(self, key, output, trace):
        await original(self, key, output, trace)
        if key == "shopping:shop":
            raise RuntimeError("injected node/checkpoint gap")

    monkeypatch.setattr(run_service.NodeStore, "save", fail_after_journal)
    tid = await thread(env, buyer)
    rid = str(uuid4())
    partial = (await start(env, buyer, tid, rid)).json()
    assert partial["status"] == "PARTIAL"
    counts = {k: len(v.seen) for k, v in models.items()}
    monkeypatch.setattr(run_service.NodeStore, "save", original)
    done = (await start(env, buyer, tid, rid)).json()
    assert done["status"] == "COMPLETED", done
    assert {r["subtask_id"] for r in done["result"]["results"]} == {"shop", "inspect"}
    assert len(models["shopping"].seen) == counts["shopping"]
    assert len(models["order"].seen) == counts["order"]
    assert done["budget"]["delegations"] == 2
    assert done["budget"]["tools"] == 2


async def test_single_mode_uses_same_confirmation_budget_and_recovery(durable_env, buyer, product):
    from multiagent_helpers import MultiModel, ai, call, final
    from t09_helpers import confirm, resume

    from agentmall.agents.specialist_tools import ALLOWLISTS

    class SingleModel(MultiModel):
        def bind_tools(self, tools, **kwargs):
            self.bound = [t.name for t in tools]
            assert set(self.bound) == {name for names in ALLOWLISTS.values() for name in names}
            return self.bind(**kwargs)

    env = durable_env
    env[2].state.durable_single_model = SingleModel(
        role="single", script=[ai(call("prepare_checkout", {"product_id": product})), final()]
    )
    tid = await thread(env, buyer, "single")
    run = (await start(env, buyer, tid, message=f"准备购买一件 {product}，送演示宿舍")).json()
    assert run["status"] == "WAITING_INPUT", run
    assert run["budget"]["models"] == 1
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    done = await resume(env, buyer, tid, run, cid)
    assert done.json()["status"] == "COMPLETED", done.text
    # T12 continues the original goal after confirmation, charging the same ledger.
    assert done.json()["budget"]["models"] == 2


async def test_database_disconnect_is_recoverable_not_sqlalchemy_document_code(
    durable_env, buyer, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from agentmall.agents import run_service

    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    rid = str(uuid4())
    original = run_service.NodeStore.save

    async def fail(self, key, output, trace):
        await original(self, key, output, trace)
        if key == "bootstrap:0":
            raise OperationalError("synthetic disconnect", {}, None)

    monkeypatch.setattr(run_service.NodeStore, "save", fail)
    run = (await start(env, buyer, tid, rid)).json()
    assert run["last_error"] == "DATABASE_UNAVAILABLE", run
    monkeypatch.setattr(run_service.NodeStore, "save", original)
    recovered = (await start(env, buyer, tid, rid)).json()
    assert recovered["status"] == "WAITING_INPUT", recovered
    assert recovered["epoch"] == 2
