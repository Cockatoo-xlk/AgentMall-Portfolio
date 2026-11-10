"""CI outcomes, metadata and actual workflow topology; no model/network/database."""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "agentmall_ci_release_gate", ROOT / "scripts/ci/release_gate.py"
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)
SHA = "a" * 40


def environment(suite):
    env = {"GITHUB_SHA": SHA, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
    env.update({f"RESULT_{key}": "success" for key in gate.CHECKS[suite]})
    return env


@pytest.mark.parametrize("suite", ["backend", "frontend", "gate"])
def test_all_checks_and_binding_are_required(suite):
    result = gate.report(suite, environment(suite))
    assert result["checks_passed"] and result["commit_sha"] == SHA
    assert result["workflow_conclusion"] == "NOT_DETERMINED_BY_ARTIFACT"
    assert len(json.dumps(result).encode()) <= 4096


@pytest.mark.parametrize(
    "suite,key",
    [
        ("backend", "PYTEST"),
        ("backend", "BOOTSTRAP"),
        ("backend", "PYTHON_DEPS"),
        ("frontend", "PLAYWRIGHT"),
        ("frontend", "NODE_DEPS"),
        ("frontend", "BOOTSTRAP"),
        ("gate", "BACKEND"),
        ("gate", "FRONTEND"),
    ],
)
@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", ""])
def test_non_success_never_passes(suite, key, outcome):
    env = environment(suite)
    env["RESULT_" + key] = outcome
    assert not gate.report(suite, env)["checks_passed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("GITHUB_SHA", "main"),
        ("GITHUB_SHA", "$(echo SECRET)"),
        ("GITHUB_RUN_ID", ""),
        ("GITHUB_RUN_ATTEMPT", "nan"),
        ("RESULT_PLAYWRIGHT", "success\nAuthorization: Bearer PRIVATE"),
    ],
)
def test_invalid_metadata_is_redacted_and_blocked(field, value):
    env = environment("frontend")
    env[field] = value
    result = gate.report("frontend", env)
    assert not result["checks_passed"] and "PRIVATE" not in json.dumps(result)
    assert "$(echo SECRET)" not in json.dumps(result)


@pytest.mark.parametrize("key", ["BACKEND", "FRONTEND", "CHECKOUT", "SUMMARY", "UPLOAD"])
@pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", ""])
def test_final_enforcement_includes_export_and_setup(key, outcome):
    env = environment("gate")
    env.update({f"RESULT_{k}": "success" for k in ["CHECKOUT", "SUMMARY", "UPLOAD"]})
    env["RESULT_" + key] = outcome
    assert not gate.enforce(env)


def test_enforcement_positive_and_no_raw_environment_export(tmp_path):
    env = environment("gate")
    env.update({f"RESULT_{k}": "success" for k in ["CHECKOUT", "SUMMARY", "UPLOAD"]})
    env["DEEPSEEK_API_KEY"] = "PRIVATE_NOT_A_REAL_KEY"
    assert gate.enforce(env)
    result = gate.report("gate", env)
    target = gate.write(result, tmp_path)
    assert target.stat().st_size <= 4096 and "PRIVATE" not in target.read_text()
    assert set(json.loads(target.read_text())) == {
        "schema_version",
        "suite",
        "commit_sha",
        "run_id",
        "run_attempt",
        "checks",
        "checks_passed",
        "metadata_valid",
        "model",
        "real_bge",
        "workflow_conclusion",
    }


def test_summary_refuses_symlink_export(tmp_path):
    (tmp_path / "backend.json").symlink_to(tmp_path / "other")
    with pytest.raises((ValueError, FileExistsError)):
        gate.write(gate.report("backend", environment("backend")), tmp_path)


def workflow():
    return yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)


