"""Real PostgreSQL metadata durability across rejected/uncheckpointed nodes."""

import json
from uuid import uuid4

import pytest
from conftest import row
from multiagent_helpers import install, make_models, route
from sqlalchemy import text
from t09_helpers import durable_env as durable_env
from t09_helpers import purchase_models, start, thread


def events(env):
    with env[1].connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT seq,event_type,payload_summary FROM run_events ORDER BY seq")
            ).mappings()
        ]


@pytest.mark.parametrize("kind", ["constraint", "provider"])
async def test_failed_node_keeps_model_metadata_without_prompt_or_parameters(
    durable_env, buyer, kind
):
    bad = route("shopping", "find_products", change=lambda t: t["constraints"].update(quantity=2))
    script = (
        [bad, bad]
        if kind == "constraint"
        else [RuntimeError("sk-synthetic-secret SELECT private_address")]
    )
    models = make_models(supervisor=script)
    await install(durable_env, models)
    tid = await thread(durable_env, buyer)
    run = (await start(durable_env, buyer, tid)).json()
    expected = 2 if kind == "constraint" else 1
    assert run["budget"]["models"] == expected
    records = events(durable_env)
    ends = [e["payload_summary"] for e in records if e["event_type"] == "model_end"]
    assert len(ends) == expected
    assert [e["attempt"] for e in ends] == list(range(1, expected + 1))
    assert ends[-1]["usage"] == (
        "UNKNOWN"
        if kind == "provider"
        else {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    )
    assert ends[-1]["status"] == ("failed" if kind == "provider" else "completed")
    assert "sk-synthetic" not in json.dumps(records)
    assert "private_address" not in json.dumps(records)
    assert "canonical_constraints" not in json.dumps(records)
    if kind == "constraint":
        rejects = [
            e["payload_summary"] for e in records if e["event_type"] == "orchestration_rejected"
        ]
        assert len(rejects) == 2
        assert all(e["constraint_fields"] == ["quantity"] for e in rejects)
    assert (
        "supervisor:0"
        not in row(durable_env[1], "SELECT node_journal FROM agent_runs")["node_journal"]
    )


async def test_model_events_deduplicate_node_journal_and_checkpoint_recovery(
    durable_env, buyer, monkeypatch
):
    from agentmall.agents.run_service import NodeStore

    env = durable_env
    await purchase_models(env)
    save = NodeStore.save

    async def fail(self, key, output, trace):
        await save(self, key, output, trace)
        if key == "supervisor:0":
            raise RuntimeError("synthetic post-journal gap")

    monkeypatch.setattr(NodeStore, "save", fail)
    tid = await thread(env, buyer)
    rid = str(uuid4())
    partial = (await start(env, buyer, tid, rid)).json()
    assert partial["status"] == "PARTIAL"
    monkeypatch.setattr(NodeStore, "save", save)
    waiting = (await start(env, buyer, tid, rid)).json()
    assert waiting["status"] == "WAITING_INPUT"
    count = waiting["budget"]["models"]
    replay = (await start(env, buyer, tid, rid)).json()
    assert replay["budget"]["models"] == count
    records = events(env)
    model_events = [
        (e["event_type"], e["payload_summary"]["attempt"])
        for e in records
        if e["event_type"] in {"model_start", "model_end"}
    ]
    assert len(model_events) == len(set(model_events)) == count * 2
    assert [e["seq"] for e in records] == list(range(1, len(records) + 1))


def test_constraint_diagnostics_only_allow_fixed_field_names():
    from agentmall.infra.observability import public_summary

    event = {
        "error_code": "HANDOFF_CONSTRAINT_CHANGED",
        "constraint_fields": [
            "quantity",
            "sk-synthetic-secret",
            "private_address",
            "exclude_product_ids",
        ],
        "rejected_arguments": {"secret": "never"},
    }
    assert public_summary("orchestration_rejected", event) == {
        "error_code": "HANDOFF_CONSTRAINT_CHANGED",
        "constraint_fields": ["exclude_product_ids", "quantity"],
    }


async def test_invalid_settlement_keeps_unknown_end_and_reserved_budget(durable_env, buyer):
    from langchain_core.messages import AIMessage

    message = AIMessage(
        content="synthetic bad usage",
        usage_metadata={"input_tokens": 1, "output_tokens": 9999, "total_tokens": 10000},
    )
    await install(durable_env, make_models(supervisor=[message]))
    run = (await start(durable_env, buyer, await thread(durable_env, buyer))).json()
    assert "MODEL_USAGE_INVALID" in run["result"]["error_codes"]
    assert run["budget"]["models"] == 1 and run["budget"]["output_tokens"] == 2048
    ends = [e["payload_summary"] for e in events(durable_env) if e["event_type"] == "model_end"]
    assert len(ends) == 1
    assert ends[0]["usage"] == "UNKNOWN" and ends[0]["status"] == "failed"
    assert ends[0]["error_code"] == "MODEL_USAGE_INVALID"
    assert row(durable_env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
