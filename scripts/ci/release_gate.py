"""Bounded public CI outcomes. An uploaded artifact is never workflow success."""

import argparse
import json
import os
import re
from pathlib import Path

CHECKS = {
    "backend": (
        "CHECKOUT",
        "PYTHON",
        "UV",
        "PYTHON_DEPS",
        "BOOTSTRAP",
        "RUFF",
        "FORMAT",
        "PYTEST",
    ),
    "frontend": (
        "CHECKOUT",
        "PYTHON",
        "UV",
        "NODE",
        "PYTHON_DEPS",
        "NODE_DEPS",
        "CHROMIUM",
        "BOOTSTRAP",
        "TYPECHECK",
        "LINT",
        "VITEST",
        "BUILD",
        "PLAYWRIGHT",
    ),
    "gate": ("BACKEND", "FRONTEND"),
}
OUTCOMES = {"success", "failure", "cancelled", "skipped", ""}


def report(suite, environment):
    """Project closed keys only, including malformed metadata without echoing it."""
    sha = environment.get("GITHUB_SHA", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    attempt = environment.get("GITHUB_RUN_ATTEMPT", "")
    valid = bool(re.fullmatch(r"[0-9a-f]{40}", sha))
    ids_valid = bool(re.fullmatch(r"[1-9][0-9]{0,19}", run_id))
    attempt_valid = bool(re.fullmatch(r"[1-9][0-9]{0,5}", attempt))
    checks = {}
    for key in CHECKS[suite]:
        value = environment.get("RESULT_" + key, "")
        checks[key] = value if value in OUTCOMES else "unknown"
    metadata_valid = valid and ids_valid and attempt_valid
    return {
        "schema_version": 1,
        "suite": suite,
        "commit_sha": sha if valid else None,
        "run_id": run_id if ids_valid else None,
        "run_attempt": int(attempt) if attempt_valid else None,
        "checks": checks,
        "checks_passed": metadata_valid
        and all(v == "success" for v in checks.values()),
        "metadata_valid": metadata_valid,
        "model": "FIXTURE_AND_SDK_MOCK_ONLY",
        "real_bge": "NOT_RUN: existing offline-core skips",
        "workflow_conclusion": "NOT_DETERMINED_BY_ARTIFACT",
    }


def enforce(environment):
    """Gate must include its own checkout, report generation and export outcomes."""
    return report("gate", environment)["checks_passed"] and all(
        environment.get("RESULT_" + key) == "success"
        for key in ("CHECKOUT", "SUMMARY", "UPLOAD")
    )


def write(result, directory):
    payload = json.dumps(result, indent=2) + "\n"
    if len(payload.encode()) > 4096:
        raise ValueError("PUBLIC_SUMMARY_TOO_LARGE")
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("PUBLIC_SUMMARY_PATH_INVALID")
    directory.mkdir(exist_ok=True)
    target = directory / (result["suite"] + ".json")
    # Never follow a symlink or overwrite an earlier receipt.
    with target.open("x") as stream:
        stream.write(payload)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(CHECKS), required=True)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if args.enforce:
        if args.suite != "gate":
            raise SystemExit("ENFORCEMENT_REQUIRES_GATE")
        passed = enforce(os.environ)
        text = "RELEASE_GATE_PASSED" if passed else "RELEASE_GATE_BLOCKED"
    else:
        result = report(args.suite, os.environ)
        write(result, "ci-public-summary")
        passed = result["checks_passed"]
        text = f"{args.suite}: checks {'passed' if passed else 'blocked'}; artifact is not final CI"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as stream:
            stream.write(text + "\n")
    print(text)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
