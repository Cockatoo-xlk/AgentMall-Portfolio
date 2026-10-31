import pytest
from evals.retrieval import metrics


def test_metrics_exclude_no_answer_from_recall_and_keep_full_relevant_denominator():
    rows = [
        {
            "relevant_ids": ["a", "b"],
            "result_ids": ["x", "a"],
            "latency_ms": 1,
            "error": None,
            "expected_error": None,
            "violations": 0,
            "citation_resolved": 2,
        },
        {
            "relevant_ids": [],
            "result_ids": [],
            "latency_ms": 3,
            "error": None,
            "expected_error": None,
            "violations": 0,
            "citation_resolved": 0,
        },
        {
            "relevant_ids": ["z"],
            "result_ids": [],
            "latency_ms": 2,
            "error": None,
            "expected_error": None,
            "violations": 0,
            "citation_resolved": 0,
        },
    ]
    result = metrics(rows)
    assert result["recall_at_5"] == pytest.approx(0.25)
    assert result["mrr_at_5"] == pytest.approx(0.25)
    assert result["no_answer_correct"] == 1
    assert result["answer_queries"] == 2 and result["no_answer_queries"] == 1
