"""RECONSTRUCTED_FIXTURE: live event failure shapes, never Provider response replays."""

from uuid import uuid4

import pytest
from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import (
    ai,
    call,
    choose_purchase,
    final,
    install,
    make_models,
    payload,
    route,
)
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env
from test_baseline_fairness import SingleModel


def events(env):
    from sqlalchemy import text

    with env[1].connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT event_type,payload_summary FROM run_events ORDER BY seq")
            ).mappings()
        ]


@pytest.mark.parametrize("corrects", [True, False])
async def test_single_read_only_progress_cannot_finish_purchase(
    durable_env, buyer, product, corrects
):
    env = durable_env
    await install(env, make_models())
    correction = ai(call("prepare_checkout", {"product_id": product})) if corrects else final()
    model = SingleModel(
        role="order",
        script=[ai(call("get_product", {"product_id": product})), final(), correction, final()],
    )
    env[2].state.durable_single_model = model
    tid = await thread(env, buyer, "single")
    run = (await start(env, buyer, tid, message=f"帮我买一件商品{product}，送演示家庭")).json()
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert run["budget"]["models"] == 3
    contexts = [payload(messages) for messages in model.seen]
    assert all("goal" not in c for c in contexts)  # no misleading inspect_orders task
    assert contexts[-1]["orchestration_feedback"]["error_code"] == "INCOMPLETE_PURCHASE"
    if corrects:
        assert run["status"] == "WAITING_INPUT", run
        cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, run, cid)).json()
        assert done["status"] == "COMPLETED", done
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    else:
        assert run["status"] == "PARTIAL", run
        assert "INCOMPLETE_PURCHASE" in run["result"]["error_codes"]
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0


async def test_single_mixed_write_repair_is_one_per_run_across_resume(durable_env, buyer, product):
    env = durable_env
    await install(env, make_models())

    def bad():
        return ai(call("get_cart"), call("prepare_checkout", {"product_id": product}))

    model = SingleModel(
        role="order",
        script=[
            ai(call("get_product", {"product_id": product})),
            bad(),
            ai(call("prepare_checkout", {"product_id": product})),
            bad(),
        ],
    )
    env[2].state.durable_single_model = model
    tid = await thread(env, buyer, "single")
    run = (await start(env, buyer, tid, message=f"帮我买一件商品{product}，送演示家庭")).json()
    assert run["status"] == "WAITING_INPUT", run
    assert run["budget"]["tools"] == 2  # rejected whole batch executed zero tools
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    request_id = str(uuid4())
    response = await resume(env, buyer, tid, run, cid, request_id=request_id)
    # Simulate losing the body: reread persistent Thread, never submit another operation.
    reread = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()
    done = reread["runs"][0]
    assert response.status_code == 200
    assert done["status"] == "PARTIAL", done
    assert "UNORDERED_WRITE_BATCH" in done["result"]["error_codes"]
    assert done["budget"]["models"] == 4  # no second repair after Resume
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
    assert (
        row(env[1], "SELECT budget FROM agent_runs")["budget"]["orchestration_repair"]["error_code"]
        == "UNORDERED_WRITE_BATCH"
    )
    assert len([e for e in events(env) if e["event_type"] == "orchestration_repair"]) == 1


def mixed_handoff(messages):
    first = route("aftersales", "prepare_return", "return", read_only=False)(messages)
    second = route("shopping", "find_products", "replacement")(messages)
    return ai(
        call(
            "route",
            {
                "tasks": [
                    first.tool_calls[0]["args"]["tasks"][0],
                    second.tool_calls[0]["args"]["tasks"][0],
                ],
                "terminal": None,
            },
        )
    )


