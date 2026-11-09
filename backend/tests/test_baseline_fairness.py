"""T12 capability contracts, before any sealed evaluation; real PG and official saver."""

import json
from dataclasses import asdict

import pytest
from aftersales_helpers import delivered_order
from conftest import env as base_env
from conftest import row
from multiagent_helpers import (
    MultiModel,
    ai,
    assessment_reads,
    call,
    choose_purchase,
    final,
    install,
    last_result,
    make_models,
    route,
)
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env

from agentmall.agents.budgets import Limits
from agentmall.agents.specialist_tools import ALLOWLISTS


@pytest.fixture
async def env():
    from sqlalchemy.engine import make_url

    from agentmall.infra.config import Settings

    url = make_url(Settings().test_database_url.get_secret_value())
    assert (url.host, url.port, url.database) == ("127.0.0.1", 55433, "agentmall_test")
    generator = base_env.__wrapped__()
    try:
        yield await anext(generator)
    finally:
        await generator.aclose()


class SingleModel(MultiModel):
    def bind_tools(self, tools, **kwargs):
        self.bound = [t.name for t in tools]
        assert set(self.bound) == {name for names in ALLOWLISTS.values() for name in names}
        return self.bind(**kwargs)


def buy_retrieved(messages):
    return ai(
        call("prepare_checkout", {"product_id": last_result(messages)["data"]["items"][0]["id"]})
    )


@pytest.mark.parametrize("architecture", ["single", "multi"])
@pytest.mark.parametrize(
    "decisions", [("approve", "approve"), ("reject", "approve"), ("approve", "reject")]
)
async def test_same_goal_two_independent_business_confirmations(
    durable_env, buyer, product, architecture, decisions
):
    env = durable_env
    old = await delivered_order(env[0], buyer, product)
    inspect = ai(
        call("get_order", {"order_id": old["id"]}),
        call("check_eligibility", {"order_id": old["id"], "reason_code": "QUALITY_ISSUE"}),
        call("retrieve_policies", {"order_id": old["id"], "query": "质量问题退货期限"}),
    )
    prepare = ai(
        call(
            "prepare_return",
            {"order_id": old["id"], "reason_code": "QUALITY_ISSUE", "description": "合成按键故障"},
        )
    )
    search = ai(call("retrieve_products", {"query": "静音键盘"}))
    models = make_models(
        supervisor=[
            route("aftersales", "assess_return", "assessment"),
            route(
                "aftersales", "prepare_return", "return", depends=["assessment"], read_only=False
            ),
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            route("finish"),
        ],
        aftersales=[*assessment_reads(old["id"]), prepare],
        shopping=[search, final()],
        order=[choose_purchase],
    )
    await install(env, models)
    single = SingleModel(role="order", script=[inspect, prepare, search, buy_retrieved, final()])
    env[2].state.durable_single_model = single
    goal = (
        f"订单{old['id']}有质量问题，想退掉。再推荐另一款500元以内静音键盘，"
        "准备购买1件，送演示宿舍。"
    )
    tid = await thread(env, buyer, architecture)
    response = await start(env, buyer, tid, message=goal)
    assert response.status_code == 201, response.text
    run = response.json()
    confirmations = []
    proposals = []
    for index, decision in enumerate(decisions):
        assert run["status"] == "WAITING_INPUT", (index, run)
        pending = run["pending_confirmation"]
        pid = pending["proposal_id"]
        assert pending["action_type"] == ("RETURN_REQUEST" if index == 0 else "CHECKOUT")
        assert pid not in proposals
        proposals.append(pid)
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        cid = await confirm(env, buyer, pid, decision)
        assert cid not in confirmations
        confirmations.append(cid)
        response = await resume(env, buyer, tid, run, cid)
        assert response.status_code == 200, response.text
        previous = run
        run = response.json()
        if index == 0 and run["pending_confirmation"]:
            stale = await resume(env, buyer, tid, run, cid)
            assert stale.status_code == 409
    assert run["status"] == "COMPLETED", run
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1 + (decisions[1] == "approve")
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == (
        decisions[0] == "approve"
    )
    assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
    assert run["result"]["budget"]["limits"] == asdict(Limits())
    assert set(run["result"]["proposal_ids"]) == set(proposals)
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 1
    replay = await resume(env, buyer, tid, previous, confirmations[-1])
    assert replay.status_code == 409  # A new request cannot replay the old interrupt.
    if architecture == "single":
        assert all(not model.seen for model in models.values())
        contexts = [
            json.loads(m.content) for batch in single.seen for m in batch if m.type == "human"
        ]
        assert any(c.get("user_goal") == goal for c in contexts)
        assert any(c.get("committed_facts") for c in contexts)


