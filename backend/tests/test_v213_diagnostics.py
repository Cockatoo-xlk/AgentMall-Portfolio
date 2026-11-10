import asyncio
import json
from uuid import uuid4

from conftest import ROOT

from agentmall.infra.observability import public_summary


def test_handoff_diagnostic_keeps_constraints_dependencies_and_safe_source():
    from agentmall.agents.context import Constraints

    constraints = Constraints(
        category="keyboard",
        max_price_cents=50000,
        quantity=1,
        address_label="demo_dorm",
        noise_preference="quiet",
    ).model_dump(mode="json")
    value = public_summary(
        "handoff",
        {
            "subtask_id": "replace",
            "depends_on": ["return"],
            "constraints": constraints,
            "constraint_source": "CURRENT_REQUEST",
            "context_version": None,
            "prompt": "PRIVATE PROMPT",
            "Authorization": "Bearer SECRET",
        },
    )
    assert value["constraints"] == constraints
    assert value["depends_on"] == ["return"]
    assert value["constraint_source"] == "CURRENT_REQUEST"
    assert "prompt" not in value and "Authorization" not in value


def test_diagnostic_export_is_allowlisted_and_missing_is_not_zero(tmp_path):
    from evals.agent_diagnostics import project, write_diagnostic

    ident = str(uuid4())
    sample = {
        "task_id": "sample",
        "architecture": "multi",
        "repetition_id": 0,
        "run_id": ident,
        "run_status": "PARTIAL",
        "result": {"error_codes": ["INCOMPLETE_WRITE_GOAL"], "answer": "private text"},
        "graph_budget": {"models": 5, "tools": 3},
        "provider_calls": [{"Authorization": "Bearer PRIVATE"}],
        "final": {
            "run_events": [
                {
                    "run_id": ident,
                    "seq": 1,
                    "event_type": "model_start",
                    "payload_summary": {
                        "role": "aftersales",
                        "attempt": 5,
                        "prompt": "PRIVATE PROMPT",
                    },
                }
            ]
        },
    }
    result = project(sample)
    assert result["events"][0]["payload_summary"] == {
        "role": "aftersales",
        "attempt": 5,
        "usage": "UNKNOWN",
    }
    assert result["budget"]["models"] == 5 and result["budget"]["delegations"] == "UNKNOWN"
    assert result["failure_class"] == "ORCHESTRATION"
    assert result["confirmations"] == "UNKNOWN"
    raw = json.dumps(result)
    assert "PRIVATE" not in raw and "private text" not in raw and "Authorization" not in raw
    target = write_diagnostic(sample, tmp_path / "private")
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700


async def test_optional_episode_diagnostics_use_real_committed_events(tmp_path):

    from evals.agent_diagnostics import project
    from evals.run import run_episode
    from evals.schema import load_tasks

    task = next(
        t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == "eval_dev_B2_01"
    )
    result = await run_episode(task, "multi", 0, diagnostics_dir=tmp_path / "private")
    assert result["success"], result["oracle"]
    assert result["agent_diagnostics"]["status"] == "SAVED"
    files = list((tmp_path / "private").glob("*.json"))
    assert len(files) == 1
    d = json.loads(await asyncio.to_thread(files[0].read_text))
    assert d == project(result)
    assert d["budget"]["models"] <= 12 and d["budget"]["tools"] <= 16
    assert any(
        e["event_type"] == "handoff" and e["payload_summary"]["constraints"]["exclude_original"]
        for e in d["events"]
    )
    assert any(e["event_type"] == "specialist_started" for e in d["events"])
    assert any(e["event_type"] == "resume_received" for e in d["events"])
    assert not d["events_truncated"]
    assert result["cleanup"]["remaining"] == []


