"""CONTRACT_TEST_ONLY: new synthetic preferences and trusted recommendation facts."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from t09_helpers import durable_env as durable_env

from agentmall.agents.budgets import GraphBudget
from agentmall.agents.context import Constraints, EntityRef, MultiRequest, user_constraints
from agentmall.agents.graph import render
from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.agents.specialist_tools import product_allowed
from agentmall.catalog.schemas import ProductDTO
from agentmall.infra.errors import DomainError


def request(message, **kwargs):
    return MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message, **kwargs)


@pytest.mark.parametrize(
    "message",
    [
        "对照有线和无线键盘，推荐三款，单价360元以内",
        "推荐三款键盘，比较无线与有线的连接区别",
        "推荐3款键盘，有线或无线均可",
        "找三款键盘，无线/有线都可以",
        "只要有线或无线键盘",
    ],
)
def test_connection_comparison_and_options_do_not_become_one_hard_mode(message):
    constraints = user_constraints(request(message))
    assert constraints.product_needs.connection is None
    prefs, effective = resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
    assert prefs.get("product_needs", {}).get("connection") is None
    assert effective["product_needs"]["connection"] is None


def test_comparison_replaces_persisted_single_connection_without_erasing_other_preferences():
    prefs, effective = resolve_preferences(
        {"max_price_cents": 36000, "product_needs": {"connection": "无线"}},
        RunCreate(request_id=uuid4(), message="比较有线和无线键盘，推荐三款"),
    )
    assert prefs["max_price_cents"] == 36000
    assert prefs.get("product_needs", {}).get("connection") is None
    assert effective["product_needs"]["connection"] is None


@pytest.mark.parametrize(
    "message", ["键盘必须有线，也必须无线", "键盘仅限有线，只要无线", "要求有线和无线键盘"]
)
def test_incompatible_connection_requirements_need_clarification_in_both_paths(message):
    with pytest.raises(DomainError) as stateless:
        user_constraints(request(message))
    assert stateless.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
    with pytest.raises(DomainError) as threaded:
        resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
    assert threaded.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("message", ["不要有线键盘", "不接受无线键盘，推荐三款"])
def test_negative_only_connection_cannot_become_a_positive_filter(message):
    with pytest.raises(DomainError) as exc:
        user_constraints(request(message))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_explicit_replacement_of_a_rejected_connection_remains_constrained():
    message = "不要有线键盘，请推荐无线键盘"
    assert user_constraints(request(message)).product_needs.connection == "无线"
    _, constraints = resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
    assert constraints["product_needs"]["connection"] == "无线"


def test_revoked_recommendation_does_not_create_a_count_goal():
    r = runtime_for("不要推荐三款键盘", [])
    assert r.constraints.recommendation is None
    assert "候选不足" not in render(r, "finish").answer


def test_replacement_count_ignores_the_explicitly_revoked_count():
    constraints = user_constraints(request("不要推荐三款键盘，改为推荐两款键盘"))
    assert constraints.recommendation.count == 2


def test_negated_comparison_cannot_create_a_comparison_requirement():
    with pytest.raises(DomainError) as exc:
        user_constraints(request("不要比较有线和无线键盘"))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def product(number, connection, *, price=25000, available=8):
    return ProductDTO(
        id=UUID(int=number),
        name=f"Synthetic board {number}",
        description="CONTRACT_TEST_ONLY",
        category="keyboard",
        price_cents=price,
        currency="CNY",
        available=available,
        catalog_version=3,
        attributes={
            "connection": connection,
            "connection_capabilities": ["wired" if connection == "有线" else "wireless"],
            "noise": "较安静",
        },
    )


def runtime_for(message, products, **kwargs):
    constraints = user_constraints(request(message, **kwargs))
    refs = [EntityRef(kind="product", id=p.id, relation="replacement") for p in products]
    return SimpleNamespace(
        input=request(message),
        constraints=constraints,
        exclusions=set(),
        references={(r.kind, str(r.id), r.relation): r for r in refs},
        facts={("product", str(p.id)): p.model_dump(mode="json") for p in products},
        completed={},
        pending={},
        errors=[],
        citations={},
        budget=GraphBudget(),
        prune_excluded_candidates=lambda: None,
        mode="FIXTURE",
    )


def test_explicit_single_connection_and_price_remain_hard_filters():
    runtime = runtime_for("只要无线键盘，单价360元以内", [])
    assert product_allowed(runtime, product(1, "无线"))
    assert not product_allowed(runtime, product(2, "有线"))
    assert not product_allowed(runtime, product(3, "无线", price=36100))
    assert not product_allowed(runtime, product(4, "无线", available=0))


def test_candidate_count_is_a_read_requirement_not_purchase_quantity():
    constraints = user_constraints(request("推荐三款键盘，仅供比较"))
    recommendation = getattr(constraints, "recommendation", None)
    assert recommendation is not None
    assert recommendation.count == 3
    assert constraints.quantity is None
    assert constraints.purchase_requested is False


def test_typed_purchase_quantity_does_not_replace_recommendation_count():
    constraints = user_constraints(request("推荐三款键盘", constraints=Constraints(quantity=2)))
    recommendation = getattr(constraints, "recommendation", None)
    assert recommendation is not None
    assert recommendation.count == 3
    assert constraints.quantity == 2


def test_short_candidate_set_has_truthful_incomplete_status_without_invented_products():
    runtime = runtime_for("推荐三款键盘", [product(10, "无线")])
    result = render(runtime, "finish")
    assert result.status == "needs_input"
    assert "不足" in result.answer
    assert "1" in result.answer and "3" in result.answer
    assert len([r for r in result.entity_refs if r.kind == "product"]) == 1
    assert result.proposal_ids == []


def test_comparison_uses_committed_connection_fields_and_detects_missing_side():
    runtime = runtime_for("比较有线和无线键盘，推荐两款", [product(11, "无线")])
    result = render(runtime, "finish")
    assert result.status == "needs_input"
    assert "无线" in result.answer
    assert "对照" in result.answer


def test_complete_comparison_is_rendered_from_facts():
    runtime = runtime_for(
        "比较有线和无线键盘，推荐两款", [product(12, "有线"), product(13, "无线")]
    )
    result = render(runtime, "finish")
    assert result.status == "done"
    assert "有线" in result.answer and "无线" in result.answer
    assert "25000" in result.answer and "8" in result.answer


def test_absent_recommendation_fields_preserve_legacy_constraint_payload():
    assert "recommendation" not in Constraints().model_dump(mode="json")


def test_bundle_keeps_independent_part_connections_and_no_single_recommendation_goal():
    constraints = user_constraints(request("搭配一套，总预算900元，包括有线键盘、无线耳机"))
    assert constraints.bundle is not None
    assert [p.requirements.connection for p in constraints.bundle.parts] == ["有线", "无线"]
    assert getattr(constraints, "recommendation", None) is None


def test_explicit_single_mode_with_rejected_other_mode_agrees_across_paths():
    message = "只要无线键盘，不要有线键盘"
    assert user_constraints(request(message)).product_needs.connection == "无线"
    _, effective = resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
    assert effective["product_needs"]["connection"] == "无线"


def test_same_connection_required_and_rejected_needs_clarification():
    with pytest.raises(DomainError) as exc:
        user_constraints(request("必须无线键盘，但拒绝无线"))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_typed_bundle_does_not_acquire_a_single_product_candidate_count():
    bundle = user_constraints(request("搭配一套，总预算900元，包括有线键盘、无线耳机")).bundle
    constraints = user_constraints(request("推荐三款方案", constraints=Constraints(bundle=bundle)))
    assert constraints.bundle == bundle
    assert getattr(constraints, "recommendation", None) is None


def test_comparison_does_not_cancel_an_explicit_rejection():
    with pytest.raises(DomainError) as exc:
        user_constraints(request("比较有线和无线键盘，但不要无线"))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_typed_count_cannot_silently_reduce_the_textual_recommendation_request():
    typed = Constraints.model_validate({"recommendation": {"count": 1}})
    with pytest.raises(DomainError) as exc:
        user_constraints(request("推荐三款键盘", constraints=typed))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


async def synthetic_catalog(env):
    """A new four-row catalog inside the fixture's disposable PostgreSQL schema."""
    from retrieval_helpers import index
    from sqlalchemy import update

    from agentmall.catalog.models import Product

    async with env[2].state.sessions.begin() as session:
        await session.execute(update(Product).values(active=False))
        for number, mode, price, stock in (
            (8001, "有线", 18000, 7),
            (8002, "无线", 26000, 9),
            (8003, "无线", 39000, 10),
            (8004, "有线", 5000, 0),
        ):
            session.add(
                Product(
                    id=UUID(int=number),
                    store_id=env[3].storefront_id,
                    name=f"Contract keyboard {number}",
                    category="keyboard",
                    price_cents=price,
                    on_hand=stock,
                    reserved=0,
                    active=True,
                    catalog_version=1,
                    attributes={
                        "connection": mode,
                        "connection_capabilities": ["wired" if mode == "有线" else "wireless"],
                    },
                    description="CONTRACT_TEST_ONLY fresh four-row catalog",
                )
            )
    return await index(env)


