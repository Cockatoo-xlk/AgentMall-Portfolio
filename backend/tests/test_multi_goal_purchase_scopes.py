"""First checkout parameters in an explicitly sequenced, multi-goal request."""

import pytest
from test_price_contract import parse

from agentmall.infra.errors import DomainError

FIRST = "请购买一件宿舍静音 K68，送演示宿舍"


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize(
    "message,quantity,address,total",
    [
        ("请购买一件宿舍静音 K68。成交后另买两件相同键盘，送演示家庭。", 1, None, None),
        ("原订单123的静音 K87，送演示家庭，请申请质量退货。另" + FIRST, 1, "demo_dorm", None),
        (FIRST + "；成交后另买一件相同键盘，第二笔我还要另外确认。", 1, "demo_dorm", None),
        (FIRST + "。成交后另买两件相同键盘，每件150元，送演示家庭。", 1, "demo_dorm", None),
        (
            "订单123中的静音 K87 按键卡死，请申请质量退货。另" + FIRST + "，两件事分开给我确认。",
            1,
            "demo_dorm",
            None,
        ),
        (
            "麻烦购买两件宿舍静音 K68，送演示宿舍。整单总预算100元，"
            "两件都不能少，超了就告诉我差多少。",
            2,
            "demo_dorm",
            10000,
        ),
        (
            "请购买两件宿舍静音 K68，送演示宿舍，整单总预算150元，两件都不能少。",
            2,
            "demo_dorm",
            15000,
        ),
    ],
)
def test_primary_purchase_has_its_own_terms(threaded, message, quantity, address, total):
    actual = parse(message, threaded=threaded)
    assert actual["purchase_requested"]
    assert actual["quantity"] == quantity
    assert actual["address_label"] == address
    assert actual["max_price_cents"] == total
    assert actual["product_needs"]["model_code"] == "K68"
    assert actual["product_needs"].get("unit_price_cents") is None


def test_quantity_restatement_must_agree_with_requested_quantity():
    with pytest.raises(DomainError):
        parse(FIRST + "，两件都不能少。")


@pytest.mark.parametrize(
    "qualifier",
    [
        "两笔合计预算200元",
        "第一单改送演示家庭",
        "整笔预算最多300元",
        "但第一笔不要了",
        "两次购买总预算300元",
    ],
)
def test_cross_order_changes_require_clarification(qualifier):
    with pytest.raises(DomainError):
        parse(FIRST + "。成交后另买两件相同键盘，" + qualifier)


@pytest.mark.parametrize("prefix", ["不要", "昨天", "如果便宜就"])
def test_polite_request_keeps_denial_history_and_conditions(prefix):
    from agentmall.agents.purchase_intent import purchase_intent

    message = prefix + "麻烦购买两件宿舍静音 K68"
    if prefix == "如果便宜就":
        with pytest.raises(DomainError):
            purchase_intent(message)
    else:
        assert purchase_intent(message).requested is not True


def test_unbound_goods_count_is_not_a_count_of_tasks():
    with pytest.raises(DomainError):
        parse(FIRST + "，两件事务用品。")


@pytest.mark.parametrize("threaded", [False, True])
def test_second_owned_budget_cannot_replace_first_quote_or_limit(threaded):
    result = parse(
        FIRST + "，每件199元，总预算210元。成交后另买两件同款键盘；第二单总预算450元。",
        threaded=threaded,
    )
    assert result["quantity"] == 1
    assert result["max_price_cents"] == 21000
    assert result["product_needs"]["unit_price_cents"] == 19900
