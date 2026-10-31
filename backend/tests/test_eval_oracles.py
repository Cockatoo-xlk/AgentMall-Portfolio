"""All ten required Oracle negative controls are in-memory synthetic corruptions."""

from copy import deepcopy

import pytest
from evals.oracles import assess, control_example


@pytest.mark.parametrize(
    "corruption",
    [
        "duplicate_proposal_order",
        "wrong_product",
        "wrong_quantity",
        "over_budget",
        "unconfirmed_commit",
        "requested_as_refunded",
        "foreign_order",
        "wrong_policy_version",
        "internal_citation",
        "missing_committed_order",
        "ticket_as_refund",
    ],
)
def test_oracle_rejects_known_wrong_result(corruption):
    task, initial, final, result, refs = deepcopy(control_example())
    assert assess(task, initial, final, result, refs)["success"]
    if corruption == "duplicate_proposal_order":
        final["orders"].append(final["orders"][0] | {"id": "duplicate"})
    elif corruption in {"wrong_product", "wrong_quantity"}:
        final["order_items"][0]["product_id" if corruption == "wrong_product" else "quantity"] = (
            "wrong" if corruption == "wrong_product" else 2
        )
    elif corruption == "over_budget":
        final["orders"][0]["total_cents"] = 999999
    elif corruption == "unconfirmed_commit":
        final["confirmations"] = []
    elif corruption == "requested_as_refunded":
        result["facts"].append({"kind": "case", "id": "case", "data": {"status": "REFUNDED"}})
    elif corruption == "foreign_order":
        final["orders"][0]["user_id"] = "other-buyer"
    elif corruption == "wrong_policy_version":
        result["citations"][0]["policy_version"] = "wrong"
    elif corruption == "internal_citation":
        result["citations"][0]["visibility"] = "internal"
    elif corruption == "missing_committed_order":
        result["entity_refs"] = []
    elif corruption == "ticket_as_refund":
        result["answer"] = "人工工单 RESOLVED，已自动退款成功。"
    verdict = assess(task, initial, final, result, refs)
    assert not verdict["success"], corruption
    assert verdict["violations"]


def test_correct_refusal_is_success_without_an_order():
    task, initial, final, result, refs = deepcopy(control_example())
    task["expected"]["delta"]["orders"] = 0
    task["expected"]["required_sources"] = []
    task["expected"]["min_candidates"] = 0
    task["user_script"]["decisions"] = [{"action_type": "CHECKOUT", "decision": "reject"}]
    final["orders"] = final["order_items"] = []
    result["entity_refs"] = []
    final["action_proposals"][0]["status"] = "REJECTED"
    final["confirmations"][0].update(decision="reject", consumed_at=None)
    result["status"] = "blocked"
    task["expected"]["output_statuses"] = ["blocked"]
    assert assess(task, initial, final, result, refs)["success"]


def test_oracle_rejects_skipped_declared_rejection():
    task, initial, final, result, refs = deepcopy(control_example())
    task["expected"]["delta"]["orders"] = 0
    task["user_script"]["decisions"] = [{"action_type": "CHECKOUT", "decision": "reject"}]
    final["orders"] = final["order_items"] = final["action_proposals"] = final["confirmations"] = []
    result["entity_refs"] = []
    verdict = assess(task, initial, final, result, refs)
    assert not verdict["success"]
    assert any(v["rule"] == "DECLARED_DECISION_MISSING" for v in verdict["violations"])


@pytest.mark.parametrize("corruption", ["unpaid_as_paid", "internal_text_in_answer"])
def test_oracle_rejects_false_fact_and_internal_content(corruption):
    task, initial, final, result, refs = deepcopy(control_example())
    if corruption == "unpaid_as_paid":
        result["facts"].append({"kind": "order", "id": "order", "data": {"status": "PAID"}})
    else:
        final["knowledge_documents"].append(
            {"id": "internal", "visibility": "internal", "store_id": "store", "version": "demo-v1"}
        )
        final["knowledge_chunks"].append(
            {
                "id": "secret",
                "document_id": "internal",
                "section_id": "1",
                "text": "合成内部客服规则标记只用于权限阴性控制",
            }
        )
        result["answer"] += final["knowledge_chunks"][-1]["text"]
    assert not assess(task, initial, final, result, refs)["success"]
