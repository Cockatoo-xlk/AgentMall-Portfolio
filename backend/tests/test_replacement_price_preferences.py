"""Replacement prices and atomic Thread preferences, using the standard product seed."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import row
from multiagent_helpers import install, make_models, route
from t09_helpers import durable_env as durable_env
from t09_helpers import thread
from test_price_contract import parse
from test_thread_memory import read, turn

from agentmall.agents.context import Constraints
from agentmall.agents.specialist_tools import product_allowed
from agentmall.catalog.schemas import ProductDTO


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
@pytest.mark.parametrize(
    "original",
    [
        "订单123里{quote}的静音K87键盘按键失灵，请申请质量退货。",
        "请退掉{quote}的旧键盘，",
        "请为{quote}的旧键盘申请质量退货。",
        "旧键盘{quote}，按键失灵，请申请质量退货。",
    ],
)
@pytest.mark.parametrize("unit", [None, 19900, 20900])
async def test_replacement_price_only_constrains_new_item(env, buyer, threaded, original, unit):
    target = "再帮我买一件有线静音键盘，送演示宿舍，总预算250元"
    if unit is not None:
        target += f"，新键盘每件{unit // 100}元"
    quoted = parse(original.format(quote="299元") + target, threaded=threaded)
    without = parse(original.replace("{quote}的", "").format(quote="") + target, threaded=threaded)
    assert quoted["product_needs"] == without["product_needs"]
    assert quoted["max_price_cents"] == without["max_price_cents"] == 25000
    assert quoted["product_needs"].get("unit_price_cents") == unit
    runtime = SimpleNamespace(constraints=Constraints.model_validate(quoted), exclusions=set())
    for name, price, expected in (
        ("宿舍静音 K68", 19900, unit in {None, 19900}),
        ("静音 K104", 49900, False),
    ):
        fact = row(env[1], "SELECT id, price_cents FROM products WHERE name=:name", name=name)
        assert fact["price_cents"] == price
        response = await env[0].get(f"/api/v1/products/{fact['id']}", headers=buyer)
        assert response.status_code == 200, response.text
        assert product_allowed(runtime, ProductDTO.model_validate(response.json())) is expected


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_price_on_return_object_does_not_become_replacement_price(threaded):
    quoted = parse("退 299 元 K87，再买总预算 250 元的键盘", threaded=threaded)
    plain = parse("退 K87，再买总预算 250 元的键盘", threaded=threaded)
    assert quoted == plain
    assert quoted["max_price_cents"] == 25000
    assert quoted["product_needs"].get("unit_price_cents") is None


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_unpunctuated_purchase_transition_preserves_current_budget(threaded):
    message = "请退掉299元的旧键盘然后再帮我买一件静音键盘，本次预算250元"
    constraints = parse(message, threaded=threaded)
    assert constraints["max_price_cents"] == 25000
    assert constraints["product_needs"].get("unit_price_cents") is None


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_current_budget_in_return_sentence_is_retained(threaded):
    message = "原订单里299元的键盘坏了但本次总预算200元，请申请质量退货；另外帮我买一件键盘"
    constraints = parse(message, threaded=threaded)
    assert constraints["max_price_cents"] == 20000
    assert constraints["product_needs"].get("unit_price_cents") is None


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_original_item_price_qualifier_ends_at_replacement_goal(threaded):
    message = (
        "原订单里的旧键盘刚满一个月，单价299元，请申请质量退货。"
        "再帮我买一件K68，新商品每件199元，总预算250元"
    )
    result = parse(message, threaded=threaded)
    assert result["max_price_cents"] == 25000
    assert result["product_needs"].get("unit_price_cents") == 19900


def price_op(field, value, op="SET"):
    return {"op": op, "field": field, "value": value}


@pytest.mark.parametrize("prior", [False, True], ids=["single-patch", "lower-saved-limit"])
async def test_inconsistent_merged_unit_prices_leave_no_context_write(durable_env, buyer, prior):
    env = durable_env
    tid = await thread(env, buyer)
    url = f"/api/v1/agent/threads/{tid}/context"

    async def patch(version, operations):
        return await env[0].patch(
            url,
            headers=buyer,
            json={
                "request_id": str(uuid4()),
                "expected_version": version,
                "operations": operations,
            },
        )

    exact = price_op("unit_price_cents", 19900)
    cap = price_op("max_unit_price_cents", 22000)
    if prior:
        saved = await patch(0, [exact, cap])
        assert saved.status_code == 200, saved.text
    before = (await read(env, buyer, tid))["context"]

    def persisted():
        return row(
            env[1],
            "SELECT c.version,c.preferences,(SELECT count(*) FROM agent_context_mutations "
            "WHERE thread_id=:tid) AS receipts FROM agent_threads t "
            "LEFT JOIN agent_thread_contexts c ON t.id=c.thread_id WHERE t.id=:tid",
            tid=tid,
        )

    original = persisted()
    lower = price_op("max_unit_price_cents", 18900, "REPLACE" if prior else "SET")
    rejected = await patch(before["version"], [lower] if prior else [exact, lower])
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
    assert persisted() == original
    assert (await read(env, buyer, tid))["context"] == before
    if not prior:
        saved = await patch(0, [exact, cap])
        assert saved.status_code == 200, saved.text

    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    result = await turn(env, buyer, tid, "看看键盘", 1)
    assert result.status_code == 201, result.text
    snapshot = row(
        env[1], "SELECT context_snapshot FROM agent_runs WHERE id=:rid", rid=result.json()["id"]
    )["context_snapshot"]
    assert snapshot["constraints"]["product_needs"]["unit_price_cents"] == 19900
    assert snapshot["constraints"]["product_needs"]["max_unit_price_cents"] == 22000
