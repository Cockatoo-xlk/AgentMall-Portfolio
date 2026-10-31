"""Regression cases for the single T08 independent review."""

import pytest
from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import ai, call, final, install, make_models, payload, route, send


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("prepare_return", {"reason_code": "QUALITY_ISSUE", "description": "按键故障"}),
        ("create_support_ticket", {"reason": "POLICY_DISPUTE", "summary": "人工核对"}),
    ],
)
async def test_aftersales_write_cannot_switch_to_another_owned_order(
    env, buyer, product, tool, arguments
):
    first = await delivered_order(env[0], buyer, product)
    second = await delivered_order(env[0], buyer, product)
    args = {**arguments, "order_id": second["id"]}
    models = make_models(
        supervisor=[
            route("aftersales", "prepare_return", "return", read_only=False),
            route("finish"),
        ],
        aftersales=[ai(call(tool, args))],
    )
    await install(env, models)
    result = await send(env, buyer, message=f"订单 {first['id']} 质量问题想退掉并联系人工")
    assert "ORDER_SCOPE_MISMATCH" in result["error_codes"]
    assert (
        row(env[1], "SELECT count(*) n FROM action_proposals WHERE proposal_slot='t08_return'")["n"]
        == 0
    )
    assert row(env[1], "SELECT count(*) n FROM support_tickets")["n"] == 0


@pytest.mark.parametrize("user_text", ["只查退货政策", "只查退货政策，不要转人工"])
async def test_unknown_reason_cannot_manufacture_human_handoff(env, buyer, product, user_text):
    order = await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "human_support", "human", read_only=False),
            route("finish"),
        ],
        aftersales=[
            ai(
                call(
                    "create_support_ticket",
                    {
                        "order_id": order["id"],
                        "reason": "POLICY_DISPUTE",
                        "summary": "模型决定转人工",
                    },
                )
            )
        ],
    )
    await install(env, models)
    result = await send(env, buyer, message=f"订单 {order['id']} {user_text}")
    assert "HUMAN_HANDOFF_NOT_NEEDED" in result["error_codes"]
    assert row(env[1], "SELECT count(*) n FROM support_tickets")["n"] == 0


@pytest.mark.parametrize("layout,connection", [("87键", "双模"), ("68键", "有线")])
async def test_structured_product_attributes_reach_specialist_and_filter_results(
    env, buyer, layout, connection
):
    def search(messages):
        needs = payload(messages)["constraints"]["product_needs"]
        assert needs == {
            "layout": layout,
            "connection": connection,
            "keyboard_type": "mechanical",
            "usage": "宿舍",
        }
        assert "private-sentinel" not in str(messages)
        # Even if the model uses a generic query, runtime preserves the explicit constraints.
        return ai(call("retrieve_products", {"query": "静音键盘"}))

    models = make_models(
        supervisor=[route("shopping", "find_products"), route("finish")], shopping=[search, final()]
    )
    await install(env, models)
    result = await send(
        env,
        buyer,
        message=f"300元以内的 {layout} {connection} 静音机械键盘，适合宿舍。密码 private-sentinel",
    )
    assert result["error_codes"] == [], result
    products = [f["data"] for f in result["facts"] if f["kind"] == "product"]
    assert products
    assert all(
        p["attributes"]["size"] == layout and p["attributes"]["connection"] == connection
        for p in products
    )


@pytest.mark.parametrize("parallel", [False, True])
async def test_replacement_cannot_run_before_original_is_resolved(env, buyer, product, parallel):
    await delivered_order(env[0], buyer, product)

    def unsafe_route(messages):
        tasks = route("shopping", "find_products", "search")(messages).tool_calls[0]["args"][
            "tasks"
        ]
        if parallel:
            tasks += route("order", "inspect_orders", "old")(messages).tool_calls[0]["args"][
                "tasks"
            ]
        return ai(call("route", {"tasks": tasks}))

    models = make_models(
        supervisor=[unsafe_route, route("finish")],
        shopping=[ai(call("retrieve_products", {"query": "键盘"})), final()],
        order=[ai(call("list_orders")), final()],
    )
    await install(env, models)
    result = await send(
        env, buyer, message="之前买的键盘质量问题想退掉，再帮我推荐一款500元以内静音键盘"
    )
    assert "REPLACEMENT_SOURCE_REQUIRED" in result["error_codes"]
    assert not models["shopping"].seen
    assert not any(f["kind"] == "product" for f in result["facts"])


async def test_multiple_owned_orders_require_selection_for_return(env, buyer, product):
    first = await delivered_order(env[0], buyer, product)
    await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("order", "inspect_orders", "old"),
            route("aftersales", "prepare_return", "return", read_only=False),
            route("finish"),
        ],
        order=[ai(call("list_orders")), final()],
        aftersales=[
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": first["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "故障",
                    },
                )
            )
        ],
    )
    await install(env, models)
    result = await send(env, buyer, message="之前键盘质量问题想退掉")
    assert "ORDER_SELECTION_REQUIRED" in result["error_codes"]
    assert (
        row(env[1], "SELECT count(*) n FROM action_proposals WHERE proposal_slot='t08_return'")["n"]
        == 0
    )


async def test_mixed_order_and_product_ids_are_classified_independently(env, buyer, product):
    order = await delivered_order(env[0], buyer, product)
    replacement = str(
        row(
            env[1],
            "SELECT id FROM products WHERE active AND id!=:id ORDER BY id LIMIT 1",
            id=product,
        )["id"]
    )

    def lookup(messages):
        refs = payload(messages)["entity_refs"]
        assert any(r["id"] == replacement and r["kind"] == "product" for r in refs)
        assert all(r["kind"] == "product" for r in refs)
        return ai(call("get_product", {"product_id": replacement}))

    models = make_models(
        supervisor=[route("shopping", "find_products"), route("finish")], shopping=[lookup, final()]
    )
    await install(env, models)
    result = await send(
        env, buyer, message=f"比较替代商品 {replacement}，原订单 {order['id']}，原商品 {product}"
    )
    assert result["error_codes"] == [], result
    assert not any(f["kind"] == "product" and f["id"] == product for f in result["facts"])


@pytest.mark.parametrize("declined", [False, True])
async def test_human_rule_requires_known_reason_and_respects_explicit_refusal(
    env, buyer, product, declined
):
    order = await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "human_support", "human", read_only=False),
            route("finish"),
        ],
        aftersales=[
            ai(
                call(
                    "create_support_ticket",
                    {"order_id": order["id"], "reason": "QUALITY_DISPUTE", "summary": "质量争议"},
                )
            )
        ],
    )
    await install(env, models)
    result = await send(
        env,
        buyer,
        message=f"处理订单 {order['id']} 的质量争议" + ("，不要转人工" if declined else ""),
        constraints={"reason_code": "QUALITY_DISPUTE"},
    )
    assert row(env[1], "SELECT count(*) n FROM support_tickets")["n"] == (0 if declined else 1)
    if declined:
        assert "HUMAN_HANDOFF_NOT_NEEDED" in result["error_codes"]
