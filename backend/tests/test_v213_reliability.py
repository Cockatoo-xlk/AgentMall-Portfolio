"""RECONSTRUCTED_FIXTURE: never presented as the missing historical Provider trace."""

from uuid import uuid4

from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import (
    ai,
    assessment_reads,
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


def verified_flow(order_id):
    def plan(messages):
        completed = {r["subtask_id"] for r in payload(messages)["completed"]}
        if "assessment" not in completed:
            return route("aftersales", "assess_return", "assessment")(messages)
        if "return" not in completed:
            return route(
                "aftersales", "prepare_return", "return", depends=["assessment"], read_only=False
            )(messages)
        if "shop" not in completed:
            return route("shopping", "find_products", "shop", depends=["return"])(messages)
        if "buy" not in completed:
            return route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False)(
                messages
            )
        return route("finish")(messages)

    def repair(messages):
        value = payload(messages)
        assert value["orchestration_feedback"]["error_code"] == "INCOMPLETE_WRITE_GOAL"
        assert value["prior_tool_results"] == []
        assert value["verified_assessments"][0]["ready"]
        return ai(
            call(
                "prepare_return",
                {
                    "order_id": order_id,
                    "reason_code": "QUALITY_ISSUE",
                    "description": "合成质量问题",
                },
            )
        )

    return make_models(
        supervisor=[plan] * 6,
        aftersales=[
            *assessment_reads(order_id),
            final("资格和政策已经核验。"),
            repair,
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )


async def test_read_facts_are_not_completion_of_write_goal_two_independent_decisions(
    durable_env, buyer
):
    env = durable_env
    product = row(env[1], "SELECT id FROM products WHERE category='keyboard' ORDER BY id LIMIT 1")[
        "id"
    ]
    order = await delivered_order(env[0], buyer, str(product))
    before = row(
        env[1],
        "SELECT (SELECT count(*) FROM orders) orders, "
        "(SELECT count(*) FROM payments) payments, "
        "(SELECT count(*) FROM confirmations) confirmations",
    )
    models = verified_flow(order["id"])
    await install(env, models)
    tid = await thread(env, buyer)
    goal = (
        f"订单{order['id']}有质量问题，申请退货，"
        "再推荐另一款500元以内静音键盘，准备购买一件，送演示宿舍"
    )
    first = (await start(env, buyer, tid, message=goal)).json()
    assert first["status"] == "WAITING_INPUT", first
    assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST", first
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == before["orders"]
    cid1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
    rid1 = str(uuid4())
    second = (await resume(env, buyer, tid, first, cid1, rid1)).json()
    assert second["status"] == "WAITING_INPUT", second
    assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
    assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == before["orders"]
    assert (await resume(env, buyer, tid, second, cid1)).status_code == 409
    cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
    rid2 = str(uuid4())
    done = (await resume(env, buyer, tid, second, cid2, rid2)).json()
    assert done["status"] == "COMPLETED", done
    assert done["budget"]["models"] == 12 and done["budget"]["tools"] == 6
    assert (
        len(models["aftersales"].seen) == 4
    )  # one local repair; no repeated supervisor/delegation
    assert (await resume(env, buyer, tid, second, cid2, rid2)).json() == done
    assert (await resume(env, buyer, tid, first, cid1, rid1)).json() == done
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == before["orders"] + 1
    assert row(env[1], "SELECT count(*) n FROM payments")["n"] == before["payments"]
    assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == before["confirmations"] + 2
    replacement = row(
        env[1],
        "SELECT oi.product_id,oi.quantity,oi.unit_price_cents,p.attributes,p.reserved "
        "FROM order_items oi JOIN orders o ON o.id=oi.order_id "
        "JOIN products p ON p.id=oi.product_id WHERE o.status='PENDING_PAYMENT'",
    )
    assert replacement["product_id"] != product
    assert replacement["quantity"] == replacement["reserved"] == 1
    assert replacement["unit_price_cents"] <= 50000
    assert replacement["attributes"]["noise"] == "较安静"
    for messages in models["supervisor"].seen:
        c = payload(messages)["canonical_constraints"]
        assert (
            c["max_price_cents"] == 50000
            and c["quantity"] == 1
            and c["address_label"] == "demo_dorm"
        )
        assert c["noise_preference"] == "quiet" and str(product) in c["exclude_product_ids"]


def test_ineligible_read_receipt_is_not_forced_into_a_write():
    from types import SimpleNamespace

    from agentmall.agents.specialists.runner import incomplete_write_goal

    runtime = SimpleNamespace(single=False, errors=[], constraints=SimpleNamespace(bundle=None))
    context = SimpleNamespace(
        envelope=SimpleNamespace(goal="prepare_return"),
        records=[
            {"name": "check_eligibility", "data": {"eligible": False, "requires_human": False}}
        ],
    )
    assert not incomplete_write_goal(runtime, context)


async def test_goal_repair_cannot_extend_existing_model_limit(durable_env, buyer, monkeypatch):
    from agentmall.agents import run_service
    from agentmall.agents.budgets import Limits
    from agentmall.agents.durable_budget import DurableBudget

    env = durable_env
    product = row(env[1], "SELECT id FROM products WHERE category='keyboard' ORDER BY id LIMIT 1")[
        "id"
    ]
    order = await delivered_order(env[0], buyer, str(product))
    models = verified_flow(order["id"])
    await install(env, models)
    monkeypatch.setattr(
        run_service, "DurableBudget", lambda fence: DurableBudget(fence, Limits(models=4))
    )
    tid = await thread(env, buyer)
    first = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{order['id']}有质量问题，申请退货，再推荐另一款500元以内静音键盘，准备购买一件，送演示宿舍",
        )
    ).json()
    assert first["status"] == "PARTIAL"
    assert first["budget"]["models"] == 4
    assert "BUDGET_EXCEEDED" in first["result"]["error_codes"]
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert (
        row(env[1], "SELECT count(*) n FROM action_proposals WHERE action_type='RETURN_REQUEST'")[
            "n"
        ]
        == 0
    )


async def test_completed_task_is_not_delegated_again(durable_env, buyer):
    env = durable_env
    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("shopping", "find_products", "shop"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    result = (await start(env, buyer, tid, message="推荐静音键盘，不要购买。")).json()
    assert result["status"] == "PARTIAL"
    assert "REPEATED_DELEGATION" in result["result"]["error_codes"]
    assert result["budget"]["delegations"] == 1
    assert len(models["shopping"].seen) == 2
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