async def test_multi_repair_serializes_writes_and_waits_between_two_actions(
    durable_env, buyer, product
):
    env = durable_env
    original = await delivered_order(env[0], buyer, product)
    read = ai(
        call("get_order", {"order_id": original["id"]}),
        call("check_eligibility", {"order_id": original["id"], "reason_code": "QUALITY_ISSUE"}),
        call("retrieve_policies", {"order_id": original["id"], "query": "质量问题退货期限"}),
    )
    prepare = ai(
        call(
            "prepare_return",
            {"order_id": original["id"], "reason_code": "QUALITY_ISSUE", "description": "合成故障"},
        )
    )
    models = make_models(
        supervisor=[
            route("aftersales", "assess_return", "inspect"),
            mixed_handoff,
            route("aftersales", "prepare_return", "return", depends=["inspect"], read_only=False),
            route("shopping", "find_products", "replacement"),
            route("order", "prepare_checkout", "buy", depends=["replacement"], read_only=False),
            route("finish"),
        ],
        aftersales=[read, prepare],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{original['id']}有质量问题，想退掉；另准备购买一款500元以内静音键盘，排除原商品，送演示宿舍",
        )
    ).json()
    assert run["status"] == "WAITING_INPUT", run
    assert run["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
    assert not models["shopping"].seen  # replacement work waits for this independent decision
    assert (
        payload(models["supervisor"].seen[2])["orchestration_feedback"]["error_code"]
        == "UNORDERED_WRITE_HANDOFF"
    )
    cid1 = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    next_run = (await resume(env, buyer, tid, run, cid1)).json()
    assert next_run["status"] == "WAITING_INPUT", next_run
    assert next_run["pending_confirmation"]["action_type"] == "CHECKOUT"
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert (await resume(env, buyer, tid, next_run, cid1)).status_code == 409
    cid2 = await confirm(env, buyer, next_run["pending_confirmation"]["proposal_id"])
    assert cid2 != cid1
    done = (await resume(env, buyer, tid, next_run, cid2)).json()
    assert done["status"] == "COMPLETED", done
    assert done["budget"]["models"] == 10
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 1
    assert any(
        e["payload_summary"].get("error_code") == "UNORDERED_WRITE_HANDOFF" for e in events(env)
    )


async def test_failed_repair_keeps_rejections_when_node_never_checkpoints(durable_env, buyer):
    env = durable_env
    models = make_models(supervisor=[mixed_handoff, mixed_handoff])
    await install(env, models)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message="查询商品并申请退货")).json()
    assert "UNORDERED_WRITE_HANDOFF" in run["result"]["error_codes"]
    assert run["budget"]["models"] == 2
    assert run["budget"]["delegations"] == 0
    rejected = [e for e in events(env) if e["event_type"] == "orchestration_rejected"]
    assert len(rejected) == 2
    assert all(e["payload_summary"]["error_code"] == "UNORDERED_WRITE_HANDOFF" for e in rejected)
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0


async def test_repair_does_not_extend_model_budget(durable_env, buyer, product, monkeypatch):
    from agentmall.agents import run_service
    from agentmall.agents.budgets import Limits
    from agentmall.agents.durable_budget import DurableBudget

    env = durable_env
    await install(env, make_models())
    env[2].state.durable_single_model = SingleModel(
        role="order",
        script=[
            ai(call("get_product", {"product_id": product})),
            final(),
            ai(call("prepare_checkout", {"product_id": product})),
        ],
    )
    monkeypatch.setattr(
        run_service, "DurableBudget", lambda fence: DurableBudget(fence, Limits(models=2))
    )
    tid = await thread(env, buyer, "single")
    run = (await start(env, buyer, tid, message=f"帮我买一件商品{product}，送演示家庭")).json()
    assert run["budget"]["models"] == 2
    assert "BUDGET_EXCEEDED" in run["result"]["error_codes"]
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0


async def test_single_pending_return_interrupt_precedes_purchase_completion_check(
    durable_env, buyer, product
):
    """Review regression: a return_direct proposal is not a model all-done answer."""
    env = durable_env
    original = await delivered_order(env[0], buyer, product)
    alternative = str(
        row(
            env[1],
            "SELECT id FROM products WHERE active AND id<>:id ORDER BY id LIMIT 1",
            id=product,
        )["id"]
    )
    await install(env, make_models())
    model = SingleModel(
        role="order",
        script=[
            ai(
                call("get_order", {"order_id": original["id"]}),
                call("get_product", {"product_id": alternative}),
            ),
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": original["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "合成故障",
                    },
                )
            ),
            ai(call("prepare_checkout", {"product_id": alternative})),
            final(),
        ],
    )
    env[2].state.durable_single_model = model
    tid = await thread(env, buyer, "single")
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{original['id']}有质量问题想退掉，另帮我买一件商品，送演示家庭",
        )
    ).json()
    assert run["status"] == "WAITING_INPUT", run
    assert run["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
    assert run["budget"]["models"] == 2
    assert "orchestration_repair" not in row(env[1], "SELECT budget FROM agent_runs")["budget"]
    assert (
        row(env[1], "SELECT count(*) n FROM action_proposals WHERE action_type='CHECKOUT'")["n"]
        == 1
    )
    cid1 = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    run2 = (await resume(env, buyer, tid, run, cid1)).json()
    assert run2["pending_confirmation"]["action_type"] == "CHECKOUT"
    cid2 = await confirm(env, buyer, run2["pending_confirmation"]["proposal_id"])
    assert cid1 != cid2
    assert (await resume(env, buyer, tid, run2, cid2)).json()["status"] == "COMPLETED"
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
