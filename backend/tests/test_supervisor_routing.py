import pytest
from multiagent_helpers import ai, call, final, install, make_models, route, send


@pytest.mark.parametrize(
    "role,goal,tool,message",
    [
        ("shopping", "find_products", "retrieve_products", "只搜索静音键盘"),
        ("order", "inspect_orders", "list_orders", "查看我的订单"),
        ("aftersales", "assess_return", None, "查询售后政策"),
    ],
)
async def test_model_selected_route_only_invokes_requested_specialist(
    env, buyer, role, goal, tool, message
):
    scripts = {
        role: (
            [ai(call(tool, {"query": "静音键盘"} if role == "shopping" else {})), final()]
            if tool
            else [final("需要订单ID")]
        )
    }
    models = make_models(supervisor=[route(role, goal, "selected"), route("finish")], **scripts)
    trace = await install(env, models)
    result = await send(env, buyer, message=message)
    assert len(models[role].seen) > 0
    assert all(not models[other].seen for other in {"shopping", "order", "aftersales"} - {role})
    assert [e["payload"]["target"] for e in trace["events"] if e["kind"] == "handoff"] == [role]
    assert result["execution_mode"] == "FIXTURE"


async def test_unknown_route_one_bounded_schema_repair_no_tools(env, buyer):
    invalid = route("not_a_real_agent", "find_products")
    models = make_models(supervisor=[invalid, invalid])
    trace = await install(env, models)
    result = await send(env, buyer)
    assert result["error_codes"] == ["INVALID_ROUTE"]
    assert result["budget"]["used"]["models"] == 2
    assert result["budget"]["used"]["delegations"] == 0
    assert not any(e["kind"] == "tool" for e in trace["events"])


@pytest.mark.parametrize(
    "change,error",
    [
        (
            lambda task: task["constraints"].update(max_price_cents=90000),
            "HANDOFF_CONSTRAINT_CHANGED",
        ),
        (lambda task: task.update(depends_on=["future"]), "DEPENDENCY_NOT_READY"),
        (
            lambda task: task.update(evidence_refs=["00000000-0000-0000-0000-000000000999"]),
            "CONTEXT_SCOPE_VIOLATION",
        ),
    ],
)
async def test_invalid_handoff_cannot_execute_specialist(env, buyer, change, error):
    invalid = route("shopping", "find_products", "bad", change=change)
    # Constraint copying gets one bounded correction; reject the second bad
    # decision too, instead of accidentally testing an exhausted model fixture.
    attempts = 2 if error == "HANDOFF_CONSTRAINT_CHANGED" else 1
    models = make_models(supervisor=[invalid] * attempts)
    trace = await install(env, models)
    result = await send(env, buyer)
    assert error in result["error_codes"]
    assert result["budget"]["used"]["models"] == attempts
    assert not models["shopping"].seen
    assert not any(e["kind"] == "tool" for e in trace["events"])


async def test_same_task_id_cannot_be_delegated_twice(env, buyer):
    models = make_models(
        supervisor=[
            route("order", "inspect_orders", "orders"),
            route("order", "inspect_orders", "orders"),
        ],
        order=[ai(call("list_orders")), final()],
    )
    await install(env, models)
    result = await send(env, buyer, message="查看我的订单")
    assert "REPEATED_DELEGATION" in result["error_codes"]
    assert result["budget"]["used"]["delegations"] == 1


async def test_parallel_readonly_specialists_use_distinct_sessions(env, buyer):
    import asyncio

    arrived = set()
    barrier = asyncio.Event()

    async def shopping_step(messages):
        arrived.add("shopping")
        if len(arrived) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 2)
        return ai(call("retrieve_products", {"query": "静音键盘"}))

    async def order_step(messages):
        arrived.add("order")
        if len(arrived) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 2)
        return ai(call("list_orders"))

    def parallel(messages):
        first = route("shopping", "find_products", "search")(messages).tool_calls[0]["args"][
            "tasks"
        ][0]
        second = route("order", "inspect_orders", "orders")(messages).tool_calls[0]["args"][
            "tasks"
        ][0]
        return ai(call("route", {"tasks": [first, second]}))

    models = make_models(
        supervisor=[parallel, route("finish")],
        shopping=[shopping_step, final()],
        order=[order_step, final()],
    )
    trace = await install(env, models)
    result = await send(env, buyer, message="搜索键盘并查看本人订单")
    assert arrived == {"shopping", "order"}
    assert result["error_codes"] == [], result
    assert result["budget"]["used"]["delegations"] == 2
    assert {r["target"] for r in result["results"]} == {"shopping", "order"}
    assert sum(e["kind"] == "tool" for e in trace["events"]) == 2
