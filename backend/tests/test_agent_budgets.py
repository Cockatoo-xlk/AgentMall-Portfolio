import asyncio

import pytest


async def test_shared_budget_atomic_parallel_tool_reservations():
    from agentmall.agents.budgets import GraphBudget, Limits, RunStopped

    budget = GraphBudget(Limits(tools=2))

    async def claim():
        try:
            await budget.take("tools")
            return True
        except RunStopped:
            return False

    assert sum(await asyncio.gather(*(claim() for _ in range(10)))) == 2
    assert budget.snapshot()["used"]["tools"] == 2


async def test_failed_model_request_remains_charged():
    from agentmall.agents.budgets import GraphBudget, Limits, RunStopped

    budget = GraphBudget(Limits(models=1))
    token = await budget.start_model()
    await budget.finish_model(token, None)
    with pytest.raises(RunStopped):
        await budget.start_model()
    assert budget.snapshot()["used"]["models"] == 1
    assert budget.snapshot()["used"]["output_tokens"] > 0


@pytest.mark.parametrize(
    "limits,expected_models,expected_tools",
    [({"models": 1}, 1, 0), ({"tools": 1}, 2, 0), ({"delegations": 1}, 4, 2), ({"steps": 1}, 1, 0)],
)
async def test_budget_enforced_inside_actual_graph(
    env, buyer, limits, expected_models, expected_tools
):
    from multiagent_helpers import ai, call, final, install, make_models, route, send

    from agentmall.agents.budgets import GraphBudget, Limits

    models = make_models(
        supervisor=[
            route("order", "inspect_orders", "first"),
            route("shopping", "find_products", "second"),
        ],
        order=[ai(call("list_orders"), call("get_cart")), final()],
    )
    await install(env, models)
    env[2].state.multi_budget_factory = lambda: GraphBudget(Limits(**limits))
    result = await send(env, buyer, message="查订单和购物车，然后推荐键盘")
    assert "BUDGET_EXCEEDED" in result["error_codes"], result
    assert result["budget"]["used"]["models"] == expected_models
    assert result["budget"]["used"]["tools"] == expected_tools
    assert all(result["budget"]["used"][k] <= v for k, v in limits.items() if k != "seconds")


async def test_specialist_failure_still_consumes_model_request(env, buyer):
    from multiagent_helpers import install, make_models, route, send

    models = make_models(
        supervisor=[route("shopping", "find_products", "shop"), route("finish")],
        shopping=[TimeoutError()],
    )
    await install(env, models)
    result = await send(env, buyer, message="找键盘")
    assert result["budget"]["used"]["models"] == 3
    assert result["budget"]["used"]["output_tokens"] == 2088
    assert "SPECIALIST_TIMEOUT" in result["error_codes"]


async def test_output_tokens_reserved_across_parallel_requests():
    from agentmall.agents.budgets import GraphBudget, Limits, RunStopped

    budget = GraphBudget(Limits(output_tokens=100))
    first = await budget.start_model()
    assert budget.reservations[first] == 100
    with pytest.raises(RunStopped):
        await budget.start_model()
    await budget.finish_model(first, None)
    assert budget.snapshot()["used"]["output_tokens"] == 100


async def test_network_timeout_preserves_committed_proposal(env, buyer):
    from conftest import row
    from multiagent_helpers import (
        ai,
        call,
        choose_purchase,
        final,
        install,
        make_models,
        route,
        send,
    )

    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            TimeoutError(),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    result = await send(env, buyer)
    assert result["status"] == "partial"
    assert len(result["proposal_ids"]) == 1
    assert "SUPERVISOR_TIMEOUT" in result["error_codes"]
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1


async def test_sdk_missing_raw_usage_keeps_full_reservation():
    from langchain_core.messages import AIMessage

    from agentmall.agents.budgets import GraphBudget

    budget = GraphBudget()
    token = await budget.start_model()
    await budget.finish_model(
        token,
        AIMessage(
            content="",
            usage_metadata={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100},
            response_metadata={"token_usage": {"prompt_tokens": 100}},
        ),
    )
    assert budget.used["output_tokens"] == 2048
