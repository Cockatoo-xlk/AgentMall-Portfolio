"""Synthetic requests: user intent must survive without borrowing model assertions."""

import pytest

from agentmall.agents.purchase_intent import purchase_intent
from agentmall.infra.errors import DomainError


@pytest.mark.parametrize(
    "message,want",
    [
        ("请采购三只演示鼠标", True),
        ("准备采购一副演示耳机", True),
        ("再采购四把演示键盘", True),
        ("不要采购演示鼠标", False),
        ("暂不采购，先看看", False),
        ("请介绍采购政策", None),
        ("采购是什么意思", None),
        ("请问能否采购演示鼠标", None),
    ],
)
def test_procurement_is_an_action_not_a_topic(message, want):
    assert purchase_intent(message).requested is want


@pytest.mark.parametrize(
    "message",
    [
        "如果便宜就采购三只演示鼠标",
        "请采购第一款，但不要采购第一款",
        "请采购第一款和第二款",
        "不要采购，改买第三款",
    ],
)
def test_procurement_preserves_ambiguity_and_object_conflict_protection(message):
    with pytest.raises(DomainError) as exc:
        purchase_intent(message)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "message,want",
    [
        ("请为本人订单创建退货提案", True),
        ("帮我准备退货申请", True),
        ("请生成退货提案，是否执行由我另行确认", True),
        ("我想退掉本人订单中的商品", True),
        ("不要创建退货提案", False),
        ("暂不申请退货", False),
        ("请解释退货提案是什么意思", None),
        ("请问能否申请退货", None),
        ("查询退货政策", None),
        ("查看两条历史退货记录", None),
    ],
)
def test_return_intent_distinguishes_proposal_request_from_information(message, want):
    from agentmall.agents.request_intents import return_intent

    assert return_intent(message) is want


@pytest.mark.parametrize(
    "message,want",
    [
        ("为本人订单建立人工客服工单", True),
        ("请创建客服工单，不要自动退款", True),
        ("请联系人工处理本人订单", True),
        ("不要建立人工客服工单", False),
        ("暂不联系人工", False),
        ("人工客服工单是什么意思", None),
        ("请问能否建立客服工单", None),
        ("查看人工客服政策", None),
        ("商品采用人工编织材料", None),
    ],
)
def test_support_intent_requires_an_explicit_action(message, want):
    from agentmall.agents.request_intents import support_intent

    assert support_intent(message) is want


@pytest.mark.parametrize("intent_name", ["return_intent", "support_intent"])
@pytest.mark.parametrize("prefix", ["如果价格合适就", "等明天再", "考虑是否"])
def test_unresolved_conditions_do_not_grant_write_intent(intent_name, prefix):
    from agentmall.agents import request_intents

    action = "生成退货提案" if intent_name == "return_intent" else "创建人工客服工单"
    with pytest.raises(DomainError) as exc:
        getattr(request_intents, intent_name)(prefix + action)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_mixed_requests_keep_independent_negation_scopes():
    from agentmall.agents.request_intents import return_intent, support_intent

    text = "不要退款；请创建人工客服工单。暂不生成退货提案。"
    assert support_intent(text) is True
    assert return_intent(text) is False
    with pytest.raises(DomainError):
        return_intent("生成退货提案，但不要申请退货")


@pytest.mark.parametrize(
    "message,want",
    [
        ("请采购三只演示鼠标", 3),
        ("准备采购四副演示耳机", 4),
        ("查看两条订单；请采购三只演示鼠标", 3),
        ("分四个步骤操作；我要购买一把演示键盘", 1),
        ("请先推荐五款耳机，再采购三副演示耳机", 3),
        ("先推荐五款耳机，再采购演示耳机", None),
        ("我要买第二款演示键盘", None),
        ("只推荐三只演示鼠标", None),
        ("暂不采购三只演示鼠标", None),
        ("请采购演示键盘", None),
        ("请采购演示键盘，数量为四把", 4),
        ("请采购10只演示鼠标", 10),
    ],
)
def test_quantity_belongs_to_purchased_goods_not_other_counts(message, want):
    from agentmall.agents.request_intents import purchase_quantity

    assert purchase_quantity(message) == want


@pytest.mark.parametrize(
    "message",
    [
        "请采购三只鼠标和四副耳机",
        "请采购三只演示鼠标，数量为四只",
        "请采购零只演示鼠标",
        "请采购十一只演示鼠标",
        "请采购三到五只演示鼠标",
        "请采购三只或四只演示鼠标",
        "请采购演示鼠标；另一个商品要四只",
        "如果合适就采购三只演示鼠标",
    ],
)
def test_ambiguous_or_unsupported_purchase_quantities_require_clarification(message):
    from agentmall.agents.request_intents import purchase_quantity

    with pytest.raises(DomainError) as exc:
        purchase_quantity(message)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_typed_quantity_cannot_override_conflicting_user_quantity():
    from agentmall.agents.request_intents import purchase_quantity

    assert purchase_quantity("请采购三只演示鼠标", typed_quantity=3) == 3
    assert purchase_quantity("请采购演示鼠标", typed_quantity=4) == 4
    with pytest.raises(DomainError) as exc:
        purchase_quantity("请采购三只演示鼠标", typed_quantity=4)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "message",
    [
        "如果库存足够，请采购三只演示鼠标",
        "审核通过后请采购三只演示鼠标",
    ],
)
def test_procurement_condition_cannot_disappear_at_a_comma(message):
    with pytest.raises(DomainError) as exc:
        purchase_intent(message)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "name,action", [("return_intent", "生成退货提案"), ("support_intent", "创建人工客服工单")]
)
def test_request_scope_rejects_conditions_and_ignores_reported_actions(name, action):
    from agentmall.agents import request_intents

    intent = getattr(request_intents, name)
    with pytest.raises(DomainError):
        intent("如果审核通过，请" + action)
    assert intent("我昨天已经" + action) is None
    assert intent("说明里写着“" + action + "”") is None
    assert intent("禁止" + action) is False
    assert intent("不得" + action) is False


