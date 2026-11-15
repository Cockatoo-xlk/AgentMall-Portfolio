"""Verified proposal observations are not permissions or new action requests."""

from copy import deepcopy

from agentmall.agents.context import Constraints

A = "10000000-0000-4000-8000-000000000001"
B = "10000000-0000-4000-8000-000000000002"


def test_outcomes_expose_current_decisions_without_private_payload_or_authority():
    from agentmall.agents.goal_receipts import action_outcomes

    facts = {
        ("proposal", B): {
            "proposal_id": B,
            "action_type": "CHECKOUT",
            "status": "REJECTED",
            "snapshot": {"address_label": "private-address-sentinel"},
        },
        ("proposal", A): {
            "proposal_id": A,
            "action_type": "RETURN_REQUEST",
            "status": "EXECUTED",
            "result": {"resource_id": B},
        },
        ("ticket", B): {"status": "OPEN"},
    }
    before = deepcopy(facts)
    observations = action_outcomes(facts)
    assert observations == [
        {"proposal_id": A, "action_type": "RETURN_REQUEST", "status": "EXECUTED"},
        {"proposal_id": B, "action_type": "CHECKOUT", "status": "REJECTED"},
    ]
    assert facts == before
    assert Constraints().purchase_requested is False
    assert Constraints().return_requested is False
    observations[0]["status"] = "APPROVED"
    assert facts[("proposal", A)]["status"] == "EXECUTED"


def test_pending_and_approved_are_not_relabelled_as_executed():
    from agentmall.agents.goal_receipts import action_outcomes

    assert action_outcomes(
        {("proposal", A): {"proposal_id": A, "action_type": "CHECKOUT", "status": "APPROVED"}}
    ) == [{"proposal_id": A, "action_type": "CHECKOUT", "status": "APPROVED"}]
    assert action_outcomes({}) == []


def test_malformed_or_unrelated_facts_cannot_appear_as_action_outcomes():
    from agentmall.agents.goal_receipts import action_outcomes

    assert (
        action_outcomes(
            {
                ("proposal", A): {
                    "proposal_id": B,
                    "action_type": "CHECKOUT",
                    "status": "EXECUTED",
                },
                ("proposal", "not-an-id"): {"action_type": "CHECKOUT", "status": "EXECUTED"},
                ("model_claim", B): {"action_type": "CHECKOUT", "status": "EXECUTED"},
                ("proposal", B): {
                    "proposal_id": B,
                    "action_type": "MOCK_REFUND",
                    "status": "EXECUTED",
                },
            }
        )
        == []
    )
