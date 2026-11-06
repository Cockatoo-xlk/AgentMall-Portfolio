"""Intent routing through the real durable graph, SDK fixtures and PostgreSQL."""

from uuid import uuid4

import pytest
from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import ai, call, final, install, make_models, route
from playground_helpers import install_sdk
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env


def business(db):
    return row(
        db,
        "SELECT (SELECT count(*) FROM orders) orders, "
        "(SELECT count(*) FROM aftersales_cases) cases, "
        "(SELECT count(*) FROM confirmations) confirmations, "
        "(SELECT count(*) FROM refunds) refunds, "
        "(SELECT count(*) FROM action_proposals WHERE action_type='CHECKOUT') checkouts",
    )


@pytest.mark.parametrize("suffix", ["", "，不要下单"])
async def test_sdk_return_and_recommendation_need_only_return_confirmation(
    durable_env, buyer, product, tmp_path, suffix
):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    before = dict(business(env[1]))
    provider, wire = await install_sdk(env, tmp_path, "return_replace", order["id"])
    try:
        tid = await thread(env, buyer)
        run = (
            await start(
                env,
                buyer,
                tid,
                message="这笔订单有质量问题，申请退货，再推荐一款500元以内的静音键盘" + suffix,
            )
        ).json()
        assert run.get("status") == "WAITING_INPUT", run
        pending = run["pending_confirmation"]
        assert pending["action_type"] == "RETURN_REQUEST"
        assert business(env[1]) == before
        cid = await confirm(env, buyer, pending["proposal_id"])
        rid = str(uuid4())
        response = await resume(env, buyer, tid, run, cid, rid)
        final_run = response.json()
        assert response.status_code == 200 and final_run.get("status") == "COMPLETED", final_run
        assert final_run["result"]["error_codes"] == []
        assert final_run["pending_confirmation"] is None
        assert "order" not in wire.counts
        assert any(
            fact["kind"] == "product"
            and fact["id"] != str(product)
            and fact["data"]["price_cents"] <= 50000
            for fact in final_run["result"]["facts"]
        )
        calls = len(wire.requests)
        replay = await resume(env, buyer, tid, run, cid, rid)
        assert replay.status_code == 200 and len(wire.requests) == calls
        assert business(env[1]) == before | {
            "cases": before["cases"] + 1,
            "confirmations": before["confirmations"] + 1,
        }
        assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "message",
    [
        "推荐一款500元以内的静音键盘，不要购买。",
        "帮我找替代品，但不要下单。原订单是{order_id}。",
    ],
)
async def test_sdk_read_only_recommendations(durable_env, buyer, product, tmp_path, message):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    before = dict(business(env[1]))
    provider, wire = await install_sdk(env, tmp_path, "recommend")
    try:
        tid = await thread(env, buyer)
        run = (await start(env, buyer, tid, message=message.format(order_id=order["id"]))).json()
        assert run.get("status") == "COMPLETED", run
        assert "shopping" in wire.counts and "order" not in wire.counts
        assert any(f["kind"] == "product" for f in run["result"]["facts"])
        assert business(env[1]) == before
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "question", ["查询订单{id}的质量问题退货政策", "查询订单{id}是否可以申请退货"]
)
async def test_sdk_policy_lookup_and_foreign_order(
    durable_env, buyer, buyer2, product, tmp_path, question
):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    before = dict(business(env[1]))
    provider, wire = await install_sdk(env, tmp_path, "return_policy", order["id"])
    try:
        tid = await thread(env, buyer2)
        denied = (
            await start(env, buyer2, tid, message=f"查询订单{order['id']}的公开退货政策")
        ).json()
        assert denied["status"] == "PARTIAL", denied
        assert denied["result"]["error_codes"] == ["NOT_FOUND"]
        assert not wire.requests
        assert not denied["result"]["entity_refs"]
        tid = await thread(env, buyer)
        run = (await start(env, buyer, tid, message=question.format(id=order["id"]))).json()
        assert run.get("status") == "COMPLETED", run
        assert any(f["kind"] == "eligibility" for f in run["result"]["facts"])
        assert run["result"]["citations"]
        assert not run["constraints"]["return_requested"]
        assert not run["result"]["proposal_ids"]
        assert business(env[1]) == before
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "message,supervisor",
    [
        (
            "推荐静音键盘，不要下单",
            [
                route("shopping", "find_products", "shop"),
                route("order", "prepare_checkout", "unexpected", read_only=False),
                route("finish"),
            ],
        ),
        (
            "帮我找静音键盘准备购买，送演示宿舍",
            [
                route("shopping", "find_products", "shop"),
                route("order", "prepare_checkout", "missing", read_only=False),
            ],
        ),
        (
            "我想买一个键盘，送演示宿舍",
            [route("order", "prepare_checkout", "no_candidate", read_only=False)],
        ),
        (
            "推荐一款静音键盘，然后我要买两件，送演示宿舍",
            [
                route("shopping", "find_products", "shop"),
                route("order", "prepare_checkout", "ambiguous_qty", read_only=False),
            ],
        ),
        (
            "我要买一件静音键盘，送演示宿舍还是演示家庭",
            [
                route("shopping", "find_products", "shop"),
                route("order", "prepare_checkout", "ambiguous_address", read_only=False),
            ],
        ),
        (
            "请推荐一款静音键盘",
            [route("finish")],
        ),
    ],
)
async def test_checkout_handoff_and_finish_use_trusted_intent(
    durable_env, buyer, message, supervisor
):
    env = durable_env
    models = make_models(
        supervisor=supervisor,
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message=message)).json()
    if "不要" in message:
        assert run.get("status") == "COMPLETED", run
        assert run["result"]["error_codes"] == []
    else:
        assert run.get("status") == "WAITING_INPUT", run
        assert run["pending_confirmation"]["type"] == "clarification"
    assert not models["order"].seen
    assert business(env[1]) == dict(orders=0, cases=0, confirmations=0, refunds=0, checkouts=0)