@pytest.mark.parametrize("architecture", ["single", "multi"])
async def test_clarification_continues_same_run(durable_env, buyer, architecture):
    from uuid import uuid4

    env = durable_env
    models = make_models(
        supervisor=[
            route("clarify"),
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    env[2].state.durable_single_model = SingleModel(
        role="order",
        script=[
            final("请补充数量地址"),
            ai(call("retrieve_products", {"query": "静音键盘"})),
            buy_retrieved,
            final(),
        ],
    )
    tid = await thread(env, buyer, architecture)
    run = (await start(env, buyer, tid, message="想买静音键盘")).json()
    assert run["status"] == "WAITING_INPUT", run
    assert run["pending_confirmation"]["type"] == "clarification"
    result = await env[0].post(
        f"/api/v1/agent/threads/{tid}/resume",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "run_id": run["id"],
            "interrupt_id": run["pending_confirmation"]["interrupt_id"],
            "clarification": "300元以内，准备购买一款，送演示宿舍",
        },
    )
    assert result.status_code == 200, result.text
    clarified = result.json()
    assert clarified["id"] == run["id"]
    assert clarified["status"] == "WAITING_INPUT"
    cid = await confirm(env, buyer, clarified["pending_confirmation"]["proposal_id"])
    done = await resume(env, buyer, tid, clarified, cid)
    assert done.json()["status"] == "COMPLETED", done.text
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1


@pytest.mark.parametrize("architecture", ["single", "multi"])
async def test_support_ticket_does_not_swallow_independent_recommendation(
    durable_env, buyer, product, architecture
):
    env = durable_env
    old = await delivered_order(env[0], buyer, product)
    ticket = ai(
        call(
            "create_support_ticket",
            {"order_id": old["id"], "reason": "EXPLANATION", "summary": "合成规则咨询"},
        )
    )
    search = ai(call("retrieve_products", {"query": "静音键盘"}))
    models = make_models(
        supervisor=[
            route("aftersales", "human_support", "ticket", read_only=False),
            route("shopping", "find_products", "shop"),
            route("finish"),
        ],
        aftersales=[ticket],
        shopping=[search, final()],
    )
    await install(env, models)
    env[2].state.durable_single_model = SingleModel(role="order", script=[ticket, search, final()])
    tid = await thread(env, buyer, architecture)
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{old['id']}需要转人工解释政策。另推荐一款500元以内静音键盘，不购买",
        )
    ).json()
    assert run["status"] == "COMPLETED", run
    assert row(env[1], "SELECT count(*) n FROM support_tickets")["n"] == 1
    assert any(f["kind"] == "product" for f in run["result"]["facts"])
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1


@pytest.mark.parametrize("architecture", ["single", "multi"])
async def test_return_confirmation_then_purchase_clarification(
    durable_env, buyer, product, architecture
):
    from uuid import uuid4

    env = durable_env
    old = await delivered_order(env[0], buyer, product)
    inspect = ai(call("get_order", {"order_id": old["id"]}))
    prepare = ai(
        call(
            "prepare_return",
            {"order_id": old["id"], "reason_code": "QUALITY_ISSUE", "description": "合成故障"},
        )
    )
    search = ai(call("retrieve_products", {"query": "静音键盘"}))
    models = make_models(
        supervisor=[
            route("aftersales", "assess_return", "assessment"),
            route("aftersales", "prepare_return", "ret", depends=["assessment"], read_only=False),
            route("clarify"),
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", read_only=False),
            route("finish"),
        ],
        aftersales=[*assessment_reads(old["id"]), prepare],
        shopping=[search, final()],
        order=[choose_purchase],
    )
    await install(env, models)
    env[2].state.durable_single_model = SingleModel(
        role="order",
        script=[inspect, prepare, final('{"terminal":"clarify"}'), search, buy_retrieved, final()],
    )
    tid = await thread(env, buyer, architecture)
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{old['id']}有质量问题，申请退货；另准备购买静音键盘，稍后补数量地址",
        )
    ).json()
    pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, pid)
    clarified = (await resume(env, buyer, tid, run, cid)).json()
    assert clarified["status"] == "WAITING_INPUT", clarified
    assert clarified["pending_confirmation"]["type"] == "clarification"
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/resume",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "run_id": run["id"],
            "interrupt_id": clarified["pending_confirmation"]["interrupt_id"],
            "clarification": "预算500元以内，准备购买一款，送演示宿舍",
        },
    )
    next_run = response.json()
    assert response.status_code == 200, next_run
    assert next_run["pending_confirmation"]["action_type"] == "CHECKOUT"
    assert next_run["pending_confirmation"]["proposal_id"] != pid
    assert (await resume(env, buyer, tid, next_run, cid)).status_code == 409
    next_cid = await confirm(env, buyer, next_run["pending_confirmation"]["proposal_id"])
    done = (await resume(env, buyer, tid, next_run, next_cid)).json()
    assert done["status"] == "COMPLETED", json.dumps(done, ensure_ascii=False)
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
