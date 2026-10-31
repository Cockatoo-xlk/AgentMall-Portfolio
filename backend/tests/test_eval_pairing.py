from copy import deepcopy

import pytest
from evals.metrics import paired_report, schedule_pairs
from evals.schema import Episode


def test_schedule_pairs_is_balanced_complete_and_repetition_clustered():
    tasks = [f"t{i}" for i in range(5)]
    schedule = schedule_pairs(tasks, 3)
    assert len(schedule) == 30
    assert len({(x["task_id"], x["repetition_id"], x["architecture"]) for x in schedule}) == 30
    for index in range(0, len(schedule), 2):
        a, b = schedule[index : index + 2]
        assert (a["task_id"], a["repetition_id"]) == (b["task_id"], b["repetition_id"])
        assert [a["architecture"], b["architecture"]] == (
            ["single", "multi"] if index % 4 == 0 else ["multi", "single"]
        )


def test_paired_bootstrap_keeps_failures_and_clusters_repeats():
    rows = []
    for item in schedule_pairs(["a", "b", "c"], 3):
        rows.append(
            item
            | {
                "category": "A1",
                "success": item["task_id"] != "c",
                "machine_seconds": 2.0,
                "model_calls": 1,
                "tool_calls": 1,
                "input_tokens": "UNKNOWN",
                "output_tokens": "UNKNOWN",
                "cost_cny": "NOT_APPLICABLE",
            }
        )
    result = paired_report(rows, bootstrap=200, seed=7)
    assert result["cluster_count"] == 3
    assert result["single"]["denominator"] == result["multi"]["denominator"] == 9
    assert result["multi_minus_single"]["success_rate"] == 0
    assert result["multi_minus_single"]["success_ci95"] == [0, 0]
    assert result["single"]["input_tokens"] == "UNKNOWN"
    assert result["single"]["cost_cny"] == "NOT_APPLICABLE"
    assert paired_report(rows, bootstrap=200, seed=7) == result
    with pytest.raises(ValueError, match="pair"):
        paired_report(rows[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        paired_report(rows + [deepcopy(rows[0])])


def test_episode_refuses_unknown_or_unbounded_scripts():
    with pytest.raises(ValueError):
        Episode.model_validate({"task_id": "guess", "user_goal": "买东西"})


def test_interrupted_report_retains_planned_denominator(tmp_path):
    import json

    from evals.report import scheduled_rows

    schedule = [item | {"category": "A1"} for item in schedule_pairs(["a", "b"])]
    (tmp_path / "schedule.json").write_text(json.dumps({"mode": "fixture", "episodes": schedule}))
    for item in schedule[:2]:
        (
            tmp_path / f"{item['task_id']}-{item['repetition_id']}-{item['architecture']}.json"
        ).write_text(json.dumps(item | {"success": True, "machine_seconds": 1.0}))
    rows = scheduled_rows(tmp_path)
    report = paired_report(rows, bootstrap=20)
    assert report["single"]["denominator"] == report["multi"]["denominator"] == 2
    assert report["single"]["successes"] == report["multi"]["successes"] == 1
    assert sum(r.get("run_status") == "NOT_RUN" for r in rows) == 2
    assert report["single"]["machine_latency_p50"] == "UNKNOWN"
