"""Reviewed experiment identities; a candidate freeze never grants paid authority."""

import argparse
import json
import os
from copy import deepcopy
from datetime import UTC, datetime

from evals.fixtures import ROOT, settings_for_eval
from evals.provider import BudgetLedger, LivePolicy, ProviderBoundaryError

RETEST_ID = "t12-live-retest-01"
DEFINITION = {
    "version": 1,
    "id": RETEST_ID,
    "authorization_status": "NOT_AUTHORIZED",
    "ledger": "evals/live/t12-live-retest-01-ledger.json",
    "authorization": "evals/live/t12-live-retest-01-authorization.json",
    "results": "evals/results/t12-live-retest-01",
    "parent_manifest_sha256": "15742b3e7e15408e1b1b066b867d29102f0ea7ff34e348e682fc2ad483bc448d",
    "task_ids": [
        "eval_dev_A1_01",
        "eval_dev_A2_01",
        "eval_dev_B1_01",
        "eval_dev_B2_01",
        "eval_dev_B1_03",
    ],
    "split": "dev",
    "repeats": 1,
    "architectures": "single,multi",
    "budget": {"max_model_calls": 100, "max_cost_cny": "5", "max_wall_seconds": 1200},
}


def validate_experiment(data):
    if (
        data.get("version") != 2
        or data.get("experiment") != DEFINITION
        or data.get("live_ledger") != DEFINITION["ledger"]
        or data.get("pilot", {}).get("task_ids") != DEFINITION["task_ids"]
    ):
        raise ProviderBoundaryError("EXPERIMENT_NOT_REGISTERED_OR_CHANGED")


def policy_for(data, manifest_hash):
    validate_experiment(data)
    price = data["provider"]["price_snapshot"]
    return LivePolicy(
        confirm_live=True,
        **DEFINITION["budget"],
        manifest_hash=manifest_hash,
        price_checked_at=price["checked_at_utc"],
        input_cny_per_million=price["peak_input_cache_miss"],
        output_cny_per_million=price["peak_output"],
        price_source=price["sources"][0],
    )


def fixed_path(key):
    path = ROOT / DEFINITION[key]
    if path.resolve() != path or path.is_symlink():
        raise ProviderBoundaryError("EXPERIMENT_PATH_SYMLINK")
    if key == "ledger" and path.with_name(path.name + ".lock").is_symlink():
        raise ProviderBoundaryError("EXPERIMENT_PATH_SYMLINK")
    return path


def binding(manifest_hash):
    return {
        "status": "AUTHORIZED",
        "experiment_id": RETEST_ID,
        "manifest_sha256": manifest_hash,
        "budget": deepcopy(DEFINITION["budget"]),
    }


def read_authorization(manifest_hash):
    path = fixed_path("authorization")
    if not path.exists():
        raise ProviderBoundaryError("LIVE_RETEST_NOT_AUTHORIZED")
    data = json.loads(path.read_text())
    if any(data.get(k) != v for k, v in binding(manifest_hash).items()) or not data.get(
        "approval_reference"
    ):
        raise ProviderBoundaryError("AUTHORIZATION_BINDING_MISMATCH")
    return data


def authorize(path, *, confirm, approval_reference):
    """Operator attestation only after a NEW owner decision; never called by run/freeze."""
    from evals.manifest import validate_manifest

    if confirm is not True or not approval_reference or not approval_reference.strip():
        raise ProviderBoundaryError("LIVE_RETEST_NOT_AUTHORIZED")
    if len(approval_reference) > 500:
        raise ProviderBoundaryError("APPROVAL_REFERENCE_TOO_LONG")
    data, ident = validate_manifest(path)
    policy_for(data, ident)  # includes current price, but does not open a ledger
    target = fixed_path("authorization")
    target.parent.mkdir(parents=True, exist_ok=True)
    record = binding(ident) | {
        "approved_at": datetime.now(UTC).isoformat(),
        "approval_reference": approval_reference.strip(),
        "meaning": "Operator attests separate explicit owner authorization; not inferred from candidate budget",
    }
    try:
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        return read_authorization(
            ident
        )  # same identity only; no timestamp/budget reset
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return record


def open_ledger(data, manifest_hash, args):
    validate_experiment(data)
    if args.run_id != RETEST_ID:
        raise ProviderBoundaryError("EXPERIMENT_RUN_ID_FIXED")
    if (
        args.confirm_live is not True
        or args.pilot is not True
        or args.mode != "live"
        or any(
            getattr(args, k, None) != DEFINITION[k]
            for k in ("split", "repeats", "architectures")
        )
        or any(getattr(args, k, None) != v for k, v in DEFINITION["budget"].items())
    ):
        raise ProviderBoundaryError("EXPERIMENT_FLAGS_OR_BUDGET_MISMATCH")
    settings_for_eval()  # validate exact project DB configuration before any writes/key reads
    policy = policy_for(data, manifest_hash)
    read_authorization(manifest_hash)
    if fixed_path("results").exists():
        raise ProviderBoundaryError("EXPERIMENT_RESULTS_EXIST_RECOVERY_REVIEW_REQUIRED")
    return BudgetLedger(fixed_path("ledger"), policy)


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("authorize",))
    parser.add_argument("--experiment", choices=(RETEST_ID,), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--confirm-authorization", action="store_true")
    parser.add_argument("--approval-reference", required=True)
    args = parser.parse_args()
    record = authorize(
        args.manifest,
        confirm=args.confirm_authorization,
        approval_reference=args.approval_reference,
    )
    print(
        json.dumps(
            {k: record[k] for k in ("experiment_id", "manifest_sha256", "status")}
        )
    )


if __name__ == "__main__":
    main()