def test_diagnostic_export_never_overwrites_or_follows_symlink(tmp_path):
    import pytest
    from evals.agent_diagnostics import write_diagnostic

    episode = {"run_id": str(uuid4())}
    path = write_diagnostic(episode, tmp_path / "private")
    with pytest.raises(FileExistsError):
        write_diagnostic(episode, path.parent)
    alias = tmp_path / "alias"
    alias.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="UNSAFE"):
        write_diagnostic(episode, alias)


def test_diagnostic_distinguishes_setup_confirmations_from_agent_actions():
    from evals.agent_diagnostics import project

    pid = str(uuid4())
    cid = str(uuid4())
    initial = str(uuid4())
    data = {
        "initial": {"confirmations": [{"id": initial}]},
        "final": {
            "action_proposals": [{"id": pid, "action_type": "RETURN_REQUEST"}],
            "confirmations": [
                {
                    "id": cid,
                    "proposal_id": pid,
                    "decision": "approve",
                    "consumed_at": "2026-11-09T01:00:00+00:00",
                    "result_ref": str(uuid4()),
                }
            ],
        },
        "oracle": {
            "diagnostics": {
                "unauthorized_business_write_count": 0,
                "missing_expected_confirmation_count": 0,
            }
        },
    }
    result = project(data)
    assert result["confirmations"][0]["action_type"] == "RETURN_REQUEST"
    assert result["confirmations"][0]["scope"] == "AGENT_EPISODE"
    assert result["oracle_diagnostics"]["unauthorized_business_write_count"] == 0
    assert result["oracle_diagnostics"]["unsupported_fact_claim_count"] == "UNKNOWN"


def test_diagnostic_families_do_not_turn_unknown_causes_into_model_faults():
    from evals.agent_diagnostics import project

    for code, family in [
        ("INVALID_ROUTE", "MODEL_OUTPUT_OR_SELECTION"),
        ("TOOL_FAILED", "TOOL_OR_DOMAIN"),
        ("DATABASE_UNAVAILABLE", "ENVIRONMENT"),
        ("INCOMPLETE_WRITE_GOAL", "ORCHESTRATION"),
        ("BUDGET_EXCEEDED", "RESOURCE_LIMIT"),
        ("UNRECOGNIZED_CODE", "UNKNOWN"),
    ]:
        assert project({"result": {"error_codes": [code]}})["failure_class"] == family


def test_nested_bundle_text_is_not_public_diagnostic_data():
    from evals.agent_diagnostics import project

    from agentmall.agents.context import Constraints

    constraints = Constraints.model_validate(
        {
            "bundle": {
                "budget_cents": 100000,
                "parts": [
                    {
                        "category": "keyboard",
                        "requirements": {
                            "category": "keyboard",
                            "query": "PRIVATE-QUERY password sk-sentinel",
                            "layout": "PRIVATE-LAYOUT",
                        },
                    },
                    {
                        "category": "mouse",
                        "requirements": {"category": "mouse", "query": "PRIVATE-SECOND"},
                    },
                ],
            }
        }
    ).model_dump(mode="json")
    event = {
        "constraints": constraints,
        "subtask_id": "bundle",
        "target": "order",
        "goal": "prepare_checkout",
    }
    handoff = public_summary("handoff", event)
    route = public_summary("route_decision", {"validated_arguments": {"tasks": [event]}})
    exported = project(
        {"final": {"run_events": [{"seq": 1, "event_type": "handoff", "payload_summary": event}]}}
    )
    for value in [handoff, route, exported]:
        assert "PRIVATE-" not in json.dumps(value)
        assert "sk-sentinel" not in json.dumps(value)
    assert handoff["constraints"]["bundle"]["parts"][0]["requirements_omitted_fields"] == [
        "query",
        "layout",
    ]

    # Stored RunEvent summaries are projected a second time by the optional exporter.
    repeated = public_summary("handoff", handoff)
    assert repeated == handoff
    safe_export = project(
        {"final": {"run_events": [{"seq": 1, "event_type": "handoff", "payload_summary": handoff}]}}
    )
    assert safe_export["events"][0]["payload_summary"] == handoff
