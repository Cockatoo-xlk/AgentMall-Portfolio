"""Synthetic assertion contracts, not product-smoke or independent Holdout results."""

import importlib
import importlib.util

import pytest
from evals.smoke_runner import SmokeStopped, export_evidence


def scorer():
    assert importlib.util.find_spec("evals.smoke_assertions"), "Frozen SQL assertion scorer missing"
    return importlib.import_module("evals.smoke_assertions")


def test_completed_run_without_required_order_fails_after_verified_export(tmp_path):
    facts = {
        "orders": [],
        "cases": [],
        "confirmations": [],
        "proposals": [],
        "items": [],
        "products": [],
        "payments": 0,
        "refunds": 0,
        "checkpoint_count": 2,
        "runs": [],
    }
    evidence = {
        "case_index": 1,
        "task_id": "CONTRACT_TEST_ONLY",
        "run": {"status": "COMPLETED"},
        "baseline": facts,
        "after": facts,
        "ledger": {
            "halted": None,
            "attempts": [
                {
                    "state": "SETTLED",
                    "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    "held_cny": "0.00036",
                }
            ],
        },
        "operator_audit": [],
        "stage_facts": [],
    }
    export_evidence(tmp_path, evidence)
    result = scorer().score_verified(tmp_path)
    assert result["status"] == "FAIL"
    assert "ORDER_DELTA" in result["violations"]
    assert result["actual_supplier_invoice_cny"] == "UNKNOWN"


def test_unverified_or_modified_export_cannot_be_scored(tmp_path):
    with pytest.raises(SmokeStopped, match="VERIFIED_EVIDENCE_REQUIRED"):
        scorer().score_verified(tmp_path)


def test_unknown_usage_is_not_zero_or_a_scored_business_failure(tmp_path):
    export_evidence(
        tmp_path,
        {
            "case_index": 0,
            "task_id": "CONTRACT_TEST_ONLY",
            "run": {"status": "PARTIAL"},
            "ledger": {
                "halted": "PROVIDER_USAGE_UNKNOWN",
                "attempts": [{"state": "STOPPED", "usage": "UNKNOWN", "held_cny": "2.113536"}],
            },
        },
    )
    result = scorer().score_verified(tmp_path)
    assert result["status"] == "NOT_SCORED"
    assert result["usage_state"] == "UNKNOWN"
    assert result["held_upper_cny"] == "2.113536"
