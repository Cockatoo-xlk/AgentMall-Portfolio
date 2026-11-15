"""CONTRACT_TEST_ONLY: synthetic decisions exercise the real handoff and database fences."""

import copy

from conftest import row
from langchain_core.messages import ToolMessage
from lifecycle_helpers import create_order
from multiagent_helpers import ai, call, final, install, make_models, payload, route, send
from t09_helpers import durable_env as durable_env
from t09_helpers import start, thread


def duplicate_read_batch(messages):
    first = route("order", "inspect_orders", "contract_first")(messages).tool_calls[0]["args"][
        "tasks"
    ][0]
    second = copy.deepcopy(first)
    second["subtask_id"] = "contract_duplicate"
    return ai(call("route", {"tasks": [first, second]}))


async def test_equivalent_read_tasks_in_one_batch_are_rejected_before_any_delegation(env, buyer):
    models = make_models(supervisor=[duplicate_read_batch, route("finish")])
    trace = await install(env, models, indexed=False)
    result = await send(env, buyer, message="查看本人的订单")
    assert result["budget"]["used"]["delegations"] == 0
    assert result["error_codes"] == ["REPEATED_DELEGATION"]
    assert not models["order"].seen
    assert not any(e["kind"] in {"handoff", "tool"} for e in trace["events"])
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0


async def test_durable_equivalent_read_batch_stops_without_spending_delegations(durable_env, buyer):
    env = durable_env
    models = make_models(supervisor=[duplicate_read_batch, route("finish")])
    await install(env, models, indexed=False)
    tid = await thread(env, buyer)
    response = await start(env, buyer, tid, message="查看本人的订单")
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["budget"]["delegations"] == 0
    assert run["status"] == "PARTIAL"
    assert run["result"]["error_codes"] == ["REPEATED_DELEGATION"]
    assert not models["order"].seen
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 0


async def test_same_read_goal_for_distinct_order_references_is_still_allowed(env, buyer, product):
    orders = [await create_order(env[0], buyer, product) for _ in range(2)]

    def distinct_reads(messages):
        tasks = []
        for index, order in enumerate(orders):
            task = route("order", "inspect_orders", f"contract_order_{index}")(messages).tool_calls[
                0
            ]["args"]["tasks"][0]
            task["entity_refs"] = [r for r in task["entity_refs"] if r["id"] == order["id"]]
            tasks.append(task)
        return ai(call("route", {"tasks": tasks}))

    def read_order(messages):
        if any(isinstance(message, ToolMessage) for message in messages):
            return final()
        order_ref = payload(messages)["entity_refs"][0]
        return ai(call("get_order", {"order_id": order_ref["id"]}))

    models = make_models(
        supervisor=[distinct_reads, route("finish")],
        order=[read_order] * 4,
    )
    await install(env, models, indexed=False)
    result = await send(
        env, buyer, message=f"查看本人订单{orders[0]['id']}和{orders[1]['id']}的状态"
    )
    assert result["status"] == "done", result
    assert result["error_codes"] == []
    assert result["budget"]["used"]["delegations"] == 2
    assert result["budget"]["used"]["tools"] == 2
    assert len(result["results"]) == 2
    assert all(r["status"] == "done" for r in result["results"])
    assert {r["id"] for r in result["entity_refs"] if r["kind"] == "order"} == {
        order["id"] for order in orders
    }
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 2
