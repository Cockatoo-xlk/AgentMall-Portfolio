"""Optional allowlisted diagnostics. Never an Oracle, prompt archive or authorization."""

import hashlib
import json
import os
import stat
from pathlib import Path
from uuid import UUID

from agentmall.infra.observability import identifier, public_summary

COUNTERS = ("models", "tools", "delegations", "steps", "output_tokens")
ORCHESTRATION = {
    "INCOMPLETE_WRITE_GOAL",
    "INCOMPLETE_PURCHASE",
    "REPEATED_DELEGATION",
    "DEPENDENCY_NOT_READY",
    "RETURN_DECISION_REQUIRED",
    "HANDOFF_CONSTRAINT_CHANGED",
    "UNORDERED_WRITE_HANDOFF",
    "HANDOFF_WRITE_SCOPE_CHANGED",
}
ENVIRONMENT = {
    "DATABASE_UNAVAILABLE",
    "DATABASE_SCOPE_MISMATCH",
    "EXECUTION_OWNER_UNAVAILABLE",
}


def known_code(value):
    return (
        value
        if isinstance(value, str) and value.isupper() and identifier(value)
        else "UNKNOWN"
    )


def project(episode):
    result = episode.get("result") or {}
    codes = [known_code(c) for c in result.get("error_codes", [])][:40]
    budget = episode.get("graph_budget") or {}
    counters = {
        k: budget[k] if type(budget.get(k)) is int and budget[k] >= 0 else "UNKNOWN"
        for k in COUNTERS
    }
    rows = (episode.get("final") or {}).get("run_events")
    events = []
    if isinstance(rows, list):
        for row in rows[:2000]:
            kind = identifier(row.get("event_type"))
            seq = row.get("seq")
            if kind and type(seq) is int and seq > 0:
                events.append(
                    {
                        "seq": seq,
                        "event_type": kind,
                        "payload_summary": public_summary(
                            kind, row.get("payload_summary") or {}
                        ),
                    }
                )
    final = episode.get("final") or {}
    initial = episode.get("initial") or {}
    baseline = {c.get("id") for c in initial.get("confirmations", [])}
    proposals = {
        p.get("id"): p.get("action_type") for p in final.get("action_proposals", [])
    }
    confirmations = final.get("confirmations")
    if isinstance(confirmations, list):
        confirmations = [
            {
                "action_type": proposals.get(c.get("proposal_id"))
                if proposals.get(c.get("proposal_id"))
                in {"CHECKOUT", "RETURN_REQUEST", "MOCK_PAYMENT", "MOCK_REFUND"}
                else "UNKNOWN",
                "scope": "INITIAL_SETUP"
                if c.get("id") in baseline
                else "AGENT_EPISODE"
                if "confirmations" in initial
                else "UNKNOWN",
                "decision": c.get("decision")
                if c.get("decision") in {"approve", "reject"}
                else "UNKNOWN",
                "consumed": bool(c["consumed_at"]) if "consumed_at" in c else "UNKNOWN",
                "has_result": bool(c["result_ref"]) if "result_ref" in c else "UNKNOWN",
            }
            for c in confirmations[:40]
        ]
    else:
        confirmations = "UNKNOWN"
    diagnostic_counts = (episode.get("oracle") or {}).get("diagnostics") or {}
    return {
        "schema_version": 1,
        "task_id": identifier(episode.get("task_id")) or "UNKNOWN",
        "architecture": episode.get("architecture")
        if episode.get("architecture") in {"single", "multi"}
        else "UNKNOWN",
        "evidence_class": episode.get("evidence_class")
        if episode.get("evidence_class")
        in {"FIXTURE_EVALUATION", "LIVE_LLM_EVALUATION"}
        else "UNKNOWN",
        "run_status": known_code(episode.get("run_status")),
        "error_codes": codes,
        "budget": counters,
        "events": events,
        "events_present": isinstance(rows, list),
        "events_truncated": isinstance(rows, list) and len(rows) > 2000,
        "confirmations": confirmations,
        "oracle_diagnostics": {
            k: diagnostic_counts[k]
            if type(diagnostic_counts.get(k)) is int and diagnostic_counts[k] >= 0
            else "UNKNOWN"
            for k in (
                "unauthorized_business_write_count",
                "missing_expected_confirmation_count",
                "missing_business_result_count",
                "unsupported_fact_claim_count",
                "required_source_missing_count",
                "observed_safety_rejection_count",
            )
        },
        "failure_class": "ENVIRONMENT"
        if set(codes) & ENVIRONMENT
        else "ORCHESTRATION"
        if set(codes) & ORCHESTRATION
        else "MODEL_OUTPUT_OR_SELECTION"
        if set(codes)
        & {
            "INVALID_ROUTE",
            "INVALID_TOOL_BATCH",
            "MODEL_PROTOCOL_ERROR",
            "MODEL_USAGE_INVALID",
        }
        else "TOOL_OR_DOMAIN"
        if set(codes)
        & {
            "TOOL_FAILED",
            "STALE_PROPOSAL",
            "INSUFFICIENT_STOCK",
            "NOT_FOUND",
            "CONSTRAINT_MISMATCH",
        }
        else "RESOURCE_LIMIT"
        if "BUDGET_EXCEEDED" in codes
        else "UNKNOWN"
        if codes or not result
        else "NO_REPORTED_ERROR",
        "classification_scope": "Observed error-code family, not proof of historical root cause.",
    }


def write_diagnostic(episode, directory):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("DIAGNOSTIC_PATH_UNSAFE")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
        raise ValueError("DIAGNOSTIC_DIRECTORY_MUST_BE_OWNER_ONLY")
    try:
        ident = str(UUID(str(episode.get("run_id"))))
    except (ValueError, TypeError):
        ident = hashlib.sha256(
            json.dumps(project(episode), sort_keys=True).encode()
        ).hexdigest()
    path = directory / (ident + ".json")
    data = (json.dumps(project(episode), ensure_ascii=False, indent=2) + "\n").encode()
    if len(data) > 1_048_576:
        raise ValueError("DIAGNOSTIC_TOO_LARGE")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    return path
