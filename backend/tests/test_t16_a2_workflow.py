"""Default seeded catalogue + real SDK wire protocol, PG, graph and checkpointer."""

from uuid import UUID, uuid4

import pytest
from conftest import row
from multiturn_helpers import install_context_sdk
from t09_helpers import confirm, resume, thread
from t09_helpers import durable_env as durable_env
from test_thread_memory import read, turn


async def test_rejected_candidate_does_not_become_purchase_selection(durable_env, buyer, tmp_path):
    from multiturn_helpers import wireless_products

    env = durable_env
    await wireless_products(env)
    provider, _ = await install_context_sdk(env, tmp_path)
    try:
        tid = await thread(env, buyer)
        await turn(env, buyer, tid, "推荐400元以内无线静音键盘", 0)
        ctx = (await read(env, buyer, tid))["context"]
        candidates = ctx["candidate_sets"][0]
        target = candidates["items"][2]["id"]
        result = await turn(
            env,
            buyer,
            tid,
            "不买第二款，改买第三款，一件，送演示宿舍。",
            ctx["version"],
            candidate_set_id=candidates["id"],
        )
        assert result.status_code == 201, result.text
        assert result.json()["status"] == "WAITING_INPUT", result.text
        assert [x["id"] for x in result.json()["context_snapshot"]["selected"]] == [target]
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
    finally:
        await provider.close()


@pytest.mark.parametrize("mode", ["single", "multi"])
async def test_default_catalogue_three_turns(durable_env, buyer, tmp_path, mode):
    env = durable_env
    provider, _ = await install_context_sdk(env, tmp_path)
    try:
        tid = await thread(env, buyer, mode)
        first = await turn(env, buyer, tid, "推荐300元以内的静音键盘，不要购买。", 0)
        assert first.status_code == 201, first.text
        assert first.json()["constraints"]["purchase_requested"] is False
        ctx = (await read(env, buyer, tid))["context"]
        second = await turn(
            env, buyer, tid, "改成支持无线连接的，预算提高到400元。", ctx["version"]
        )
        assert second.status_code == 201, second.text
        ctx = (await read(env, buyer, tid))["context"]
        assert ctx["preferences"]["max_price_cents"] == 40000
        assert ctx["preferences"]["noise_preference"] == "quiet"
        candidates = ctx["candidate_sets"][0]
        assert len(candidates["items"]) >= 2
        assert {x["name"] for x in candidates["items"]} <= {"静音 K87", "静音 K98", "办公 K108"}
        target = candidates["items"][1]["id"]
        body = dict(candidate_set_id=candidates["id"], request_id=str(uuid4()))
        message = "就买最新推荐的第二款，一件，送演示宿舍。"
        third = await turn(env, buyer, tid, message, ctx["version"], **body)
        assert third.status_code == 201, third.text
        run = third.json()
        assert run["status"] == "WAITING_INPUT", run
        assert run["context_snapshot"]["selected"][0]["id"] == target
        replay = await turn(env, buyer, tid, message, ctx["version"], **body)
        assert replay.status_code == 200 and replay.json()["id"] == run["id"]
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
        pid = run["pending_confirmation"]["proposal_id"]
        proposal = (await env[0].get(f"/api/v1/proposals/{pid}", headers=buyer)).json()
        assert proposal["canonical_payload"]["items"][0]["product_id"] == target
        cid = await confirm(env, buyer, pid)
        key = str(uuid4())
        done = await resume(env, buyer, tid, run, cid, key)
        assert done.status_code == 200 and done.json()["status"] == "COMPLETED", done.text
        assert (await resume(env, buyer, tid, run, cid, key)).status_code == 200
        assert row(env[1], "SELECT count(*) n FROM orders WHERE status='PENDING_PAYMENT'")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 3
        from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

        async with checkpoint_saver(env[3]) as saver:
            snapshot = await saver.aget_tuple(checkpoint_config(UUID(tid), UUID(run["id"])))
            assert snapshot is not None
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "message",
    [
        "我不想买第二款。",
        "我不需要买第二款。",
        "不要买第二款，只想看看。",
        "先别下单。",
        "我取消购买，继续比较商品。",
        "不要再买第二款，一件，送演示宿舍。",
        "我不打算买第二款，一件，送演示宿舍。",
        "不用帮我买第二款，一件，送演示宿舍。",
    ],
)
async def test_negation_blocks_tool_even_with_typed_or_handoff_assertion(
    durable_env, buyer, message
):
    from retrieval_helpers import actor

    from agentmall.agents.budgets import GraphBudget
    from agentmall.agents.context import Constraints, HandoffEnvelope, MultiRequest
    from agentmall.agents.memory import resolve_preferences
    from agentmall.agents.run_schemas import RunCreate
    from agentmall.agents.runtime import RunContext
    from agentmall.agents.specialist_tools import SpecialistTools

    env = durable_env
    pid = row(env[1], "SELECT id FROM products WHERE name='静音 K87'")["id"]
    _, canonical = resolve_preferences(
        {},
        RunCreate(
            request_id=uuid4(),
            message=message,
            expected_context_version=0,
            constraints={"purchase_requested": True, "quantity": 1, "address_label": "demo_dorm"},
        ),
    )
    runtime = RunContext(
        actor(env[3]),
        env[3],
        env[2].state.sessions,
        MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message),
        {},
        None,
        GraphBudget(),
        {},
        thread_snapshot={"constraints": canonical, "selected": []},
    )
    forged = Constraints(purchase_requested=True, quantity=1, address_label="demo_dorm")
    envelope = HandoffEnvelope(
        subtask_id="attack",
        target="order",
        goal="prepare_checkout",
        constraints=forged,
        remaining_budget=runtime.budget.snapshot(),
        read_only=False,
    )
    tools = SpecialistTools(runtime, envelope)
    assert (await tools.execute("get_product", {"product_id": str(pid)}))["ok"]
    result = await tools.execute("prepare_checkout", {"product_id": str(pid)})
    assert result.get("error_code") == "PURCHASE_DETAILS_REQUIRED", result
    for table in ["action_proposals", "orders", "confirmations", "payments"]:
        assert row(env[1], f"SELECT count(*) n FROM {table}")["n"] == 0


async def test_uuid_alternatives_do_not_mutate_context_or_business(durable_env, buyer):
    env = durable_env
    tid = await thread(env, buyer)
    first = row(env[1], "SELECT id FROM products WHERE name='静音 K87'")["id"]
    second = row(env[1], "SELECT id FROM products WHERE name='静音 K98'")["id"]
    result = await turn(env, buyer, tid, f"我要买{first}或{second}，一件，送演示宿舍。", 0)
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
    assert (await read(env, buyer, tid))["context"]["version"] == 0
    for table in ["agent_runs", "action_proposals", "orders", "confirmations", "payments"]:
        assert row(env[1], f"SELECT count(*) n FROM {table}")["n"] == 0
