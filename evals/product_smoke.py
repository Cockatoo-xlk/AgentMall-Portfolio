"""Static product-smoke proposal validation and binding, never an execution entry point.

No credentials, model, HTTP client, database or old L8 task loader is imported.
A binding is a self-authored preregistration receipt, not Live authorization.
"""

import argparse
import hashlib
import json
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

LIMITS = {
    "http": 12,
    "models": 12,
    "tools": 16,
    "delegations": 4,
    "steps": 24,
    "input_tokens": 3145728,
    "output_tokens": 12000,
    "episode_seconds": 90,
    "outer_seconds": 300,
}
RULES = {
    "retry": False,
    "recover": False,
    "auto_approve": False,
    "unknown_stops_batch": True,
    "waiting_counts_toward_episode": True,
    "fresh_environment_per_task": True,
}


def validate_proposal(value):
    if not isinstance(value, dict) or (
        value.get("purpose") != "EXPLORATORY_PRODUCT_SMOKE"
        or value.get("live_authorization") != "NONE"
        or type(value.get("independent_holdout_count")) is not int
        or value["independent_holdout_count"] != 0
    ):
        raise ValueError("EXPLORATORY_UNAUTHORIZED_PROPOSAL_REQUIRED")
    model = value.get("model")
    if (
        not isinstance(model, dict)
        or type(model.get("temperature")) not in {int, float}
        or model
        != {
            "name": "deepseek-flash",
            "thinking": {"type": "disabled"},
            "temperature": 0,
        }
    ):
        raise ValueError("MODEL_CONFIGURATION_INVALID")
    limits = value.get("limits", {})
    if not isinstance(limits, dict) or any(
        type(limits.get(k)) is not int or not 0 < limits[k] <= cap
        for k, cap in LIMITS.items()
    ):
        raise ValueError("BUDGET_INVALID")
    try:
        task = Decimal(limits["task_cost_cny"])
        batch = Decimal(limits["batch_cost_cny"])
        if not (
            task.is_finite()
            and batch.is_finite()
            and 0 < task <= Decimal("2.50")
            and 0 < batch <= Decimal("7.50")
            and batch <= task * 3
        ):
            raise ValueError("BUDGET_INVALID")
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise ValueError("BUDGET_INVALID") from exc
    rules = value.get("rules", {})
    if not isinstance(rules, dict) or any(
        rules.get(k) is not v for k, v in RULES.items()
    ):
        raise ValueError("HITL_CLOCK_OR_STOP_RULE_INVALID")
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 3:
        raise ValueError("THREE_ORDERED_TASKS_REQUIRED")
    identifiers = set()
    for item, architecture, decisions in zip(
        tasks, ("single", "single", "multi"), (0, 1, 2), strict=True
    ):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item["id"])
            or item["id"] in identifiers
            or item.get("architecture") != architecture
            or type(item.get("required_human_decisions")) is not int
            or item["required_human_decisions"] != decisions
            or not isinstance(item.get("user_request"), str)
            or not item["user_request"].strip()
            or not isinstance(item.get("fixture"), dict)
            or not item["fixture"]
            or not isinstance(item.get("assertions"), list)
            or not item["assertions"]
            or any(not isinstance(a, str) or not a.strip() for a in item["assertions"])
        ):
            raise ValueError("TASK_FIXTURE_ASSERTIONS_OR_HITL_INVALID")
        identifiers.add(item["id"])
    # Return a detached snapshot; a caller cannot mutate the validated original by alias.
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def freeze_proposal(path, *, source_commit, source_tree):
    if any(
        not isinstance(x, str) or not re.fullmatch(r"[a-f0-9]{40}", x)
        for x in (source_commit, source_tree)
    ):
        raise ValueError("EXACT_SOURCE_COMMIT_AND_TREE_REQUIRED")
    raw = Path(path).read_bytes()
    value = validate_proposal(json.loads(raw))
    return {
        "purpose": value["purpose"],
        "live_authorization": "NONE",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "proposal_sha256": hashlib.sha256(raw).hexdigest(),
        "task_order": [item["id"] for item in value["tasks"]],
        "episodes_started": 0,
        "provider_requests": 0,
        "key_reads": 0,
        "source_identity_kind": "LOCAL_GIT_COMMIT_NOT_RELEASE",
    }


def agent_input(value, task_id):
    """Public execution input only. Host fixture and scoring fields never cross this projection.

    A host-created order reference, if required by the user message, must be resolved
    and verified against this task's setup receipt before invoking the formal API.
    This function never performs that setup or an API request.
    """
    value = validate_proposal(value)
    for task in value["tasks"]:
        if task["id"] == task_id:
            return {"mode": task["architecture"], "message": task["user_request"]}
    raise ValueError("TASK_NOT_IN_FROZEN_ORDER")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("validate", "freeze"))
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_proposal(json.loads(args.proposal.read_bytes()))
    result = {"state": "STATIC_PROPOSAL_VALID", "live_authorization": "NONE"}
    if args.operation == "freeze":
        if subprocess.check_output(["git", "status", "--porcelain=v1"]).strip():
            raise ValueError("CLEAN_SOURCE_REQUIRED_BEFORE_FREEZE")
        commit, tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD", "HEAD^{tree}"], text=True
        ).splitlines()
        result = freeze_proposal(args.proposal, source_commit=commit, source_tree=tree)
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
