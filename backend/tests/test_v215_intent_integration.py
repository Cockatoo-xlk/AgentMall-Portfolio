"""CONTRACT_TEST_ONLY integration of current decisions, quantities and proposal receipts."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentmall.agents.budgets import GraphBudget
from agentmall.agents.context import Constraints, MultiRequest, SpecialistResult, user_constraints
from agentmall.agents.memory import accept_clarification
from agentmall.infra.errors import DomainError


def request(message, **kwargs):
    return MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message, **kwargs)


def test_current_user_command_keeps_its_leading_modifier():
    c = user_constraints(request("再帮我推荐一款500元以内静音键盘准备购买，送演示宿舍"))
    assert c.purchase_requested is True and c.quantity == 1


async def test_single_item_clarification_clause_can_include_an_address(clarification_state):
    run = clarification_state(purchase_requested=True)
    binding = await accept_clarification(None, None, run, "一款，送演示宿舍")
    assert binding["constraints"]["quantity"] == 1
    assert binding["constraints"]["address_label"] == "demo_dorm"


@pytest.mark.parametrize(
    "field,message",
    [
        ("return_requested", "为本人订单创建退货提案"),
        ("support_requested", "为本人订单建立人工客服工单"),
    ],
)
def test_current_explicit_action_reaches_product_constraints(field, message):
    constraints = user_constraints(request(message))
    assert getattr(constraints, field) is True


@pytest.mark.parametrize(
    "field,message",
    [
        ("return_requested", "禁止为本人订单创建退货提案"),
        ("support_requested", "禁止为本人订单建立人工客服工单"),
    ],
)
def test_current_revocation_overrides_typed_permission(field, message):
    constraints = user_constraints(
        request(message, constraints=Constraints.model_validate({field: True}))
    )
    assert getattr(constraints, field) is False
    if field == "support_requested":
        assert constraints.support_declined is True


@pytest.mark.parametrize(
    "field,message",
    [
        ("return_requested", "为本人订单创建退货提案"),
        ("support_requested", "为本人订单建立人工客服工单"),
    ],
)
def test_current_positive_action_cannot_override_typed_denial(field, message):
    with pytest.raises(DomainError) as exc:
        user_constraints(request(message, constraints=Constraints.model_validate({field: False})))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "message", ["查询退货政策", "请解释人工客服工单流程", "之前已经创建退货提案"]
)
def test_informational_or_historical_topics_grant_no_new_action(message):
    constraints = user_constraints(request(message))
    assert constraints.return_requested is False
    assert constraints.support_requested is False
    assert constraints.purchase_requested is False


def test_purchase_units_are_independent_of_recommendation_count():
    constraints = user_constraints(request("先推荐四款键盘，再采购三把合成键盘"))
    assert constraints.purchase_requested is True
    assert constraints.quantity == 3
    assert constraints.recommendation.count == 4


def test_typed_quantity_conflict_is_not_silently_replaced():
    with pytest.raises(DomainError) as exc:
        user_constraints(request("请采购四只合成鼠标", constraints=Constraints(quantity=3)))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_a_recommendation_of_one_is_not_purchasing_quantity():
    constraints = user_constraints(request("推荐一款合成键盘，仅供选择"))
    assert constraints.recommendation.count == 1
    assert constraints.purchase_requested is False
    assert constraints.quantity is None


@pytest.mark.parametrize(
    "message",
    ["准备购买一款合成键盘", "找一款360元以内键盘准备购买", "我要买第二款，一件，送演示宿舍"],
)
def test_legacy_unambiguous_one_item_purchase_remains_supported(message):
    constraints = user_constraints(request(message))
    assert constraints.purchase_requested is True
    assert constraints.quantity == 1


@pytest.mark.parametrize(
    "message",
    [
        "推荐一款500元以内合成键盘，准备购买，送演示宿舍",
        "再推荐另一款500元以内合成键盘，准备购买，送演示家庭",
    ],
)
def test_legacy_single_recommendation_with_current_purchase_keeps_one_item_quantity(message):
    constraints = user_constraints(request(message))
    assert constraints.purchase_requested is True
    assert constraints.quantity == 1


@pytest.mark.parametrize(
    "message,typed_quantity,want",
    [
        ("推荐三款合成键盘，准备购买", None, None),
        ("推荐一款合成键盘，准备购买两件", None, 2),
        ("推荐一款合成键盘，准备购买", 2, 2),
        ("不要推荐一款合成键盘，准备购买", None, None),
        ("不要找一款合成键盘，准备购买", None, None),
    ],
)
def test_legacy_one_item_compatibility_never_overrides_explicit_units_or_multiple_choices(
    message, typed_quantity, want
):
    typed = Constraints(quantity=typed_quantity) if typed_quantity is not None else None
    constraints = user_constraints(request(message, constraints=typed))
    assert constraints.purchase_requested is True
    assert constraints.quantity == want


def test_typed_bundle_quantities_do_not_collapse_into_a_single_product_count():
    bundle = user_constraints(
        request("预算1800元，组合键盘一把、耳机两副，先推荐，不要购买")
    ).bundle
    constraints = user_constraints(
        request("就买这套，每样一件，送演示宿舍", constraints=Constraints(bundle=bundle))
    )
    assert constraints.purchase_requested is True
    assert constraints.bundle == bundle
    assert [part.quantity for part in constraints.bundle.parts] == [1, 2]
    assert constraints.recommendation is None


def test_displayed_bundle_each_quantity_waits_for_the_existing_bundle_owner():
    constraints = user_constraints(request("就买这套，每样两件，送演示宿舍"))
    assert constraints.purchase_requested is True
    assert constraints.quantity is None
    assert constraints.bundle is None


@pytest.mark.parametrize(
    "message",
    [
        "请采购三只合成鼠标，每样一件",
        "请采购三只合成鼠标，各一件",
        "请采购合成鼠标，每样一件",
        "请采购三只合成鼠标，每样一件，之后查看这套",
        "请采购三只合成鼠标，再买这套，每样一件",
    ],
)
def test_nonbundle_each_quantity_cannot_bypass_typed_purchase_quantity_conflicts(message):
    with pytest.raises(DomainError) as exc:
        user_constraints(request(message, constraints=Constraints(quantity=4)))
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("reference", ["那套", "整套方案", "刚才那套"])
def test_explicit_bundle_target_keeps_each_quantity_with_the_bundle_owner(reference):
    constraints = user_constraints(request(f"就买{reference}，各一件，送演示宿舍"))
    assert constraints.purchase_requested is True
    assert constraints.quantity is None


@pytest.fixture
def clarification_state(monkeypatch):
    from agentmall.agents import memory

    context = SimpleNamespace(preferences={}, version=7, offered_ids=[], focus={}, provenance={})

    async def locked(*args):
        return context

    async def now(*args):
        return datetime(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(memory, "locked_context", locked)
    monkeypatch.setattr(memory, "database_now", now)

    def run_for(**active):
        return SimpleNamespace(
            id=uuid4(),
            request_id=uuid4(),
            thread_id=uuid4(),
            resume_journal={},
            context_snapshot={
                "version": 7,
                "constraints": Constraints(**active).model_dump(mode="json"),
                "selected": [],
            },
        )

    return run_for


@pytest.mark.parametrize(
    "field,message",
    [
        ("return_requested", "禁止为本人订单创建退货提案"),
        ("support_requested", "禁止为本人订单建立人工客服工单"),
    ],
)
async def test_clarification_revocation_is_not_restored_from_active_run(
    clarification_state, field, message
):
    run = clarification_state(**{field: True})
    binding = await accept_clarification(None, None, run, message)
    assert binding["constraints"][field] is False
    if field == "support_requested":
        assert binding["constraints"]["support_declined"] is True


@pytest.mark.parametrize("message", ["三只", "数量为三只"])
async def test_clarification_can_supply_quantity_to_the_same_active_purchase(
    clarification_state, message
):
    run = clarification_state(purchase_requested=True, address_label="demo_home")
    binding = await accept_clarification(None, None, run, message)
    assert binding["constraints"]["purchase_requested"] is True
    assert binding["constraints"]["quantity"] == 3
    assert binding["constraints"]["address_label"] == "demo_home"


async def test_quantity_clarification_does_not_create_a_purchase_intent(clarification_state):
    run = clarification_state(purchase_requested=False)
    binding = await accept_clarification(None, None, run, "三只")
    assert binding["constraints"]["purchase_requested"] is False
    assert binding["constraints"]["quantity"] is None


async def test_same_run_information_preserves_existing_intent_without_granting_other_actions(
    clarification_state,
):
    run = clarification_state(return_requested=True)
    binding = await accept_clarification(None, None, run, "查看处理说明")
    assert binding["constraints"]["return_requested"] is True
    assert binding["constraints"]["support_requested"] is False
    assert binding["constraints"]["purchase_requested"] is False


async def test_same_run_budget_clarification_preserves_candidate_count_and_comparison(
    clarification_state,
):
    run = clarification_state(recommendation={"count": 3, "compare_connections": True})
    binding = await accept_clarification(None, None, run, "预算改为420元")
    assert binding["constraints"]["recommendation"] == {"count": 3, "compare_connections": True}
    assert "recommendation" not in binding["preferences"]
    assert run.context_snapshot["constraints"]["recommendation"]["count"] == 3


@pytest.mark.parametrize("message", ["推荐两款", "不要推荐三款，推荐两款"])
async def test_same_run_new_candidate_count_keeps_the_unrevoked_comparison(
    clarification_state, message
):
    run = clarification_state(recommendation={"count": 3, "compare_connections": True})
    binding = await accept_clarification(None, None, run, message)
    assert binding["constraints"]["recommendation"] == {"count": 2, "compare_connections": True}
    assert run.context_snapshot["constraints"]["recommendation"]["count"] == 3


async def test_same_run_new_comparison_keeps_the_existing_candidate_count(clarification_state):
    run = clarification_state(recommendation={"count": 3, "compare_connections": False})
    binding = await accept_clarification(None, None, run, "比较有线和无线")
    assert binding["constraints"]["recommendation"] == {"count": 3, "compare_connections": True}


@pytest.mark.parametrize("message", ["不要推荐了", "不要比较了"])
async def test_same_run_explicit_recommendation_revocation_removes_the_read_requirement(
    clarification_state, message
):
    run = clarification_state(recommendation={"count": 3, "compare_connections": True})
    binding = await accept_clarification(None, None, run, message)
    assert "recommendation" not in binding["constraints"]


@pytest.mark.parametrize(
    "field,action", [("return_requested", "申请退货"), ("support_requested", "联系人工")]
)
async def test_historical_order_reference_does_not_restore_revoked_run_permission(
    clarification_state, field, action
):
    run = clarification_state(**{field: True})
    binding = await accept_clarification(None, None, run, "昨天的订单不要" + action)
    assert binding["constraints"][field] is False
    if field == "support_requested":
        assert binding["constraints"]["support_declined"] is True


@pytest.mark.parametrize("action", ["比较", "对比", "对照"])
async def test_cancelling_only_comparison_keeps_the_current_recommendation_count(
    clarification_state, action
):
    run = clarification_state(recommendation={"count": 3, "compare_connections": True})
    binding = await accept_clarification(None, None, run, f"不要{action}了，只推荐三款无线键盘")
    assert binding["constraints"]["recommendation"] == {
        "count": 3,
        "compare_connections": False,
    }
    assert binding["constraints"]["product_needs"]["connection"] == "无线"


async def test_a_later_new_run_does_not_inherit_the_previous_runs_recommendation(
    clarification_state,
):
    from agentmall.agents.memory import resolve_preferences
    from agentmall.agents.run_schemas import RunCreate

    run = clarification_state(recommendation={"count": 3, "compare_connections": True})
    binding = await accept_clarification(None, None, run, "预算改为420元")
    _, next_constraints = resolve_preferences(
        binding["preferences"], RunCreate(request_id=uuid4(), message="继续看看")
    )
    assert "recommendation" not in next_constraints


async def test_supervisor_receives_current_action_outcomes_separately_from_stale_task_history():
    from multiagent_helpers import MultiModel, ai, call, payload

    from agentmall.agents.supervisor import choose_plan

    proposal_id = str(uuid4())

    def inspect(messages):
        value = payload(messages)
        assert value["action_outcomes"] == [
            {"proposal_id": proposal_id, "action_type": "CHECKOUT", "status": "REJECTED"}
        ]
        assert value["completed"][0]["status"] == "proposal"
        assert value["canonical_constraints"]["purchase_requested"] is False
        assert "private-address-sentinel" not in json.dumps(value)
        return ai(call("route", {"tasks": [], "terminal": "finish"}))

    constraints = Constraints()
    runtime = SimpleNamespace(
        trace={"prompts": {}},
        models={"supervisor": MultiModel(role="supervisor", script=[inspect])},
        thread_snapshot={},
        constraints=constraints,
        input=request("处理已记录的决定"),
        purchase_target_id=None,
        references={},
        citations={},
        completed={
            "old": SpecialistResult(
                subtask_id="old", target="order", status="proposal", summary="old waiting state"
            )
        },
        facts={
            ("proposal", proposal_id): {
                "proposal_id": proposal_id,
                "action_type": "CHECKOUT",
                "status": "REJECTED",
                "snapshot": {"address": "private-address-sentinel"},
            }
        },
        budget=GraphBudget(),
        errors=[],
        exclusions=set(),
        schema_repairs=0,
        checkout_blocker=lambda: "PURCHASE_NOT_REQUESTED",
        handoff_constraints=lambda: constraints,
        event=lambda *args, **kwargs: None,
    )
    plan = await choose_plan(runtime)
    assert plan.terminal == "finish"
    assert runtime.budget.used["models"] == 1
    assert runtime.budget.used["tools"] == 0
