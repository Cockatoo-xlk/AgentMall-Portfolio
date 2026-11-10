from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import ai, call, final, install, make_models, route
from t09_helpers import durable_env as durable_env
from t09_helpers import start, thread


async def test_failed_goal_cannot_be_redelegated_with_new_id_or_new_evidence(
    durable_env, buyer, product
):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "assess_return", "first"),
            route("aftersales", "assess_return", "renamed"),
            route("finish"),
        ],
        aftersales=[
            ai(call("get_order", {"order_id": order["id"]})),
            ai(
                call(
                    "check_eligibility", {"order_id": order["id"], "reason_code": "QUALITY_ISSUE"}
                ),
                call("retrieve_policies", {"order_id": order["id"], "query": "退货政策"}),
                call("execute_confirmed_action", {}),
            ),
            final(),
        ],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    result = (
        await start(env, buyer, tid, message=f"订单{order['id']}质量问题，检查售后资格。")
    ).json()
    assert result["status"] == "PARTIAL"
    assert "REPEATED_DELEGATION" in result["result"]["error_codes"]
    assert result["budget"]["delegations"] == 1
    assert len(models["aftersales"].seen) == 2
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert (
        row(env[1], "SELECT count(*) n FROM action_proposals WHERE action_type='RETURN_REQUEST'")[
            "n"
        ]
        == 0
    )


async def test_failed_goal_marker_survives_discovery_of_original_exclusions(
    durable_env, buyer, product
):
    from multiagent_helpers import payload

    env = durable_env
    await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("order", "inspect_orders", "discover"),
            route("order", "inspect_orders", "discover_again"),
            route("finish"),
        ],
        order=[ai(call("list_orders")), ai(call("confirm_proposal", {})), final()],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    result = (
        await start(
            env,
            buyer,
            tid,
            message="这笔订单有质量问题，申请退货，再推荐另一款500元以内的静音键盘。",
        )
    ).json()
    assert result["status"] == "PARTIAL"
    assert not payload(models["supervisor"].seen[0])["canonical_constraints"]["exclude_product_ids"]
    assert (
        product
        in payload(models["supervisor"].seen[1])["canonical_constraints"]["exclude_product_ids"]
    )
    assert result["budget"]["delegations"] == 1
    assert len(models["order"].seen) == 2
    assert "REPEATED_DELEGATION" in result["result"]["error_codes"]
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    rejected = row(
        env[1], "SELECT payload_summary FROM run_events WHERE event_type='delegation_rejected'"
    )["payload_summary"]
    assert rejected["delegation_executed"] is False


async def test_single_negative_purchase_intent_does_not_spend_a_model_repair(durable_env, buyer):
    from test_baseline_fairness import SingleModel

    env = durable_env
    await install(env, make_models())
    model = SingleModel(role="order", script=[ai(call("prepare_checkout", {})), final()])
    env[2].state.durable_single_model = model
    tid = await thread(env, buyer, "single")
    run = (await start(env, buyer, tid, message="推荐静音键盘，不要购买。")).json()
    assert run["status"] == "PARTIAL"
    assert run["budget"]["models"] == 1
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 0