@pytest.mark.parametrize(
    "message,identifiers",
    [
        ("对照无线与有线键盘，推荐两款，单价360元以内", {8001, 8002}),
        ("只要无线键盘，单价360元以内", {8002}),
    ],
)
async def test_postgres_product_tool_keeps_hard_filters_and_comparison_options(
    env, message, identifiers
):
    from retrieval_helpers import actor

    from agentmall.agents.context import HandoffEnvelope
    from agentmall.agents.runtime import RunContext
    from agentmall.agents.specialist_tools import SpecialistTools

    encoder = await synthetic_catalog(env)
    runtime = RunContext(
        actor(env[3]),
        env[3],
        env[2].state.sessions,
        request(message),
        {},
        encoder,
        GraphBudget(),
        {},
    )
    envelope = HandoffEnvelope(
        subtask_id="contract_recommendation",
        target="shopping",
        goal="find_products",
        constraints=runtime.handoff_constraints(),
        remaining_budget=runtime.budget.snapshot(),
    )
    output = await SpecialistTools(runtime, envelope).execute(
        "retrieve_products", {"query": "键盘"}
    )
    assert output["ok"] is True
    assert {UUID(p["id"]).int for p in output["data"]["items"]} == identifiers
    assert all(p["product"]["price_cents"] <= 36000 for p in output["data"]["items"])
    assert all(p["product"]["available"] > 0 for p in output["data"]["items"])
    assert not any(kind == "proposal" for kind, _ in runtime.facts)


