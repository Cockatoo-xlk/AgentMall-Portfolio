import json

import pytest
from evals.metrics import paired_report, schedule_pairs
from evals.report import scheduled_rows
from evals.studio import export_studio


def sample(tmp_path):
    task = "eval_dev_B2_01"
    plan = {
        "mode": "fixture",
        "dataset_sha256": "a" * 64,
        "manifest_sha256": "UNFROZEN",
        "episodes": [item | {"category": "B2"} for item in schedule_pairs([task], 2)],
    }
    (tmp_path / "schedule.json").write_text(json.dumps(plan))
    for item in plan["episodes"][:-1]:
        success = item["architecture"] == "single"
        row = item | {
            "mode": "fixture",
            "success": success,
            "run_status": "COMPLETED" if success else "PARTIAL",
            "machine_seconds": 0.25,
            "model_calls": 2,
            "tool_calls": 1,
            "actual_bill_cny": "NOT_APPLICABLE",
            "oracle": {
                "diagnostics": {"unauthorized_business_write_count": 0},
                "violations": []
                if success
                else [
                    {
                        "rule": "RESOURCE_DELTA",
                        "label": "BUSINESS_RULE",
                        "detail": "eyJ.private.test",
                    },
                    {"rule": "USER_BUDGET_MISMATCH", "label": "ORACLE_OR_FIXTURE"},
                    {"rule": "PRIVATE_PAYLOAD", "label": "sk-secret"},
                ],
            },
            "initial": {"aftersales_cases": [{"id": "SECRET-OLD"}]},
            "final": {"aftersales_cases": [{"id": "SECRET-OLD"}, {"id": "SECRET-NEW"}]},
            "messages": ["private-prompt"],
            "trace": {"db": "postgresql://example-secret"},
        }
        (tmp_path / f"{task}-{item['repetition_id']}-{item['architecture']}.json").write_text(
            json.dumps(row)
        )
    return plan


def test_export_uses_original_denominators_and_preserves_missing_values(tmp_path):
    sample(tmp_path)
    original = paired_report(scheduled_rows(tmp_path))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    public = export_studio(tmp_path)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    for arch in ("single", "multi"):
        assert public["comparison"][arch]["denominator"] == original[arch]["denominator"]
        assert public["comparison"][arch]["successes"] == original[arch]["successes"]
        assert public["comparison"][arch]["success_rate"] == original[arch]["success_rate"]
    assert public["comparison"]["multi_minus_single"]["mean_machine_seconds"] == "UNKNOWN"
    assert (
        public["comparison"]["single"]["actual_bill_cny"] == original["single"]["actual_bill_cny"]
    )
    assert public["run"]["git_commit"] == "UNKNOWN"
    assert public["comparison"]["paired_episodes"] == 2
    assert len(public["episodes"]) == 4
    assert any(row["run_status"] == "NOT_RUN" and not row["success"] for row in public["episodes"])


def test_only_reviewed_diagnostics_and_effect_counts_leave_raw_directory(tmp_path):
    sample(tmp_path)
    public = export_studio(tmp_path)
    row = next(row for row in public["episodes"] if row["run_status"] == "PARTIAL")
    assert row["business_effects"]["aftersales_cases"] == 1
    assert row["business_effects"]["orders"] == "UNKNOWN"
    assert row["oracle_rules"] == ["RESOURCE_DELTA", "USER_BUDGET_MISMATCH", "UNKNOWN"]
    assert row["error_class"] == "BUSINESS_RULE"
    for secret in (
        "eyJ.",
        "sk-secret",
        "SECRET-NEW",
        "PRIVATE_PAYLOAD",
        "private-prompt",
        "postgresql://",
    ):
        assert secret not in json.dumps(public)


@pytest.mark.parametrize("broken", ["incomplete", "duplicate", "unsafe_path", "mode"])
def test_export_rejects_invalid_schedule_or_mixed_evidence(tmp_path, broken):
    plan = sample(tmp_path)
    if broken == "incomplete":
        plan["episodes"].pop()
    elif broken == "duplicate":
        plan["episodes"].append(plan["episodes"][0])
    elif broken == "unsafe_path":
        plan["episodes"][0]["task_id"] = "../../sensitive"
    else:
        plan["mode"] = "live"
    (tmp_path / "schedule.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        export_studio(tmp_path)


def test_historical_aggregate_separate_from_current_fixture(tmp_path):
    sample(tmp_path)
    reviewed = tmp_path / "reviewed.json"
    reviewed.write_text(
        json.dumps(
            {
                "first": {"single_success": 1, "multi_success": 4, "tasks_per_architecture": 5},
                "second": {"single_success": 5, "multi_success": 4, "tasks_per_architecture": 5},
                "raw_conversation": "SECRET",
            }
        )
    )
    public = export_studio(tmp_path, historical_live=reviewed)
    assert public["comparison"]["evidence_class"] == "FIXTURE_EVALUATION"
    assert public["historical_live"]["evidence_class"] == "LIVE_LLM_EVALUATION"
    assert public["historical_live"]["second"]["single_success"] == 5
    assert "SECRET" not in json.dumps(public)