def test_parallel_dag_preserves_every_old_check_and_t16_rules():
    w = workflow()
    jobs = w["jobs"]
    assert {"backend-core", "frontend-e2e", "release-gate", "t16-admission"} == set(jobs)
    expected = {
        "backend-core": {"python-deps", "bootstrap", "ruff", "format", "pytest"},
        "frontend-e2e": {
            "python-deps",
            "node-deps",
            "chromium",
            "bootstrap",
            "typecheck",
            "lint",
            "vitest",
            "build",
            "playwright",
        },
    }
    for name, ids in expected.items():
        job = jobs[name]
        assert not job.get("needs") and job["runs-on"] == "ubuntu-24.04"
        assert job["timeout-minutes"] == "30" and "postgres" in job["services"]
        steps = {s.get("id"): s for s in job["steps"]}
        assert ids <= set(steps)
        assert all("continue-on-error" not in s for s in job["steps"])
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[a-f0-9]{40}", step["uses"])
        assert steps["checkout"]["with"]["persist-credentials"] == "false"
        assert steps["summary"]["if"] == "always()" and steps["upload"]["if"] == "always()"
        assert (
            steps["upload"]["with"]["path"]
            == f"ci-public-summary/{'backend' if name == 'backend-core' else 'frontend'}.json"
        )
    assert "node" not in {s.get("id") for s in jobs["backend-core"]["steps"]}
    assert jobs["release-gate"]["needs"] == ["backend-core", "frontend-e2e"]
    assert (
        "always()" in jobs["release-gate"]["if"]
        and "t16-a3-ci-verify" in jobs["release-gate"]["if"]
    )
    assert jobs["release-gate"]["steps"][-1]["id"] == "enforce"
    assert jobs["release-gate"]["steps"][-1]["if"] == "always()"
    assert w["permissions"] == {"contents": "read"}
    assert w["on"]["push"]["branches-ignore"] == ["codex/t16-a3-ci-verify"]
    assert "github.run_attempt == 1" in jobs["t16-admission"]["if"]
    assert jobs["t16-admission"]["uses"] == "./.github/workflows/t16-a3-admission.yml"
    assert [s.get("id") for s in jobs["backend-core"]["steps"]].index("bootstrap") < [
        s.get("id") for s in jobs["backend-core"]["steps"]
    ].index("pytest")
    assert "--ci-offline-core --strict-markers -ra" in next(
        s["run"] for s in jobs["backend-core"]["steps"] if s.get("id") == "pytest"
    )
    assert "npm --prefix frontend run test:e2e" in next(
        s["run"] for s in jobs["frontend-e2e"]["steps"] if s.get("id") == "playwright"
    )


@pytest.mark.parametrize(
    "suite,key",
    [
        ("backend", "PYTEST"),
        ("backend", "BOOTSTRAP"),
        ("frontend", "PLAYWRIGHT"),
        ("gate", "FRONTEND"),
    ],
)
def test_cli_failure_writes_bounded_failure_artifact_and_exits_nonzero(tmp_path, suite, key):
    env = environment(suite)
    env["RESULT_" + key] = "cancelled"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/release_gate.py"), "--suite", suite],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert proc.returncode == 1
    artifact = tmp_path / "ci-public-summary" / (suite + ".json")
    result = json.loads(artifact.read_text())
    assert not result["checks_passed"] and artifact.stat().st_size < 4096
    assert result["checks"][key] == "cancelled"


@pytest.mark.parametrize("key", ["BACKEND", "CHECKOUT", "SUMMARY", "UPLOAD"])
def test_cli_enforcement_cannot_succeed_after_required_failure(tmp_path, key):
    env = environment("gate")
    env.update({"RESULT_" + k: "success" for k in ["CHECKOUT", "SUMMARY", "UPLOAD"]})
    env["RESULT_" + key] = "failure"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/release_gate.py"), "--suite", "gate", "--enforce"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert proc.returncode == 1 and b"RELEASE_GATE_BLOCKED" in proc.stdout
    assert not (tmp_path / "ci-public-summary").exists()
