"""CONTRACT_TEST_ONLY: same-Run supplements are not a new multi-purchase batch."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentmall.agents.context import Constraints, MultiRequest, user_constraints
from agentmall.infra.errors import DomainError


def runtime(message, **constraints):
    request = MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
    return SimpleNamespace(input=request, constraints=Constraints(**constraints))


def test_legacy_clarification_supplements_existing_purchase_without_reparsing_old_action():
    from agentmall.agents.durable_graph import apply_legacy_clarification

    r = runtime(
        "另准备购买合成键盘，稍后补数量地址",
        purchase_requested=True,
        return_requested=True,
        category="keyboard",
        noise_preference="quiet",
    )
    apply_legacy_clarification(r, "预算420元以内，准备购买一款，送演示家庭")
    assert r.constraints.purchase_requested and r.constraints.return_requested
    assert r.constraints.quantity == 1 and r.constraints.address_label == "demo_home"
    assert r.constraints.max_price_cents == 42000
    assert r.constraints.category == "keyboard" and r.constraints.noise_preference == "quiet"
    restored = user_constraints(r.input)
    assert restored.quantity == 1 and restored.return_requested is True
    assert restored.category == "keyboard" and restored.noise_preference == "quiet"


def test_legacy_clarification_revokes_purchase_without_revoking_independent_return():
    from agentmall.agents.durable_graph import apply_legacy_clarification

    r = runtime(
        "准备购买一件合成键盘",
        purchase_requested=True,
        return_requested=True,
        quantity=1,
        address_label="demo_home",
    )
    apply_legacy_clarification(r, "不要购买，继续推荐三款键盘")
    assert r.constraints.purchase_requested is False
    assert r.constraints.return_requested is True
    assert r.constraints.quantity is None and r.constraints.address_label is None
    assert r.constraints.recommendation.count == 3


def test_legacy_clarification_preserves_old_budget_exclusions_and_read_requirements():
    from agentmall.agents.durable_graph import apply_legacy_clarification

    excluded = uuid4()
    r = runtime(
        "推荐替代商品并准备购买",
        purchase_requested=True,
        max_price_cents=24000,
        exclude_original=True,
        exclude_product_ids=[excluded],
        recommendation={"count": 3, "compare_connections": True},
    )
    apply_legacy_clarification(r, "预算420元以内")
    assert r.constraints.max_price_cents == 24000
    assert r.constraints.exclude_original and r.constraints.exclude_product_ids == [excluded]
    assert r.constraints.recommendation.count == 3
    assert r.constraints.recommendation.compare_connections is True
    assert r.constraints.quantity is None


def test_legacy_clarification_can_supply_units_without_repeating_the_purchase_action():
    from agentmall.agents.durable_graph import apply_legacy_clarification

    r = runtime("准备购买合成鼠标", purchase_requested=True)
    apply_legacy_clarification(r, "三只，送演示家庭")
    assert r.constraints.purchase_requested is True
    assert r.constraints.quantity == 3
    assert r.constraints.address_label == "demo_home"


def test_current_multiple_purchase_actions_are_still_rejected():
    with pytest.raises(DomainError) as exc:
        user_constraints(
            MultiRequest(
                request_id=uuid4(),
                thread_id=uuid4(),
                message="请采购三只合成鼠标，再购买三副合成耳机",
            )
        )
    assert exc.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
