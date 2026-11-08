"""Graded retrieval metrics; null is unknown, and failures never disappear from the plan."""

import math
import statistics

from evals.metrics import percentile


def dcg(grades):
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def per_query(row):
    if row["status"] != "OK" or row.get("result_ids") is None:
        return {
            "recall_at_5": None,
            "mrr_at_5": None,
            "ndcg_at_5": None,
            "candidate_recall_at_20": None,
            "candidate_ndcg_ceiling_at_5": None,
        }
    labels = row["grades"]
    positive = {k: v for k, v in labels.items() if v > 0}
    if not positive:
        return {
            k: None
            for k in [
                "recall_at_5",
                "mrr_at_5",
                "ndcg_at_5",
                "candidate_recall_at_20",
                "candidate_ndcg_ceiling_at_5",
            ]
        }
    ids = row["result_ids"][:5]
    pool = row["candidate_ids"] or []
    ideal = dcg(sorted(positive.values(), reverse=True)[:5])
    return {
        "recall_at_5": len(set(ids) & positive.keys()) / len(positive),
        "mrr_at_5": next((1 / (i + 1) for i, x in enumerate(ids) if x in positive), 0),
        "ndcg_at_5": dcg([positive.get(x, 0) for x in ids]) / ideal,
        "candidate_recall_at_20": len(set(pool) & positive.keys()) / len(positive),
        "candidate_ndcg_ceiling_at_5": dcg(
            sorted([positive.get(x, 0) for x in pool], reverse=True)[:5]
        )
        / ideal,
    }


def summarize(rows):
    answers = [r for r in rows if r["grades"]]
    empty = [r for r in rows if not r["grades"]]
    ok = [r for r in rows if r["status"] == "OK"]
    all_ok = len(ok) == len(rows)
    scores = [per_query(r) for r in answers]

    def mean(key):
        values = [s[key] for s in scores]
        return (
            statistics.mean(values)
            if values and all(v is not None for v in values)
            else None
        )

    def latency(q):
        values = [r.get("pipeline_ms") for r in rows]
        return (
            percentile(values, q)
            if values and all(type(v) in (int, float) for v in values)
            else None
        )

    ranks = [r["rerank_ms"] for r in ok if type(r.get("rerank_ms")) in (int, float)]
    calls = (
        [r.get("embedding_calls", 0) + r.get("reranker_calls", 0) for r in rows]
        if all_ok
        and all(
            type(r.get(k)) is int
            for r in rows
            for k in ["embedding_calls", "reranker_calls"]
        )
        else []
    )
    return {
        "planned_queries": len(rows),
        "completed_queries": len(ok),
        "answer_queries": len(answers),
        "no_answer_queries": len(empty),
        **{
            k: mean(k)
            for k in [
                "recall_at_5",
                "mrr_at_5",
                "ndcg_at_5",
                "candidate_recall_at_20",
                "candidate_ndcg_ceiling_at_5",
            ]
        },
        "no_answer_accuracy": statistics.mean(not r["result_ids"] for r in empty)
        if empty and all(r["status"] == "OK" for r in empty)
        else None,
        "latency_p50_ms": latency(0.5),
        "latency_p95_ms": latency(0.95),
        "rerank_mean_ms": statistics.mean(ranks) if ranks else None,
        "rerank_timed_queries": len(ranks),
        "model_calls_mean": statistics.mean(calls) if calls else None,
        "illegal_result_count": sum(len(r.get("violations", [])) for r in rows)
        if all_ok
        else None,
        "stale_index_leak_count": sum(
            sum(v.startswith("STALE") for v in r.get("violations", [])) for r in rows
        )
        if all_ok
        else None,
        "execution_errors": len(rows) - len(ok),
    }


def category_metrics(rows):
    return {
        category: summarize([r for r in rows if r["category"] == category])
        for category in sorted({r["category"] for r in rows})
    }
