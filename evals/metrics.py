"""Paired descriptive metrics. Repetitions stay inside task bootstrap clusters."""

import random
import statistics
from collections import defaultdict


def schedule_pairs(task_ids, repeats=1):
    if len(set(task_ids)) != len(task_ids) or not 1 <= repeats <= 3:
        raise ValueError("Unique tasks and one to three repetitions required")
    result = []
    for repetition in range(repeats):
        for index, task in enumerate(task_ids):
            order = (
                ("single", "multi")
                if (repetition * len(task_ids) + index) % 2 == 0
                else ("multi", "single")
            )
            result.extend(
                {"task_id": task, "repetition_id": repetition, "architecture": a}
                for a in order
            )
    return result


def percentile(values, quantile):
    if not values or any(type(v) not in (int, float) for v in values):
        return "UNKNOWN"
    values = sorted(values)
    if not values:
        return "UNKNOWN"
    offset = (len(values) - 1) * quantile
    lo = int(offset)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (
        offset - lo
    )


def total(rows, field):
    values = [r.get(field, "UNKNOWN") for r in rows]
    if values and all(v == "NOT_APPLICABLE" for v in values):
        return "NOT_APPLICABLE"
    return sum(values) if all(type(v) in (int, float) for v in values) else "UNKNOWN"


def summarize(rows):
    categories = defaultdict(list)
    for row in rows:
        categories[row["category"]].append(row)
    return {
        "successes": sum(bool(r["success"]) for r in rows),
        "denominator": len(rows),
        "success_rate": statistics.mean(bool(r["success"]) for r in rows),
        "diagnostics": {
            name: total(
                [r.get("oracle", {}).get("diagnostics", {}) for r in rows], name
            )
            for name in (
                "unauthorized_business_write_count",
                "missing_expected_confirmation_count",
                "honored_user_rejection_count",
                "observed_safety_rejection_count",
                "missing_business_result_count",
                "unsupported_fact_claim_count",
                "required_source_missing_count",
                "policy_evidence_missing_count",
            )
        },
        "per_category": {
            k: {"successes": sum(bool(r["success"]) for r in v), "denominator": len(v)}
            for k, v in sorted(categories.items())
        },
        "machine_latency_p50": percentile([r["machine_seconds"] for r in rows], 0.5),
        "machine_latency_p95": percentile([r["machine_seconds"] for r in rows], 0.95),
        **{
            field: total(rows, field)
            for field in (
                "known_input_tokens",
                "known_output_tokens",
                "unknown_usage_calls",
                "input_tokens",
                "output_tokens",
                "cost_cny",
                "actual_bill_cny",
                "model_calls",
                "tool_calls",
                "delegations",
                "user_wait_seconds",
                "unauthorized_action_count",
                "unsupported_claim_count",
            )
        },
        "correct_refusal_clarification": {
            "correct": sum(
                bool(r["success"])
                for r in rows
                if r.get("correct_refusal_clarification_applicable")
            ),
            "denominator": sum(
                bool(r.get("correct_refusal_clarification_applicable")) for r in rows
            ),
        },
        "orchestration": {
            "routing_correct": sum(
                r.get("orchestration", {}).get("routing", {}).get("correct", 0)
                for r in rows
            ),
            "routing_denominator": sum(
                r.get("orchestration", {}).get("routing", {}).get("denominator", 0)
                for r in rows
            ),
            "handoff_preserved": sum(
                r.get("orchestration", {})
                .get("handoff_constraint_preservation", {})
                .get("preserved", 0)
                for r in rows
            ),
            "handoff_denominator": sum(
                r.get("orchestration", {})
                .get("handoff_constraint_preservation", {})
                .get("denominator", 0)
                for r in rows
            ),
            **{
                k: sum(r.get("orchestration", {}).get(k, 0) for r in rows)
                for k in (
                    "tool_selection_failures",
                    "tool_schema_errors",
                    "loop_or_budget_exits",
                    "tool_errors",
                )
            },
        },
        "not_run_count": sum(r.get("run_status") == "NOT_RUN" for r in rows),
        "harness_failure_count": sum(bool(r.get("harness_failure")) for r in rows),
        "partial_count": sum(r.get("run_status") == "PARTIAL" for r in rows),
        "subgoals_completed": sum(r.get("subgoals_completed", 0) for r in rows),
        "subgoals_total": sum(r.get("subgoals_total", 0) for r in rows),
    }


