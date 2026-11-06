"""Export a public, read-only projection of a scheduled evaluation directory."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path

from evals.metrics import paired_report, total
from evals.oracles import EFFECT_TABLES
from evals.report import scheduled_rows
from evals.schema import DEV_COUNTS

UNKNOWN = "UNKNOWN"
NA = "NOT_APPLICABLE"
STATUSES = {"RUNNING", "WAITING_INPUT", "COMPLETED", "PARTIAL", "FAILED", "NOT_RUN"}
LABELS = {
    "AUTHORIZATION",
    "BUSINESS_RULE",
    "CONFIRMATION",
    "GROUNDING",
    "IDEMPOTENCY",
    "MODEL_TOOL_SELECTION",
    "RECOVERY_CHECKPOINT",
    "RETRIEVAL",
    "ROUTING_HANDOFF",
    "ORACLE_OR_FIXTURE",
    "PROVIDER_ENVIRONMENT",
}
RULES = frozenset(
    [
        "CANDIDATE_BUDGET",
        "CANDIDATE_CATEGORY",
        "CANDIDATE_COUNT",
        "CANDIDATE_ORIGINAL_EXCLUSION",
        "CANDIDATE_REQUIREMENT_LOST",
        "COMMITTED_RESULT_MISSING",
        "CROSS_TENANT_RESOURCE",
        "DECLARED_DECISION_MISSING",
        "DUPLICATE_BUSINESS_EFFECT",
        "FABRICATED_CITATION",
        "FABRICATED_RECEIPT",
        "FALSE_REFUND_CLAIM",
        "FALSE_RESOURCE_FACT",
        "INTERNAL_OR_FOREIGN_CITATION",
        "INVENTORY_CONSERVATION_NO_REFUND_RESTOCK",
        "INVENTORY_INCREASE",
        "MISSING_ACTION_RECEIPT",
        "ORIGINAL_NOT_EXCLUDED",
        "ORIGINAL_ORDER_STATE",
        "OUTPUT_STATE",
        "OVER_BUDGET",
        "POLICY_EVIDENCE_MISSING",
        "POLICY_VERSION_MISMATCH",
        "PRIVATE_CONTENT_IN_RESULT",
        "PRIVATE_FACT",
        "PRIVATE_IDENTIFIER_IN_RESULT",
        "PRIVATE_OR_INACTIVE_CANDIDATE",
        "PRIVATE_RESULT_REFERENCE",
        "REQUIRED_SOURCE_MISSING",
        "REQUIREMENT_LOST",
        "RESOURCE_DELTA",
        "RUN_STATE",
        "UNAUTHORIZED_REFUND",
        "UNAVAILABLE_CANDIDATE",
        "UNCONFIRMED_COMMIT",
        "UNEXPECTED_ERROR",
        "UNSCRIPTED_APPROVAL",
        "UNSUPPORTED_REFUND_CLAIM",
        "WRONG_ATTRIBUTES",
        "WRONG_BUSINESS_STATE",
        "WRONG_CATEGORY",
        "WRONG_ITEM_COUNT",
        "WRONG_PRICE",
        "WRONG_PRODUCT",
        "WRONG_QUANTITY",
        "WRONG_TOTAL",
        "EPISODE_HARNESS_FAILED",
        "INITIAL_STATE_MISMATCH",
        "PLANNED_EPISODE_NOT_RUN",
        "START_FAILED",
        "RUN_NOT_READABLE",
        "RECOVER_FAILED",
        "UNEXPECTED_CLARIFICATION",
        "PROPOSAL_NOT_READABLE",
        "INTERRUPT_IDENTITY_CHANGED",
        "UNEXPECTED_CONFIRMATION",
        "USER_QUANTITY_MISMATCH",
        "USER_BUDGET_MISMATCH",
        "CONFIRMATION_FAILED",
        "RESUME_FAILED",
        "REPLAY_IDENTITY_MISMATCH",
        "USER_SCRIPT_LIMIT",
        "SCRIPTED_ACTION_FAILED",
        "SCRIPTED_REPLAY_MISMATCH",
        "MERCHANT_REVIEW_FAILED",
        "MERCHANT_RECEIVE_FAILED",
        "SCRIPTED_AFTERSALES_FAILED",
        "SCRIPTED_TICKET_FAILED",
        "UNDECLARED_SCRIPTED_ACTION",
        "EPISODE_TIME_BUDGET_EXCEEDED",
        "BUSINESS_EVENT_UNIQUE",
        "VALIDATED_CONSTRAINTS",
        "STOCK_CHECK",
        "RESERVATION_MISMATCH",
        "ORDER_SCOPE",
        "ORDER_TOTAL",
        "PAYMENT_ORDER_STATE",
        "ORDER_CREATED_EVENT",
        "ITEM_SCOPE",
        "PAYMENT_AMOUNT_SCOPE",
        "CASE_SCOPE",
        "REFUND_AMOUNT_STATE_SCOPE",
        "REFUND_EVENT_MISSING",
        "RUN_EVENT_SEQUENCE",
        "REFUNDED_CASE_RECEIPT",
        "TICKET_SCOPE",
        "COMPLETED_CONFIRMATION_RECEIPT",
        "CONSUMED_CONFIRMATION_RESULT",
        "RECEIPT_COMPLETE",
        "COMPLETED_RUN_METADATA",
        "COMPLETED_RUN_RESULT_MISSING",
        "RUN_COMMITTED_RECEIPT_MISSING",
        "RUN_RESULT_READABLE",
        "UNIQUE_orders_proposal_id",
        "UNIQUE_aftersales_cases_proposal_id",
        "UNIQUE_payments_order_id",
        "UNIQUE_payments_action_id",
        "UNIQUE_refunds_payment_id",
        "UNIQUE_refunds_case_id",
        "UNIQUE_refunds_action_id",
        "UNIQUE_idempotency_requests_action_id",
    ]
)
SUMMARY_FIELDS = (
    "successes",
    "denominator",
    "success_rate",
    "success_ci95",
    "per_category",
    "machine_latency_p50",
    "machine_latency_p95",
    "model_calls",
    "tool_calls",
    "actual_bill_cny",
    "input_tokens",
    "output_tokens",
    "partial_count",
    "not_run_count",
    "harness_failure_count",
    "diagnostics",
)


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else UNKNOWN


def measure(value):
    if type(value) in (int, float) and isfinite(value) and value >= 0:
        return value
    return NA if value == NA else UNKNOWN


def digest(value, size=64):
    return value if matches(value, rf"[0-9a-f]{{{size}}}") else UNKNOWN


def timestamp(value):
    if not matches(
        value, r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)"
    ):
        return UNKNOWN
    try:
        return datetime.fromisoformat(value).astimezone(UTC).isoformat()
    except ValueError:
        return UNKNOWN


def run_metadata(directory, schedule):
    path = directory / "studio-provenance.json"
    recorded = json.loads(path.read_text()) if path.is_file() else {}
    environment = recorded.get("environment", {})
    manifest = schedule.get("manifest_sha256")
    return {
        "run_id": directory.name,
        "git_commit": digest(recorded.get("git_commit"), 40),
        "dataset_sha256": digest(schedule.get("dataset_sha256")),
        "manifest_sha256": "UNFROZEN" if manifest == "UNFROZEN" else digest(manifest),
        "started_at": timestamp(recorded.get("started_at")),
        "completed_at": timestamp(recorded.get("completed_at")),
        "environment": {
            "os": enum(environment.get("os"), {"Linux", "Darwin", "Windows"}),
            "architecture": enum(
                environment.get("architecture"), {"aarch64", "arm64", "x86_64", "AMD64"}
            ),
            **{
                field: environment[field]
                if matches(environment.get(field), r"\d{1,3}(?:\.\d{1,3}){1,2}")
                else UNKNOWN
                for field in ("python", "postgresql")
            },
        },
    }


def business_effects(row):
    def ids(snapshot, table):
        items = snapshot.get(table)
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str)
            for item in items
        ):
            return None
        return {item["id"] for item in items}

    effects = {}
    for table in EFFECT_TABLES:
        before = ids(row.get("initial", {}), table)
        after = ids(row.get("final", {}), table)
        effects[table] = (
            len(after - before) if before is not None and after is not None else UNKNOWN
        )
    return effects


def public_episode(row):
    oracle = row.get("oracle", {})
    violations = oracle.get("violations", [])
    labels = [enum(v.get("label"), LABELS) for v in violations]
    return {
        **{
            k: row[k]
            for k in ("task_id", "repetition_id", "architecture", "category", "success")
        },
        "run_status": enum(row.get("run_status"), STATUSES),
        "oracle_rules": list(
            dict.fromkeys(enum(v.get("rule"), RULES) for v in violations)
        ),
        "error_class": enum((oracle.get("failure") or {}).get("primary"), LABELS)
        if oracle.get("failure")
        else labels[0]
        if labels
        else NA
        if row["success"]
        else UNKNOWN,
        "machine_seconds": measure(row.get("machine_seconds")),
        "model_calls": measure(row.get("model_calls")),
        "tool_calls": measure(row.get("tool_calls")),
        "business_effects": business_effects(row),
        "observed_safety_rejections": measure(
            oracle.get("diagnostics", {}).get("observed_safety_rejection_count")
        ),
    }


def historical_summary(path):
    raw = path.read_bytes()
    source = json.loads(raw)
    second = source["second"]
    known_failure = (
        second.get("failed_episode") == "Multi eval_dev_B2_01"
        and second.get("status") == "PARTIAL / HANDOFF_CONSTRAINT_CHANGED"
    )
    return {
        "evidence_class": "LIVE_LLM_EVALUATION",
        "scope": "HISTORICAL_REVIEWED_AGGREGATE",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "git_commit": UNKNOWN,
        "dataset_sha256": UNKNOWN,
        "actual_bill_cny": UNKNOWN,
        **{
            pilot: {
                field: measure(source[pilot].get(field))
                for field in (
                    "single_success",
                    "multi_success",
                    "tasks_per_architecture",
                    "model_requests",
                )
            }
            for pilot in ("first", "second")
        },
        "reviewed_failure": {
            "task_id": "eval_dev_B2_01",
            "architecture": "multi",
            "run_status": "PARTIAL",
            "error_code": "HANDOFF_CONSTRAINT_CHANGED",
            "business_effects": {"aftersales_cases": 1, "orders": 0}
            if second.get("legal_effect") == "REQUESTED case only, no replacement order"
            else UNKNOWN,
        }
        if known_failure
        else None,
    }


def export_studio(directory, *, historical_live=None):
    if not matches(
        directory.name, r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}"
    ) or directory.name.lower().startswith("sk-"):
        raise ValueError("INVALID_RUN_ID")
    schedule = json.loads((directory / "schedule.json").read_text())
    mode = schedule["mode"]
    if mode not in ("fixture", "live"):
        raise ValueError("INVALID_EVIDENCE_MODE")
    for item in schedule["episodes"]:
        if (
            item["category"] not in DEV_COUNTS
            or not matches(
                item["task_id"], rf"eval_(?:dev|test)_{item['category']}_\d{{2}}"
            )
            or type(item["repetition_id"]) is not int
            or not 0 <= item["repetition_id"] < 3
            or item["architecture"] not in ("single", "multi")
        ):
            raise ValueError("INVALID_EPISODE_IDENTITY")
    rows = scheduled_rows(directory)
    for row, item in zip(rows, schedule["episodes"], strict=True):
        if row.get("mode") != mode or row.get("category") != item["category"]:
            raise ValueError("EPISODE_SCOPE_MISMATCH")
        if (
            row.get("manifest_sha256") is not None
            and schedule.get("manifest_sha256") is not None
            and row["manifest_sha256"] != schedule["manifest_sha256"]
        ):
            raise ValueError("EPISODE_MANIFEST_MISMATCH")
        if type(row.get("success")) is not bool or (
            row.get("run_status") == "NOT_RUN" and row["success"]
        ):
            raise ValueError("INVALID_EPISODE_VERDICT")
        row["machine_seconds"] = measure(row.get("machine_seconds"))
    summary = paired_report(rows)
    comparison = {
        key: summary[key]
        for key in (
            "evidence_class",
            "cluster_count",
            "paired_episodes",
            "bootstrap",
            "multi_minus_single",
        )
    }
    comparison["paid_provider_requests"] = total(rows, "paid_provider_requests")
    for arch in ("single", "multi"):
        comparison[arch] = {field: summary[arch][field] for field in SUMMARY_FIELDS}
    return {
        "version": 1,
        "run": run_metadata(directory, schedule),
        "comparison": comparison,
        "episodes": [public_episode(row) for row in rows],
        "historical_live": historical_summary(historical_live)
        if historical_live
        else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--reviewed-live", type=Path)
    args = parser.parse_args()
    try:
        report = export_studio(args.directory, historical_live=args.reviewed_live)
        output = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Raw paths, input data and exception messages can contain private material.
        parser.exit(2, "Could not export a valid paired evaluation report.\n")
    print(output)