@pytest.mark.parametrize(
    "count,run_status,result_status",
    [(2, "COMPLETED", "done"), (3, "WAITING_INPUT", "needs_input")],
)
async def test_postgres_single_stops_truthfully_at_actual_candidate_count(
    durable_env, buyer, count, run_status, result_status
):
    from conftest import row
    from multiagent_helpers import ai, call, final
    from t09_helpers import start, thread
    from test_baseline_fairness import SingleModel

    env = durable_env
    await synthetic_catalog(env)
    model = SingleModel(
        role="order", script=[ai(call("retrieve_products", {"query": "键盘"})), final()]
    )
    env[2].state.durable_single_model = model
    tid = await thread(env, buyer, "single")
    response = await start(
        env, buyer, tid, message=f"比较有线和无线键盘，推荐{count}款，单价360元以内，不要购买"
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == run_status, run
    result = run["result"]
    assert result["status"] == result_status
    products = [f for f in result["facts"] if f["kind"] == "product"]
    assert {UUID(p["id"]).int for p in products} == {8001, 8002}
    assert "有线" in result["answer"] and "无线" in result["answer"]
    assert ("不足" in result["answer"]) is (count == 3)
    assert run["budget"]["models"] == 2
    assert run["budget"]["tools"] == 1
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 0