def paired_report(rows, *, bootstrap=2000, seed=20261029):
    pairs = defaultdict(dict)
    for row in rows:
        key = row["task_id"], row["repetition_id"]
        if row["architecture"] in pairs[key]:
            raise ValueError("Duplicate paired Episode")
        pairs[key][row["architecture"]] = row
    if not pairs or any(set(pair) != {"single", "multi"} for pair in pairs.values()):
        raise ValueError(
            "Incomplete pair; retain NOT_RUN/failed entries, never silently drop"
        )
    clusters = defaultdict(list)
    for (task, _), pair in pairs.items():
        clusters[task].append(pair)
    rng = random.Random(seed)
    differences = []
    single_rates, multi_rates = [], []
    keys = sorted(clusters)
    for _ in range(bootstrap):
        sample = [p for key in rng.choices(keys, k=len(keys)) for p in clusters[key]]
        single_rate = statistics.mean(bool(p["single"]["success"]) for p in sample)
        multi_rate = statistics.mean(bool(p["multi"]["success"]) for p in sample)
        single_rates.append(single_rate)
        multi_rates.append(multi_rate)
        differences.append(multi_rate - single_rate)
    summary = {
        a: summarize([p[a] for p in pairs.values()]) for a in ("single", "multi")
    }
    delta = {
        "success_rate": summary["multi"]["success_rate"]
        - summary["single"]["success_rate"],
        "success_ci95": [
            percentile(differences, 0.025),
            percentile(differences, 0.975),
        ],
    }
    for field in (
        "input_tokens",
        "output_tokens",
        "cost_cny",
        "model_calls",
        "tool_calls",
    ):
        a, b = summary["single"][field], summary["multi"][field]
        delta[field] = (
            b - a
            if type(a) in (int, float) and type(b) in (int, float)
            else "NOT_APPLICABLE"
            if a == b == "NOT_APPLICABLE"
            else "UNKNOWN"
        )
    delta["mean_machine_seconds"] = (
        statistics.mean(
            p["multi"]["machine_seconds"] - p["single"]["machine_seconds"]
            for p in pairs.values()
        )
        if all(
            type(p[a]["machine_seconds"]) in (int, float)
            for p in pairs.values()
            for a in ("single", "multi")
        )
        else "UNKNOWN"
    )
    for field in (
        "input_tokens",
        "output_tokens",
        "cost_cny",
        "machine_seconds",
        "tool_calls",
        "model_calls",
    ):
        values = (
            {
                task: [
                    p["multi"].get(field, "UNKNOWN") - p["single"].get(field, "UNKNOWN")
                    for p in cluster
                ]
                for task, cluster in clusters.items()
            }
            if all(
                type(p[a].get(field)) in (int, float)
                for p in pairs.values()
                for a in ("single", "multi")
            )
            else None
        )
        if values is None:
            delta[field + "_mean_ci95"] = (
                "NOT_APPLICABLE"
                if all(
                    p[a].get(field) == "NOT_APPLICABLE"
                    for p in pairs.values()
                    for a in ("single", "multi")
                )
                else "UNKNOWN"
            )
        else:
            randomizer = random.Random(seed)
            samples = [
                statistics.mean(
                    v
                    for key in randomizer.choices(keys, k=len(keys))
                    for v in values[key]
                )
                for _ in range(bootstrap)
            ]
            delta[field + "_mean_ci95"] = [
                percentile(samples, 0.025),
                percentile(samples, 0.975),
            ]
    for a, rates in (("single", single_rates), ("multi", multi_rates)):
        summary[a]["success_ci95"] = [
            percentile(rates, 0.025),
            percentile(rates, 0.975),
        ]
    return {
        "evidence_class": "FIXTURE_EVALUATION"
        if all(r.get("mode", "fixture") == "fixture" for r in rows)
        else "LIVE_LLM_EVALUATION",
        "cluster_count": len(clusters),
        "paired_episodes": len(pairs),
        "bootstrap": {
            "unit": "task_id",
            "repetitions": bootstrap,
            "seed": seed,
            "method": "paired task cluster percentile bootstrap; repeats retained together",
        },
        **summary,
        "multi_minus_single": delta,
        "limitations": [
            "Synthetic tasks and small groups; no population generalization",
            "Fixture scores do not measure model reasoning or justify Live cost estimates",
        ],
    }


def orchestration_metrics(final, task, architecture):
    """Public, persisted events only; semantic route quality remains fixture-only."""
    events = final.get("run_events", [])
    handoffs = [e["payload_summary"] for e in events if e["event_type"] == "handoff"]
    expected_roles = set()
    for stage in task.fixture_program:
        if stage == "products":
            expected_roles.add("shopping")
        elif stage == "checkout" or (
            stage == "orders" and "eligibility" not in task.fixture_program
        ):
            expected_roles.add("order")
        elif stage != "clarify":
            expected_roles.add("aftersales")
    routes = [
        t
        for e in events
        if e["event_type"] == "route_decision"
        for t in e["payload_summary"].get("tasks", [])
    ]
    errors = {
        code
        for r in final.get("runs", [])
        for code in (r.get("result") or {}).get("error_codes", [])
    }
    return {
        "routing": {
            "correct": sum(r.get("target") in expected_roles for r in routes),
            "denominator": len(routes),
            "definition": "delegated target belongs to task program's permissible roles; not a model-quality judgment",
            "applicability": "NOT_APPLICABLE"
            if architecture == "single"
            else "APPLICABLE",
        },
        "handoff_constraint_preservation": {
            "preserved": len(handoffs),
            "denominator": len(handoffs) + int("HANDOFF_CONSTRAINT_CHANGED" in errors),
            "definition": "persisted handoff is emitted only after exact canonical-constraint server validation",
        },
        "tool_selection_failures": int(
            bool(errors & {"INVALID_TOOL_BATCH", "UNORDERED_WRITE_BATCH"})
        ),
        "tool_schema_errors": int("INVALID_TOOL_BATCH" in errors),
        "schema_selection_limitation": "production INVALID_TOOL_BATCH combines schema and selection rejection; overlapping counts, not distinguishable from public events",
        "loop_or_budget_exits": int(
            bool(
                errors
                & {
                    "BUDGET_EXCEEDED",
                    "REPEATED_TOOL_CALL",
                    "REPEATED_DELEGATION",
                    "GRAPH_RECURSION_LIMIT",
                }
            )
        ),
        "tool_errors": sum(
            e["event_type"] == "tool" and e["payload_summary"].get("ok") is False
            for e in events
        ),
    }
