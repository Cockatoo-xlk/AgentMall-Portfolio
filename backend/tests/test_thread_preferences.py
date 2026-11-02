"""Literal expectations for cross-run replacement, not the old min-budget merge."""

from uuid import uuid4

import pytest

from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.infra.errors import DomainError


def request(message, **extra):
    return RunCreate(request_id=uuid4(), message=message, expected_context_version=0, **extra)


def test_explicit_budget_raise_preserves_other_preferences_without_inheriting_intent():
    prefs, constraints = resolve_preferences(
        {"category": "keyboard", "max_price_cents": 30000, "noise_preference": "quiet"},
        request("改成无线的，预算提高到400元"),
    )
    assert prefs == {
        "category": "keyboard",
        "max_price_cents": 40000,
        "noise_preference": "quiet",
        "product_needs": {"connection": "无线"},
    }
    assert constraints["purchase_requested"] is False
    assert constraints["quantity"] is None
    assert constraints["address_label"] is None


@pytest.mark.parametrize(
    "message,want",
    [
        ("忘记之前的预算", {"product_needs": {"connection": "无线"}}),
        ("不要无线了", {"max_price_cents": 30000}),
        ("忘记之前的预算，不要无线了", {}),
    ],
)
def test_clear_is_a_real_removal(message, want):
    prefs, _ = resolve_preferences(
        {"max_price_cents": 30000, "product_needs": {"connection": "无线"}}, request(message)
    )
    assert prefs == want


@pytest.mark.parametrize(
    "message", ["预算300元，不超过400元", "有线键盘和无线键盘", "预算300元，忘记之前的预算"]
)
def test_conflicting_same_message_requires_clarification(message):
    with pytest.raises(DomainError) as error:
        resolve_preferences({}, request(message))
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
