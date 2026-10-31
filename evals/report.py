"""Readable reports from preserved paired rows; no generated model-quality conclusions."""

import argparse
import json
from pathlib import Path

from evals.metrics import paired_report


def write_report(destination, rows, summary):
    lines = [
        f"# {summary['evidence_class']}",
        "",
        "Fixture tests verify evaluation plumbing and business safety. They do not measure LLM reasoning or predict Live cost.",
        "",
        "| Metric | Single | Multi |",
        "|---|---:|---:|",
    ]
    for key in (
        "successes",
        "denominator",
        "success_rate",
        "success_ci95",
        "subgoals_completed",
        "subgoals_total",
        "input_tokens",
        "output_tokens",
        "model_calls",
        "tool_calls",
        "delegations",
        "machine_latency_p50",
        "machine_latency_p95",
        "user_wait_seconds",
        "cost_cny",
        "actual_bill_cny",
        "unauthorized_action_count",
        "unsupported_claim_count",
        "partial_count",
    ):
        lines.append(
            f"| {key} | {summary['single'].get(key, 'UNKNOWN')} | {summary['multi'].get(key, 'UNKNOWN')} |"
        )
    lines += [
        "",
        "## Diagnostic counts (additive; verdicts unchanged)",
        "",
        (
            "Legacy unauthorized_action_count mixes authorization and missing-confirmation violations; "
            "legacy unsupported_claim_count includes missing sources. Neither is a count of proven unlawful writes or false claims."
        ),
        "",
        "| Diagnostic | Single | Multi |",
        "|---|---:|---:|",
    ]
    for name in summary["single"].get("diagnostics", {}):
        lines.append(
            f"| {name} | {summary['single']['diagnostics'][name]} | {summary['multi']['diagnostics'][name]} |"
        )
    lines += [
        "",
        "## Groups",
        "",
        "| Group | Single successes / denominator | Multi successes / denominator |",
        "|---|---:|---:|",
    ]
    for category in summary["single"]["per_category"]:
        values = [summary[a]["per_category"][category] for a in ("single", "multi")]
        lines.append(
            f"| {category} | {values[0]['successes']}/{values[0]['denominator']} | {values[1]['successes']}/{values[1]['denominator']} |"
        )
    lines += [
        "",
        "## Paired differences and orchestration",
        "",
        "Task-cluster percentile bootstrap; all repetitions of a task stay together. The JSON includes all denominators and UNKNOWN values.",
        "",
        "```json",
        json.dumps(
            {
                "multi_minus_single": summary["multi_minus_single"],
                "orchestration": {
                    a: summary[a].get("orchestration") for a in ("single", "multi")
                },
            },
            indent=2,
        ),
        "```",
        "",
        "## Failures (all retained)",
        "",
    ]
    failures = [r for r in rows if not r["success"]]
    if not failures:
        lines.append("No Oracle failures in this recorded pass.")
    for row in failures:
        name = f"{row['task_id']}-{row['repetition_id']}-{row['architecture']}.json"
        lines.append(
            f"- [{name}]({name}): "
            + json.dumps(
                row["oracle"].get("failure") or row["oracle"]["violations"],
                ensure_ascii=False,
            )
        )
    lines += [
        "",
        "## Limits",
        "",
        "- One Codex author; no independent multi-annotator labels.",
        "- Payment, cancellation, delivery, refunds and ticket resolution are declared deterministic scripts, not autonomous Agent capabilities.",
        "- Fixture embeddings are non-semantic unit vectors. Live pilot uses pinned offline local BGE; neither semantic RAG nor real model quality is established by this report.",
        "- Public events collapse tool selection/schema rejection into INVALID_TOOL_BATCH; reported counts overlap.",
        "- Fixed logical business clock; real machine latency. Synthetic user waiting is separated and is not an estimate of human response time.",
        "- Failed/missing usage is UNKNOWN, never estimated as zero; actual billing unavailable in Live. No T12 paid requests were made by the offline phase.",
    ]
    (destination / "report.md").write_text("\n".join(lines) + "\n")


def scheduled_rows(destination):
    plan = json.loads((destination / "schedule.json").read_text())
    rows = []
    for item in plan["episodes"]:
        path = (
            destination
            / f"{item['task_id']}-{item['repetition_id']}-{item['architecture']}.json"
        )
        if path.exists():
            row = json.loads(path.read_text())
            if any(
                row[k] != item[k] for k in ("task_id", "repetition_id", "architecture")
            ):
                raise ValueError("SCHEDULE_IDENTITY_MISMATCH")
        else:
            row = item | {
                "mode": plan["mode"],
                "success": False,
                "run_status": "NOT_RUN",
                "machine_seconds": "UNKNOWN",
                "oracle": {
                    "violations": [
                        {
                            "rule": "PLANNED_EPISODE_NOT_RUN",
                            "label": "PROVIDER_ENVIRONMENT",
                        }
                    ]
                },
            }
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = scheduled_rows(args.directory)
    summary = paired_report(rows)
    write_report(args.directory, rows, summary)


if __name__ == "__main__":
    main()
