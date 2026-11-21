"""Deferred checkout details never override the currently authorized purchase."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_price_contract import parse

from agentmall.agents.context import Constraints, MultiRequest
from agentmall.agents.durable_graph import apply_legacy_clarification
from agentmall.agents.purchase_intent import purchase_intent

FIRST = "68000000-0000-4000-8000-000000000001"
SECOND = "87000000-0000-4000-8000-000000000002"


@pytest.mark.parametrize("first", ["键盘", FIRST])
def test_later_uuid_does_not_bind_the_first_proposal(first):
    purchase = "请购买一件键盘" if first == "键盘" else f"请购买{FIRST}，数量一件"
    message = f"{purchase}，送演示宿舍。成交后另买{SECOND}，送演示家庭。"
    intent = purchase_intent(message)
    assert intent.requested
    assert intent.product_id == (None if first == "键盘" else FIRST)
    assert SECOND not in intent.reference_text


@pytest.mark.parametrize("threaded", [False, True])
def test_explicit_second_address_has_same_scope_for_both_entries(threaded):
    parsed = parse(
        "请购买一件静音K68，送演示宿舍。成交后另买两件相同键盘，第二笔订单送演示家庭。",
        threaded=threaded,
    )
    assert parsed["quantity"] == 1
    assert parsed["address_label"] == "demo_dorm"


@pytest.mark.parametrize("threaded", [False, True])
def test_current_checkout_address_after_return_remains_available(threaded):
    parsed = parse(
        "请买一件静音 K68，另请申请质量退货。收货地址是演示宿舍。",
        threaded=threaded,
    )
    assert parsed["purchase_requested"] and parsed["return_requested"]
    assert parsed["address_label"] == "demo_dorm"


@pytest.mark.parametrize("lead", ["我并未", "我从未", "我拒绝"])
def test_polite_prefix_does_not_authorize_a_denied_action(lead):
    assert not purchase_intent(f"{lead}麻烦你购买一件键盘，送演示宿舍。").requested


@pytest.mark.parametrize("lead", ["我无须", "我不准你", "我不想让你"])
def test_polite_prefix_preserves_existing_revocation(lead):
    assert purchase_intent(f"{lead}麻烦你购买键盘。").requested is False


@pytest.mark.parametrize("threaded", [False, True])
def test_explicit_revocation_conflicts_with_typed_purchase(threaded):
    result = parse(
        "我不准你麻烦购买键盘，送演示宿舍。",
        threaded=threaded,
        constraints=Constraints(purchase_requested=True, quantity=1, address_label="demo_dorm"),
    )
    assert result["purchase_requested"] is False


def test_explicit_revocation_clears_previous_purchase_before_resume():
    request = MultiRequest(
        request_id=uuid4(), thread_id=uuid4(), message="请购买一件键盘，送演示宿舍。"
    )
    runtime = SimpleNamespace(input=request, constraints=Constraints(**parse(request.message)))
    apply_legacy_clarification(runtime, "我不准你麻烦购买键盘。")
    assert runtime.constraints.purchase_requested is False
    assert runtime.constraints.quantity is None and runtime.constraints.address_label is None
