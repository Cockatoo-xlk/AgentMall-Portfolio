"""CONTRACT_TEST_ONLY: no Agent episodes or live credentials are reachable here."""

import copy
import hashlib
import json

import pytest


def proposal():
    return {
        "purpose": "EXPLORATORY_PRODUCT_SMOKE",
        "version": "v217-smoke-v1",
        "live_authorization": "NONE",
        "independent_holdout_count": 0,
        "model": {"name": "deepseek-flash", "thinking": {"type": "disabled"}, "temperature": 0},
        "limits": {
            "http": 12,
            "models": 12,
            "tools": 16,
            "delegations": 4,
            "steps": 24,
            "input_tokens": 3145728,
            "output_tokens": 12000,
            "episode_seconds": 90,
            "outer_seconds": 300,
            "task_cost_cny": "2.50",
            "batch_cost_cny": "7.50",
        },
        "tasks": [
            {
                "id": "contract-A",
                "architecture": "single",
                "user_request": "只读需求",
                "fixture": {"recipe": "fresh-legacy"},
                "assertions": ["orders_delta=0"],
                "required_human_decisions": 0,
            },
            {
                "id": "contract-B",
                "architecture": "single",
                "user_request": "购买需求",
                "fixture": {"recipe": "fresh-legacy"},
                "assertions": ["orders_delta=1"],
                "required_human_decisions": 1,
            },
            {
                "id": "contract-C",
                "architecture": "multi",
                "user_request": "退换购需求",
                "fixture": {"recipe": "fresh-legacy-delivered"},
                "assertions": ["cases_delta=1"],
                "required_human_decisions": 2,
            },
        ],
        "rules": {
            "retry": False,
            "recover": False,
            "auto_approve": False,
            "unknown_stops_batch": True,
            "waiting_counts_toward_episode": True,
            "fresh_environment_per_task": True,
        },
    }


def test_freeze_binds_original_bytes_and_exact_source_without_starting_a_run(tmp_path):
    from evals.product_smoke import freeze_proposal

    source = "a" * 40
    path = tmp_path / "proposal.json"
    raw = json.dumps(proposal(), ensure_ascii=False).encode()
    path.write_bytes(raw)
    value = freeze_proposal(path, source_commit=source, source_tree="b" * 40)
    assert value["source_commit"] == source
    assert value["proposal_sha256"] == hashlib.sha256(raw).hexdigest()
    assert value["task_order"] == ["contract-A", "contract-B", "contract-C"]
    assert value["live_authorization"] == "NONE"
    assert value["episodes_started"] == value["provider_requests"] == value["key_reads"] == 0
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "field,value",
    [
        ("http", 13),
        ("http", True),
        ("models", 13),
        ("episode_seconds", 91),
        ("outer_seconds", 301),
        ("task_cost_cny", "2.51"),
        ("batch_cost_cny", "7.51"),
        ("task_cost_cny", "NaN"),
    ],
)
def test_budget_escalation_or_invalid_numbers_rejected(field, value):
    from evals.product_smoke import validate_proposal

    p = proposal()
    p["limits"][field] = value
    with pytest.raises(ValueError, match="BUDGET"):
        validate_proposal(p)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_task",
        "wrong_architecture",
        "auto_approve",
        "resume_resets_clock",
        "independence_claim",
        "preauthorized",
        "missing_fixture",
        "missing_assertions",
        "second_hitl_missing",
    ],
)
def test_invalid_or_privilege_increasing_contract_cannot_be_frozen(change):
    from evals.product_smoke import validate_proposal

    p = proposal()
    if change == "duplicate_task":
        p["tasks"][1]["id"] = p["tasks"][0]["id"]
    elif change == "wrong_architecture":
        p["tasks"][2]["architecture"] = "single"
    elif change == "auto_approve":
        p["rules"]["auto_approve"] = True
    elif change == "resume_resets_clock":
        p["rules"]["waiting_counts_toward_episode"] = False
    elif change == "independence_claim":
        p["purpose"] = "INDEPENDENT_BLIND_HOLDOUT"
    elif change == "preauthorized":
        p["live_authorization"] = "APPROVED"
    elif change == "missing_fixture":
        p["tasks"][0]["fixture"] = {}
    elif change == "missing_assertions":
        p["tasks"][0]["assertions"] = []
    elif change == "second_hitl_missing":
        p["tasks"][2]["required_human_decisions"] = 1
    with pytest.raises(ValueError):
        validate_proposal(p)


def test_freeze_rejects_invalid_source_and_never_mutates_input(tmp_path):
    from evals.product_smoke import freeze_proposal, validate_proposal

    original = proposal()
    original_copy = copy.deepcopy(original)
    assert validate_proposal(original)["purpose"] == "EXPLORATORY_PRODUCT_SMOKE"
    assert original == original_copy
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="SOURCE"):
        freeze_proposal(path, source_commit="main", source_tree="b" * 40)


def test_agent_projection_excludes_fixture_and_scoring_conditions():
    from evals.product_smoke import agent_input

    value = proposal()
    value["tasks"][0]["fixture"]["secret_scoring_canary"] = "GOLD_CANARY_217"
    value["tasks"][0]["assertions"] = ["GOLD_CANARY_217"]
    visible = agent_input(value, "contract-A")
    assert visible == {"mode": "single", "message": "只读需求"}
    assert "GOLD_CANARY_217" not in json.dumps(visible)
    with pytest.raises(ValueError, match="TASK"):
        agent_input(value, "old-L8-task")


@pytest.mark.parametrize("invalid", ["boolean_temperature", "null_assertion", "empty_assertion"])
def test_unexecutable_assertions_and_wrong_json_scalar_types_are_rejected(invalid):
    from evals.product_smoke import validate_proposal

    value = proposal()
    if invalid == "boolean_temperature":
        value["model"]["temperature"] = False
    else:
        value["tasks"][0]["assertions"] = [None if invalid == "null_assertion" else ""]
    with pytest.raises(ValueError):
        validate_proposal(value)
