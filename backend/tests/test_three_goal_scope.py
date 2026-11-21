"""Bind only current checkout terms. An independent query grants no write authority."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_price_contract import parse

from agentmall.agents.budgets import GraphBudget
from agentmall.agents.context import Constraints, MultiRequest
from agentmall.agents.runtime import RunContext
from agentmall.infra.errors import DomainError

FIRST = "请购买一件静音 K68，送演示宿舍"
DEFERRED = "成交后另买相同键盘"
ORDER_LIST = "另请查询本人订单"
THREE_GOALS = f"{FIRST}。{DEFERRED}。{ORDER_LIST}。"
SECOND_ID = "87000000-0000-4000-8000-000000000002"


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize(
    "message",
    [
        THREE_GOALS,
        f"{FIRST}。{DEFERRED}并请查看我的订单。",
        f"{FIRST}。成交后另买{SECOND_ID}，第二笔订单送演示家庭。{ORDER_LIST}。",
    ],
)
def test_order_query_does_not_merge_into_deferred_purchase(message, threaded):
    parsed = parse(message, threaded=threaded)
    assert parsed["purchase_requested"] is True
    assert parsed["quantity"] == 1
    assert parsed["address_label"] == "demo_dorm"
    assert parsed["product_needs"]["model_code"] == "K68"


@pytest.mark.parametrize(
    "override",
    [
        "第一笔取消",
        "第一笔改送演示家庭",
        "第一笔改成两件",
        "两笔合计预算200元",
        "查询本人订单并取消第一笔购买",
        "查询本人订单，第一笔预算100元",
    ],
)
def test_order_query_does_not_hide_first_checkout_override(override):
    with pytest.raises(DomainError) as refusal:
        parse(f"{THREE_GOALS}{override}。", threaded=True)
    assert refusal.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_runtime_restore_accepts_verified_first_order_binding():
    # Same RunContext constructor as run_service before opening the checkpoint.
    # This normalized snapshot describes the first proposal admitted by mainline.
    binding = Constraints(purchase_requested=True, quantity=1, address_label="demo_dorm")
    url = SimpleNamespace(host="127.0.0.1", port=55433, database="agentmall_test")
    sessions = SimpleNamespace(kw={"bind": SimpleNamespace(url=url)})
    request = MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=THREE_GOALS)
    runtime = RunContext(
        None,
        None,
        sessions,
        request,
        {},
        None,
        GraphBudget(),
        {},
        thread_snapshot={"constraints": binding.model_dump(mode="json")},
    )
    assert runtime.constraints == binding
    assert runtime.input.message == THREE_GOALS
    assert runtime.purchase_target_id is None


@pytest.mark.parametrize("action", ["第一笔取消", "第一笔不要了", "取消第1单", "调整第一笔数量"])
@pytest.mark.parametrize("threaded", [False, True])
def test_first_checkout_override_is_rejected_before_deferred_boundary(action, threaded):
    with pytest.raises(DomainError) as refusal:
        parse(f"{FIRST}，{action}。{DEFERRED}。{ORDER_LIST}。", threaded=threaded)
    assert refusal.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_separate_read_with_sentence_terminator_still_leaves_first_terms():
    parsed = parse(f"{FIRST}。{DEFERRED}。{ORDER_LIST}！", threaded=True)
    assert parsed["quantity"] == 1 and parsed["address_label"] == "demo_dorm"


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("second_terms", ["第二笔送演示家庭", "第2单总预算100元"])
def test_second_terms_before_purchase_boundary_cannot_bind_first(second_terms, threaded):
    with pytest.raises(DomainError) as refusal:
        parse(f"请购买一件静音 K68；{second_terms}。{DEFERRED}。{ORDER_LIST}。", threaded=threaded)
    assert refusal.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "extra",
    ["首单取消", "第一笔先不处理", "第一笔暂缓", "两笔合计预算200元"],
)
def test_pre_deferred_owner_declaration_must_be_safe_for_first_checkout(extra):
    with pytest.raises(DomainError) as refusal:
        parse(f"{FIRST}，{extra}。{DEFERRED}。{ORDER_LIST}。", threaded=True)
    assert refusal.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_explicit_first_budget_is_not_an_amendment_to_another_purchase():
    parsed = parse(f"{FIRST}，第一笔总预算250元。{DEFERRED}。{ORDER_LIST}。", threaded=True)
    assert parsed["max_price_cents"] == 25000


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize(
    "lead",
    ["请查询本人订单", "第一笔取消", "请购买一件，送演示宿舍"],
)
def test_deferred_item_cannot_supply_missing_first_intent_or_object(lead, threaded):
    with pytest.raises(DomainError) as refusal:
        parse(
            f"{lead}。成交后另请购买{SECOND_ID}，第二笔送演示家庭。{ORDER_LIST}。",
            threaded=threaded,
        )
    assert refusal.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_multi_cannot_finish_two_goals_from_one_checkout_receipt():
    from agentmall.agents.supervisor import unfinished_goal

    runtime = SimpleNamespace(
        errors=[],
        completed={},
        facts={("proposal", "first"): {"action_type": "CHECKOUT", "status": "EXECUTED"}},
        input=SimpleNamespace(message=THREE_GOALS),
        constraints=Constraints(purchase_requested=True),
    )
    assert unfinished_goal(runtime, THREE_GOALS) == "FOLLOWUP_CHECKOUT_UNRESOLVED"
