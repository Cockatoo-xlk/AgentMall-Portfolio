"""Verified capabilities, never names, qualify a product before recall truncation."""

from types import SimpleNamespace

import pytest

from agentmall.agents.context import Constraints
from agentmall.agents.specialist_tools import product_allowed


@pytest.mark.parametrize(
    "label,capabilities,want",
    [
        ("双模", ["wired", "wireless"], True),
        ("三模", ["wired", "wireless"], True),
        ("双模", None, False),
        ("三模", None, False),
        ("有线", ["wired"], False),
        ("无线", None, True),
        ("无线", ["wired"], False),
        ("双模", "wireless", False),
    ],
)
def test_wireless_requires_explicit_catalogue_capability(label, capabilities, want):
    attributes = {"connection": label, "noise": "较安静"}
    if capabilities is not None:
        attributes["connection_capabilities"] = capabilities
    product = SimpleNamespace(
        id="synthetic", available=1, category="keyboard", price_cents=29900, attributes=attributes
    )
    runtime = SimpleNamespace(
        constraints=Constraints(product_needs={"connection": "无线"}), exclusions=set()
    )
    assert product_allowed(runtime, product) is want


@pytest.mark.parametrize(
    "label,caps,want",
    [
        ("有线", ["wired"], True),
        ("有线", ["wired", "wireless"], False),
        ("双模", ["wired", "wireless"], False),
    ],
)
def test_wired_only_does_not_accept_conflicting_wireless_capability(label, caps, want):
    product = SimpleNamespace(
        id="synthetic",
        available=1,
        category="keyboard",
        price_cents=29900,
        attributes={"connection": label, "connection_capabilities": caps},
    )
    runtime = SimpleNamespace(
        constraints=Constraints(product_needs={"connection": "有线"}), exclusions=set()
    )
    assert product_allowed(runtime, product) is want
