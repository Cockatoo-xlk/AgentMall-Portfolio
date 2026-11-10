"""Current user intent is independent of remembered preferences and model assertions."""

from uuid import uuid4

import pytest

from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.infra.errors import DomainError


@pytest.mark.parametrize(
    "message,want",
    [
        ("我不想买第二款。", False),
        ("我不需要买第二款。", False),
        ("不要买第二款，只想看看。", False),
        ("先别下单。", False),
        ("我取消购买，继续比较商品。", False),
        ("不要再买第二款，一件，送演示宿舍。", False),
        ("我不打算买第二款，一件，送演示宿舍。", False),
        ("不用帮我买第二款，一件，送演示宿舍。", False),
        ("我不需要再买第二款，一件，送演示宿舍。", False),
        ("我要买第二款，一件。", True),
        ("不买第二款，改买第三款，一件。", True),
    ],
)
def test_current_turn_purchase_intent(message, want):
    preferences, constraints = resolve_preferences(
        {"category": "keyboard", "max_price_cents": 40000},
        RunCreate(request_id=uuid4(), message=message, expected_context_version=0),
    )
    assert constraints["purchase_requested"] is want
    assert "purchase_requested" not in preferences


@pytest.mark.parametrize("message", ["我不想买第二款", "我取消购买", "先别下单"])
def test_explicit_negation_overrides_typed_purchase_assertion(message):
    _, constraints = resolve_preferences(
        {},
        RunCreate(
            request_id=uuid4(),
            message=message,
            expected_context_version=0,
            constraints={"purchase_requested": True, "quantity": 1, "address_label": "demo_dorm"},
        ),
    )
    assert constraints["purchase_requested"] is False


@pytest.mark.parametrize(
    "message",
    [
        "不买第二款，又要买第二款",
        "买第二款也买第三款",
        "取消购买，改买第三款",
        "不买第二款，买第2款",
    ],
)
def test_conflicting_or_multiple_purchase_targets_need_clarification(message):
    with pytest.raises(DomainError) as failure:
        resolve_preferences(
            {}, RunCreate(request_id=uuid4(), message=message, expected_context_version=0)
        )
    assert failure.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_connection_exclusion_is_not_a_positive_multi_mode_requirement():
    prefs, constraints = resolve_preferences(
        {},
        RunCreate(
            request_id=uuid4(),
            message="支持无线连接，但不接受双模／三模",
            expected_context_version=0,
        ),
    )
    assert prefs["product_needs"] == {
        "connection": "无线",
        "excluded_connections": ["双模", "三模"],
    }
    assert constraints["product_needs"]["connection"] == "无线"


def test_empty_typed_exclusions_remove_old_exclusions_without_breaking_candidate_digest():
    prefs, _ = resolve_preferences(
        {"product_needs": {"connection": "无线", "excluded_connections": ["双模"]}},
        RunCreate(
            request_id=uuid4(),
            message="继续推荐",
            expected_context_version=0,
            constraints={"product_needs": {"excluded_connections": []}},
        ),
    )
    assert prefs == {"product_needs": {"connection": "无线"}}


def test_typed_denial_cannot_be_overwritten_by_textual_purchase():
    with pytest.raises(DomainError) as failure:
        resolve_preferences(
            {},
            RunCreate(
                request_id=uuid4(),
                message="买第二款，一件",
                expected_context_version=0,
                constraints={"purchase_requested": False},
            ),
        )
    assert failure.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("joiner", ["或", "或者", "还是", "也买"])
def test_two_explicit_product_ids_require_clarification(joiner):
    first, second = uuid4(), uuid4()
    with pytest.raises(DomainError) as failure:
        resolve_preferences(
            {},
            RunCreate(
                request_id=uuid4(),
                message=f"我要买{first}{joiner}{second}，一件，送演示宿舍。",
                expected_context_version=0,
            ),
        )
    assert failure.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("message", ["我不一定买第二款，一件", "不要让助手帮我买第二款，一件"])
def test_unresolved_negative_scope_never_becomes_positive_intent(message):
    with pytest.raises(DomainError) as failure:
        resolve_preferences(
            {}, RunCreate(request_id=uuid4(), message=message, expected_context_version=0)
        )
    assert failure.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
