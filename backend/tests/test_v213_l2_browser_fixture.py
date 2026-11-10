"""Fixture planning must respect authoritative committed facts, never weaken the guard."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from workflow_e2e import models


@pytest.mark.parametrize("status", ["EXECUTED", "REJECTED"])
async def test_browser_single_fixture_does_not_reprepare_a_decided_checkout(status):
    fixture = models("purchase", SimpleNamespace(fake_model_calls=0))["single"]
    value = {
        "constraints": {"purchase_requested": True},
        "committed_facts": [
            {"kind": "proposal", "data": {"action_type": "CHECKOUT", "status": status}}
        ],
    }
    message = await fixture.ainvoke([HumanMessage(content=json.dumps(value))], max_tokens=2048)
    assert message.tool_calls == []
    assert json.loads(message.content) == {"terminal": "finish"}


@pytest.mark.parametrize("status", ["PENDING", "APPROVED"])
async def test_browser_single_fixture_does_not_fabricate_execution_from_approval(status):
    fixture = models("purchase", SimpleNamespace(fake_model_calls=0))["single"]
    value = {
        "constraints": {"purchase_requested": True},
        "committed_facts": [
            {"kind": "proposal", "data": {"action_type": "CHECKOUT", "status": status}}
        ],
    }
    message = await fixture.ainvoke([HumanMessage(content=json.dumps(value))], max_tokens=2048)
    assert message.tool_calls[0]["name"] == "retrieve_products"
