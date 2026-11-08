import math

import pytest


def test_graded_metrics_keep_all_positive_labels_and_fixed_denominators():
    from evals.retrieval_quality import summarize

    rows = [
        {
            "id": "a",
            "category": "monitor",
            "status": "OK",
            "grades": {"a": 3, "b": 1, "c": 2, "d": 1, "e": 1, "f": 1},
            "result_ids": ["x", "b", "a"],
            "candidate_ids": ["x", "a", "b"],
            "pipeline_ms": 12.0,
            "retrieval_ms": 3.0,
            "rerank_ms": 2.0,
            "embedding_calls": 1,
            "reranker_calls": 1,
            "violations": [],
        },
        {
            "id": "b",
            "category": "phone",
            "status": "OK",
            "grades": {},
            "result_ids": [],
            "candidate_ids": [],
            "pipeline_ms": 8.0,
            "retrieval_ms": 2.0,
            "rerank_ms": None,
            "embedding_calls": 0,
            "reranker_calls": 0,
            "violations": [],
        },
    ]
    result = summarize(rows)
    assert result["planned_queries"] == 2 and result["answer_queries"] == 1
    assert result["recall_at_5"] == pytest.approx(2 / 6)
    assert result["mrr_at_5"] == 0.5 and result["no_answer_accuracy"] == 1
    ideal = 7 + 3 / math.log2(3) + 1 / math.log2(4) + 1 / math.log2(5) + 1 / math.log2(6)
    assert result["ndcg_at_5"] == pytest.approx((1 / math.log2(3) + 7 / math.log2(4)) / ideal)
    assert result["candidate_recall_at_20"] == pytest.approx(2 / 6)
    assert result["latency_p50_ms"] == 10 and result["latency_p95_ms"] == pytest.approx(11.8)


def test_missing_timed_out_rows_are_unknown_not_latency_zero_or_dropped():
    from evals.retrieval_quality import summarize

    row = {
        "id": "a",
        "category": "monitor",
        "status": "TIMEOUT",
        "grades": {"x": 3},
        "result_ids": None,
        "candidate_ids": None,
        "pipeline_ms": None,
        "retrieval_ms": None,
        "rerank_ms": None,
        "embedding_calls": None,
        "reranker_calls": None,
        "violations": [],
    }
    result = summarize([row])
    assert result["planned_queries"] == 1 and result["completed_queries"] == 0
    assert (
        result["recall_at_5"] is None
        and result["latency_p50_ms"] is None
        and result["model_calls_mean"] is None
    )


def test_frozen_expanded_labels_have_both_splits_and_explicit_single_annotator():
    from evals.expanded_retrieval import load_dataset

    manifest, datasets = load_dataset()
    assert manifest["annotation"].startswith("SINGLE_ANNOTATOR")
    assert set(datasets) == {"dev", "test"} and all(len(rows) == 20 for rows in datasets.values())
    assert (
        len({r["category"] for rows in datasets.values() for r in rows} - {"cross_category"}) == 13
    )
    assert all(
        j["rationale"] for rows in datasets.values() for row in rows for j in row["judgments"]
    )