@pytest.mark.parametrize(
    "message", ["采购清单包含三只演示鼠标", "采购部门处理合同", "记录显示昨天已采购三只演示鼠标"]
)
def test_procurement_nouns_and_historical_records_are_not_current_requests(message):
    assert purchase_intent(message).requested is None


def test_quantity_is_not_taken_from_a_purchase_ordinal_or_another_item_in_same_clause():
    from agentmall.agents.request_intents import purchase_quantity

    assert purchase_quantity("我要购买第二个演示鼠标") is None
    with pytest.raises(DomainError):
        purchase_quantity("请采购演示鼠标并给另一个商品配四副耳罩")


@pytest.mark.parametrize(
    "message", ["禁止采购演示鼠标", "不得购买演示键盘", "不要为本人订单采购演示鼠标"]
)
def test_nonadjacent_and_strong_denial_can_override_typed_purchase_intent(message):
    assert purchase_intent(message).requested is False


@pytest.mark.parametrize(
    "message", ["请采购三只演示鼠标；再采购三副演示耳机", "请采购一只演示鼠标，改成四只"]
)
def test_equal_counts_for_different_purchases_and_unscoped_revisions_do_not_merge(message):
    from agentmall.agents.request_intents import purchase_quantity

    with pytest.raises(DomainError):
        purchase_quantity(message)


@pytest.mark.parametrize("message", ["请查看建立人工客服工单的流程", "请打开人工客服工单记录"])
def test_opening_or_reading_support_information_does_not_request_a_new_ticket(message):
    from agentmall.agents.request_intents import support_intent

    assert support_intent(message) is None


def test_procurement_keeps_original_purchase_object_and_revocation_rules():
    assert purchase_intent("不采购第二款，改买第三款").requested is True
    for message in ["请采购第一款，不要采购", "采购第二款，也买第三款"]:
        with pytest.raises(DomainError):
            purchase_intent(message)


@pytest.mark.parametrize(
    "name,action",
    [("return_intent", "创建退货提案"), ("support_intent", "创建人工客服工单")],
)
@pytest.mark.parametrize(
    "prefix", ["不允许", "不要为演示订单 10000000-0000-4000-8000-000000000009 "]
)
def test_denial_survives_intervening_order_reference(name, action, prefix):
    from agentmall.agents import request_intents

    assert getattr(request_intents, name)(prefix + action) is False


@pytest.mark.parametrize(
    "message",
    [
        "供应商将采购三只演示鼠标",
        "商家准备采购三只演示鼠标",
        "小李计划采购三只演示鼠标",
    ],
)
def test_third_party_procurement_plans_do_not_grant_a_user_request(message):
    assert purchase_intent(message).requested is None


@pytest.mark.parametrize(
    "name,message",
    [
        ("return_intent", "客服将创建退货提案"),
        ("return_intent", "小李计划创建退货提案"),
        ("support_intent", "商家准备联系人工"),
        ("support_intent", "客服将建立人工客服工单"),
    ],
)
def test_third_party_service_plans_are_not_current_user_authorization(name, message):
    from agentmall.agents import request_intents

    assert getattr(request_intents, name)(message) is None


@pytest.mark.parametrize("prefix", ["请", "帮我", "我要", "我想", "再"])
def test_explicit_user_procurement_commands_remain_supported(prefix):
    assert purchase_intent(prefix + "采购三只演示鼠标").requested is True


@pytest.mark.parametrize(
    "name,message",
    [
        ("return_intent", "请让客服创建退货提案"),
        ("support_intent", "我想让商家建立人工客服工单"),
        ("return_intent", "不要让客服创建退货提案"),
    ],
)
def test_indirect_service_instructions_require_clear_current_scope(name, message):
    from agentmall.agents import request_intents

    with pytest.raises(DomainError) as exc:
        getattr(request_intents, name)(message)
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_third_party_instruction_to_the_user_requires_clarification():
    with pytest.raises(DomainError) as exc:
        purchase_intent("供应商让我采购三只演示鼠标")
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_third_party_history_does_not_hide_a_separate_explicit_user_command():
    assert purchase_intent("供应商将采购三只演示鼠标；请采购四副演示耳机").requested is True


@pytest.mark.parametrize(
    "message,want",
    [
        ("演示订单需要转人工解释政策", True),
        ("请解释转人工政策", None),
        ("请问能否联系人工", None),
    ],
)
def test_explicit_contact_action_keeps_its_explanatory_purpose(message, want):
    from agentmall.agents.request_intents import support_intent

    assert support_intent(message) is want


@pytest.mark.parametrize(
    "message,want",
    [("之前键盘质量问题想退掉", True), ("之前已经申请退货", None)],
)
def test_past_product_reference_is_separate_from_a_past_action(message, want):
    from agentmall.agents.request_intents import return_intent

    assert return_intent(message) is want


@pytest.mark.parametrize(
    "message",
    [
        "推荐一款静音键盘准备购买",
        "另准备购买一款500元以内静音键盘",
        "申请退货，再推荐另一款演示键盘，并准备购买一件",
    ],
)
def test_current_preparation_command_is_not_a_third_party_plan(message):
    assert purchase_intent(message).requested is True


def test_quantity_range_detection_ignores_an_observed_product_uuid():
    from agentmall.agents.request_intents import purchase_quantity

    assert purchase_quantity("帮我买一件商品10000000-0000-4000-8000-000000000123，送演示家庭") == 1
