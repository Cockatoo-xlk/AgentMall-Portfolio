from pathlib import Path

import pytest
from evals.run import run_episode
from evals.schema import load_tasks

ROOT = Path(__file__).resolve().parents[2]


async def test_dev_pair_uses_same_fixture_and_distinct_owned_schemas():
    tasks = load_tasks(ROOT / "evals/data/agent_dev.jsonl")
    task = next(t for t in tasks if t.task_id == "eval_dev_B2_01")
    single = await run_episode(task, "single", 0)
    multi = await run_episode(task, "multi", 0)
    for result in (single, multi):
        assert result["success"], result["oracle"]
        assert result["evidence_class"] == "FIXTURE_EVALUATION"
        assert result["paid_provider_requests"] == 0
        assert result["cleanup"]["remaining"] == []
        assert result["final"]["checkpoint_counts"]["checkpoints"] > 0
    assert single["initial_hash"] == multi["initial_hash"]
    assert single["cleanup"]["business_schema"] != multi["cleanup"]["business_schema"]
    assert single["run_id"] != multi["run_id"]
    assert single["confirmations"] == multi["confirmations"] == 2
    assert single["final"]["invariants"]["violations"] == []


async def test_simulator_does_not_authorize_undeclared_proposal():
    tasks = load_tasks(ROOT / "evals/data/agent_dev.jsonl")
    task = next(t for t in tasks if t.task_id == "eval_dev_A2_01")
    task = task.model_copy(
        update={"user_script": task.user_script.model_copy(update={"decisions": []})}
    )
    result = await run_episode(task, "single", 0)
    assert not result["success"]
    assert result["simulator_error"] == "UNEXPECTED_CONFIRMATION"
    assert len(result["final"]["orders"]) == 0
    assert result["cleanup"]["remaining"] == []


@pytest.mark.parametrize("architecture", ["single", "multi"])
async def test_recovery_pair_keeps_original_run_and_committed_effect(architecture):
    tasks = load_tasks(ROOT / "evals/data/agent_dev.jsonl")
    task = next(t for t in tasks if t.task_id == "eval_dev_R1_02")
    result = await run_episode(task, architecture, 0)
    assert result["success"], result
    assert len(result["final"]["runs"]) == 1
    assert len(result["final"]["aftersales_cases"]) == 1
    assert result["recoveries"] == 1


async def test_single_budget_exhaustion_preserves_explicit_exit_class():
    task = next(
        t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == "eval_dev_E1_02"
    )
    result = await run_episode(task, "single", 0)
    assert result["success"], result["oracle"]
    assert result["model_calls"] == 12
    assert "BUDGET_EXCEEDED" in result["result"]["error_codes"]


async def test_live_runner_uses_actual_sdk_with_local_mock_transport_only(tmp_path, monkeypatch):
    import json

    import httpx
    from evals import provider
    from evals.provider import BudgetLedger
    from retrieval_helpers import FixtureEncoder
    from test_eval_budget import policy

    from agentmall.retrieval import embedding

    task = next(
        t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == "eval_dev_A1_01"
    )
    ledger = BudgetLedger(tmp_path / "ledger.json", policy(max_model_calls=4))
    requests = []

    def wire(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["temperature"] == 0
        assert len(ledger.read()["attempts"]) == len(requests)
        message = {"role": "assistant", "content": "完成"}
        if len(requests) == 1:
            message.update(
                content="",
                tool_calls=[
                    {
                        "id": "local_tool_1",
                        "type": "function",
                        "function": {
                            "name": "retrieve_products",
                            "arguments": '{"query":"静音键盘"}',
                        },
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "id": f"local_{len(requests)}",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    original = provider.MeteredTransport
    monkeypatch.setattr(
        provider,
        "MeteredTransport",
        lambda ledger, episode: original(ledger, episode, inner=httpx.MockTransport(wire)),
    )
    monkeypatch.setattr(embedding, "LocalEncoder", FixtureEncoder)
    result = await run_episode(
        task, "single", 0, mode="live", live_ledger=ledger, live_key="synthetic-local-key"
    )
    assert result["success"], result
    assert result["model_calls"] == len(requests) == 2
    assert result["cleanup"]["remaining"] == []
    assert result["final"]["checkpoint_counts"]["checkpoints"] > 0
    # This is protocol-only MockTransport; no evidence file claims real paid requests.