async def test_model_cannot_make_read_only_order_goal_writable(durable_env, buyer):
    env = durable_env
    models = make_models(
        supervisor=[
            route("order", "inspect_orders", "smuggled", read_only=False),
            route("clarify"),
        ],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message="帮我准备购买键盘，一件，送演示宿舍")).json()
    assert run.get("status") == "WAITING_INPUT", run
    assert run["pending_confirmation"]["type"] == "clarification"
    assert not models["order"].seen
    assert business(env[1]) == dict(orders=0, cases=0, confirmations=0, refunds=0, checkouts=0)


async def test_return_decision_precedes_replacement_purchase(durable_env, buyer, product):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    replacement = row(
        env[1], "SELECT id FROM products WHERE active AND id != :id ORDER BY id LIMIT 1", id=product
    )["id"]
    before = business(env[1])
    models = make_models(
        supervisor=[
            route("order", "prepare_checkout", "too_early", read_only=False),
            route("aftersales", "prepare_return", "return", read_only=False),
        ],
        aftersales=[
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": order["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "故障",
                    },
                )
            )
        ],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{order['id']}有质量问题，申请退货；再购买{replacement}作为替代品，一件，送演示宿舍",
        )
    ).json()
    assert run.get("status") == "WAITING_INPUT", run
    assert run["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
    assert not models["order"].seen
    assert business(env[1]) == before


async def test_order_hydration_does_not_complete_policy_goal(durable_env, buyer, product):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    before = business(env[1])
    await install(env, make_models(supervisor=[route("finish")]))
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message=f"查询订单{order['id']}的售后政策")).json()
    assert run.get("status") == "WAITING_INPUT", run
    assert run["pending_confirmation"]["type"] == "clarification"
    assert business(env[1]) == before


async def test_model_cannot_swap_explicit_purchase_sku(durable_env, buyer):
    env = durable_env
    with env[1].connect() as connection:
        from sqlalchemy import text

        selected, other = connection.scalars(
            text("SELECT id FROM products WHERE name IN ('静音 K87', '宿舍静音 K68') ORDER BY id")
        ).all()
    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", read_only=False),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[ai(call("prepare_checkout", {"product_id": str(other)})), final()],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message=f"我要买{selected}，一件，送演示宿舍")).json()
    assert run["status"] == "PARTIAL", run
    assert "SELECTION_MISMATCH" in run["result"]["error_codes"]
    assert business(env[1]) == dict(orders=0, cases=0, confirmations=0, refunds=0, checkouts=0)


async def test_return_receipt_survives_real_shopping_failure(durable_env, buyer, product):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    before = dict(business(env[1]))
    models = make_models(
        supervisor=[
            route("aftersales", "prepare_return", "return", read_only=False),
            route("shopping", "find_products", "replacement"),
            route("finish"),
        ],
        aftersales=[
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": order["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "故障",
                    },
                )
            )
        ],
        shopping=[RuntimeError("synthetic shopping failure")],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{order['id']}有质量问题，申请退货，再推荐500元以内的静音键盘",
        )
    ).json()
    assert run.get("status") == "WAITING_INPUT", run
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    rid = str(uuid4())
    response = await resume(env, buyer, tid, run, cid, rid)
    done = response.json()
    assert done["status"] == "PARTIAL", done
    assert done["result"]["error_codes"] == ["SPECIALIST_FAILED"]
    assert (await resume(env, buyer, tid, run, cid, rid)).status_code == 200
    assert business(env[1]) == before | {
        "cases": before["cases"] + 1,
        "confirmations": before["confirmations"] + 1,
    }
    assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
