"""L1 offline admission: actual SDK, owned PG/BGE, and multiprocess budget gates.

Every HTTP completion is a MockTransport response. Never touches the real Live ledger.
"""

import hashlib
import json
import multiprocessing
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from evals import fixtures, provider, run
from evals.fixture_model import fixture_models
from evals.provider import BudgetLedger, LivePolicy, ProviderBoundaryError
from evals.schema import load_tasks
from pydantic import ValidationError
from sqlalchemy import text
from test_eval_budget import policy

from agentmall.agents.specialist_tools import ALLOWLISTS, SCHEMAS

ROOT = Path(__file__).resolve().parents[2]
PILOT = [
    "eval_dev_A1_01",
    "eval_dev_A2_01",
    "eval_dev_B1_01",
    "eval_dev_B2_01",
    "eval_dev_B1_03",
]


def receipt(name, data):
    directory = os.environ.get("AGENTMALL_L1_EVIDENCE_DIR")
    if directory:
        directory = Path(directory).resolve()
        assert directory.is_relative_to(ROOT / "evals/evidence/t12-live-preflight")
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (name + ".json")).open("x") as stream:
            json.dump(
                {"evidence_class": "OFFLINE_TEST", "paid_requests": 0, **data},
                stream,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            stream.write("\n")


def reserve_worker(path, data, barrier, queue):
    """Spawned processes share only the real flock-protected synthetic ledger."""
    ledger = BudgetLedger(Path(path), LivePolicy(**data))
    barrier.wait(timeout=15)
    for index in range(3):
        try:
            token = ledger.reserve(f"different-run:{os.getpid()}:{index}", 2048)
            queue.put((os.getpid(), "RESERVED", token))
        except ProviderBoundaryError as exc:
            queue.put((os.getpid(), str(exc), None))


@pytest.mark.parametrize("cap,cost,expected", [(3, "100", 3), (100, "4.23", 2)])
def test_multiprocess_ledger_has_no_double_spend(tmp_path, cap, cost, expected):
    config = policy(max_model_calls=cap, max_cost_cny=cost)
    path = tmp_path / "synthetic-ledger.json"
    ledger = BudgetLedger(path, config)
    ctx = multiprocessing.get_context("spawn")
    queue, barrier = ctx.Queue(), ctx.Barrier(4)
    workers = [
        ctx.Process(target=reserve_worker, args=(str(path), asdict(config), barrier, queue))
        for _ in range(4)
    ]
    try:
        for process in workers:
            process.start()
        outcomes = [queue.get(timeout=30) for _ in range(12)]
        for process in workers:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert len({item[0] for item in outcomes}) == 4
        assert sum(item[1] == "RESERVED" for item in outcomes) == expected
        assert {item[1] for item in outcomes} == {"RESERVED", "EXPERIMENT_BUDGET_EXHAUSTED"}
        rows = BudgetLedger(path, config).read()["attempts"]
        assert len(rows) == len({r["id"] for r in rows}) == expected
        assert all(r["usage"] == "UNKNOWN" for r in rows)
        assert sum(Decimal(r["held_cny"]) for r in rows) <= Decimal(cost)
        with pytest.raises(ProviderBoundaryError, match="BUDGET"):
            BudgetLedger(path, config).reserve("new-run-label-after-restart", 2048)
        for changes in ({"max_cost_cny": "200"}, {"max_model_calls": 200}):
            with pytest.raises(ProviderBoundaryError, match="BINDING"):
                BudgetLedger(path, LivePolicy(**(asdict(config) | changes)))
        receipt(
            f"multiprocess-{cap}", {"processes": 4, "attempts": outcomes, "ledger": ledger.read()}
        )
    finally:
        for process in workers:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
        queue.join_thread()


@pytest.mark.parametrize("failure", [429, 500, "response_loss", "unknown_usage"])
async def test_sdk_failure_has_one_charged_attempt_no_hidden_retry(tmp_path, failure):
    from openai import APIConnectionError, APIStatusError

    ledger = BudgetLedger(tmp_path / "synthetic-ledger.json", policy())
    seen = []

    def wire(request):
        seen.append(1)
        assert ledger.read()["attempts"][0]["state"] == "RESERVED"
        if failure == "response_loss":
            raise httpx.ReadError("synthetic reply lost", request=request)
        if isinstance(failure, int):
            return httpx.Response(failure, json={"error": {"message": "synthetic failure"}})
        return httpx.Response(200, json=completion("done", "fixture-response"))

    transport = provider.MeteredTransport(ledger, "task", inner=httpx.MockTransport(wire))
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        model = provider.live_model("synthetic-L1-key", client)
        assert model.max_retries == model.root_async_client.max_retries == 0
        if failure == "unknown_usage":
            await model.ainvoke("synthetic-L1-private-prompt", max_tokens=2048)
        else:
            with pytest.raises((APIConnectionError, APIStatusError)):
                await model.ainvoke("synthetic-L1-private-prompt", max_tokens=2048)
    rows = ledger.read()["attempts"]
    assert len(seen) == len(rows) == 1
    assert rows[0]["state"] == rows[0]["usage"] == "UNKNOWN"
    assert Decimal(rows[0]["held_cny"]) == Decimal("2.113536")
    assert "synthetic-L1-key" not in ledger.path.read_text()
    assert "synthetic-L1-private-prompt" not in ledger.path.read_text()
    receipt(
        f"provider-failure-{failure}", {"mock_http_attempts": len(seen), "ledger": ledger.read()}
    )


def completion(content, ident, calls=None, usage=None):
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {
                "id": c["id"],
                "type": "function",
                "function": {
                    "name": c["name"],
                    "arguments": json.dumps(c["args"], ensure_ascii=False),
                },
            }
            for c in calls
        ]
    data = {
        "id": ident,
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [
            {"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}
        ],
    }
    if usage:
        data["usage"] = usage
    return data


async def test_failed_ledger_persistence_prevents_send(tmp_path, monkeypatch):
    ledger = BudgetLedger(tmp_path / "synthetic-ledger.json", policy())

    def broken_write(data):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(ledger, "_write", broken_write)
    transport = provider.MeteredTransport(
        ledger,
        "task",
        inner=httpx.MockTransport(lambda request: pytest.fail("sent without reservation")),
    )
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        with pytest.raises(OSError, match="storage failure"):
            await client.post(
                "https://api.deepseek.com/chat/completions",
                json={
                    "model": "deepseek-flash",
                    "thinking": {"type": "disabled"},
                    "max_tokens": 2048,
                },
            )
    assert ledger.read()["attempts"] == []


@pytest.mark.parametrize(
    "url",
    [
        None,
        "postgresql+psycopg://agentmall:synthetic@127.0.0.1:55432/agentmall_test",
        "postgresql+psycopg://agentmall:synthetic@127.0.0.1:55433/agentmall",
        "postgresql+psycopg://other:synthetic@127.0.0.1:55433/agentmall_test",
        "postgresql+psycopg://agentmall:synthetic@elsewhere.invalid:55433/agentmall_test",
        "postgresql://agentmall:synthetic@127.0.0.1:55433/agentmall_test",
        "postgresql+psycopg://agentmall:synthetic@127.0.0.1:55433/agentmall_test?host=other",
    ],
)
async def test_invalid_database_rejected_before_engine_or_schema(monkeypatch, url):
    seen = []

    def config(path):
        assert path == ROOT / ".env.rag"
        seen.append(str(path))
        return {"AGENTMALL_TEST_DATABASE_URL": url}

    monkeypatch.setattr(fixtures, "dotenv_values", config)
    monkeypatch.setattr(
        fixtures, "create_engine", lambda *a, **k: pytest.fail("connection attempted")
    )
    task = load_tasks(ROOT / "evals/data/agent_dev.jsonl")[0]
    with pytest.raises(ValueError):
        async with fixtures.episode_database(task):
            pytest.fail("invalid database admitted")
    assert len(seen) == 1


def test_project_database_overrides_inherited_env(monkeypatch):
    from sqlalchemy.engine import make_url

    monkeypatch.setenv("AGENTMALL_DATABASE_URL", "postgresql+psycopg://bad:bad@invalid:55432/demo")
    monkeypatch.setenv(
        "AGENTMALL_TEST_DATABASE_URL", "postgresql+psycopg://bad:bad@invalid:55432/demo"
    )
    settings = fixtures.settings_for_eval()
    for value in (settings.database_url, settings.test_database_url):
        url = make_url(value.get_secret_value())
        assert (url.host, url.port, url.database, url.username) == (
            "127.0.0.1",
            55433,
            "agentmall_test",
            "agentmall",
        )


@pytest.mark.parametrize(
    "field", ["actor_id", "store_id", "approved", "confirmation_id", "amount_cents"]
)
def test_no_tool_schema_grants_authority(field):
    from uuid import uuid4

    base = {
        "query": "synthetic",
        "product_id": str(uuid4()),
        "order_id": str(uuid4()),
        "reason_code": "QUALITY_ISSUE",
        "description": "synthetic",
        "reason": "EXPLANATION",
        "summary": "synthetic",
    }
    for schema in SCHEMAS.values():
        valid = {k: base[k] for k, v in schema.model_fields.items() if v.is_required()}
        schema.model_validate(valid)
        with pytest.raises(ValidationError) as error:
            schema.model_validate(valid | {field: "forged"})
        assert any(e["type"] == "extra_forbidden" for e in error.value.errors())
    assert "refund" not in SCHEMAS


@pytest.mark.parametrize("task_id", PILOT)
@pytest.mark.parametrize("architecture", ["single", "multi"])
@pytest.mark.real_bge
async def test_pilot_sdk_pg_checkpoint_and_real_local_embedding(
    tmp_path, monkeypatch, task_id, architecture
):
    """Real SDK wire + existing scripted responses: explicitly NOT Live quality evidence."""
    from langchain_openai.chat_models.base import _convert_dict_to_message

    from agentmall.agents.persistence import checkpoint_saver
    from agentmall.retrieval.embedding import DIMENSION, MODEL, REVISION, LocalEncoder

    task = next(t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == task_id)
    ledger = BudgetLedger(
        tmp_path / "synthetic-ledger.json", policy(max_model_calls=12, max_cost_cny="30")
    )
    original_database = fixtures.episode_database
    state, wire_receipts, outstanding = {}, [], {}

    @asynccontextmanager
    async def capture(task, **kwargs):
        assert kwargs == {"embedding": "local"}
        async with original_database(task, **kwargs) as resources:
            encoder = resources["encoder"]
            assert type(encoder) is LocalEncoder
            assert (encoder.model_id, encoder.revision, encoder.dimension) == (
                MODEL,
                REVISION,
                DIMENSION,
            )
            single, multi = fixture_models(
                task.fixture_program,
                task.user_goal.format(**resources["refs"]),
                resources["refs"],
                task.fault.kind,
            )
            state.update(single=single, multi=multi)
            env = resources["env"]
            with env[1].connect() as connection:
                business = dict(
                    connection.execute(
                        text(
                            "SELECT current_database() db, current_user actor, "
                            "current_schema() schema, inet_server_port() port"
                        )
                    )
                    .mappings()
                    .one()
                )
                vector_rows = (
                    connection.execute(
                        text(
                            "SELECT DISTINCT embedding_model, embedding_revision, "
                            "vector_dims(embedding) dimensions FROM knowledge_chunks "
                            "UNION SELECT DISTINCT embedding_model, embedding_revision, "
                            "vector_dims(embedding) dimensions FROM product_search"
                        )
                    )
                    .mappings()
                    .all()
                )
                assert vector_rows
                assert all(tuple(r.values()) == (MODEL, REVISION, DIMENSION) for r in vector_rows)
            async with checkpoint_saver(env[3]) as saver:
                checkpoint = await (
                    await saver.conn.execute(
                        "SELECT current_database() db, current_user actor, "
                        "current_schema() schema, inet_server_port() port"
                    )
                ).fetchone()
            assert business["db"] == checkpoint["db"] == "agentmall_test"
            assert business["actor"] == checkpoint["actor"] == "agentmall"
            assert (
                business["port"] == checkpoint["port"]
            )  # container internal port, not host mapping
            assert business["schema"].startswith("test_") and checkpoint["schema"].startswith("cp_")
            query = encoder.encode(["静音键盘"], query=True)[0]
            assert len(query) == 512 and sum(abs(v) > 1e-8 for v in query) > 400
            state["isolation"] = {
                "business": business,
                "checkpoint": checkpoint,
                "embedding_rows": [dict(row) for row in vector_rows],
            }
            yield resources

    async def wire(request):
        body = json.loads(request.content)
        names = {t["function"]["name"] for t in body["tools"]}
        if names == {"route"}:
            role = "supervisor"
            assert body["tool_choice"] == {"type": "function", "function": {"name": "route"}}
        elif architecture == "single":
            role = "single"
            assert names == set(SCHEMAS)
        else:
            role = next(r for r, allowed in ALLOWLISTS.items() if names == set(allowed))
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        assert body["temperature"] == 0 and not body.get("stream", False)
        assert 0 < body["max_tokens"] <= 2048
        assert ledger.read()["attempts"][-1]["state"] == "RESERVED"
        paired_ids = []
        for message in body["messages"]:
            if message["role"] == "tool":
                ident = message["tool_call_id"]
                assert ident in outstanding
                paired_ids.append(ident)
        messages = [_convert_dict_to_message(m) for m in body["messages"]]
        # OpenAI Tool messages carry tool_call_id, not the fixture helper's name.
        # Recover the name only from a previously emitted call in this mock exchange.
        for message in messages:
            if message.type == "tool":
                message.name = outstanding[message.tool_call_id]
        model = state["single"] if role == "single" else state["multi"][role]
        reply = (
            (await model._agenerate(messages, max_tokens=body["max_tokens"])).generations[0].message
        )
        for call in reply.tool_calls:
            assert call["id"] not in outstanding
            outstanding[call["id"]] = call["name"]
        wire_receipts.append(
            {
                "role": role,
                "url": str(request.url),
                "max_tokens": body["max_tokens"],
                "schema_names": sorted(names),
                "tool_choice": body.get("tool_choice", "auto"),
                "returned_tools": [c["name"] for c in reply.tool_calls],
                "tool_result_ids": paired_ids,
            }
        )
        return httpx.Response(
            200,
            headers={"x-request-id": f"fixture-wire-{len(wire_receipts)}"},
            json=completion(
                reply.content,
                f"fixture-response-{len(wire_receipts)}",
                reply.tool_calls,
                {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            ),
        )

    original_transport = provider.MeteredTransport
    monkeypatch.setattr(run, "episode_database", capture)
    monkeypatch.setattr(
        provider,
        "MeteredTransport",
        lambda ledger, episode: original_transport(
            ledger, episode, inner=httpx.MockTransport(wire)
        ),
    )
    result = await run.run_episode(
        task, architecture, 0, mode="live", live_ledger=ledger, live_key="synthetic-L1-key"
    )
    assert result["success"], {
        k: result.get(k) for k in ("oracle", "harness_error", "simulator_error")
    }
    assert result["cleanup"]["remaining"] == []
    assert result["final"]["checkpoint_counts"]["checkpoints"] > 0
    assert result["final"]["invariants"]["violations"] == []
    assert result["model_calls"] == len(wire_receipts) == len(ledger.read()["attempts"])
    assert any(r["tool_result_ids"] for r in wire_receipts)
    if architecture == "multi":
        assert any(r["role"] == "supervisor" for r in wire_receipts)
    assert all(
        r["state"] == "SETTLED" and r["provider_request_id"].startswith("fixture-wire-")
        for r in ledger.read()["attempts"]
    )
    text_result = json.dumps(result)
    assert "synthetic-L1-key" not in text_result and '"messages"' not in text_result
    receipt(
        f"sdk-{task_id}-{architecture}",
        {
            "evidence_class": "OFFLINE_SDK_MOCK_PG_REAL_BGE",
            "paid_requests": 0,
            "task_id": task_id,
            "architecture": architecture,
            "run_id": result["run_id"],
            "initial_hash": result["initial_hash"],
            "oracle": result["oracle"],
            "wire": wire_receipts,
            "ledger": ledger.read(),
            "isolation": state["isolation"],
            "checkpoint_counts": result["final"]["checkpoint_counts"],
            "cleanup": result["cleanup"],
            "graph_budget": result["graph_budget"],
            "run_events": result["final"]["run_events"],
            "business_counts": {
                k: len(result["final"][k])
                for k in ("orders", "aftersales_cases", "refunds", "confirmations")
            },
            "output_fields": sorted(result),
            "prompt_hashes": json.loads((ROOT / "evals/config/frozen-repaired.yaml").read_text())[
                "prompt_hashes"
            ],
            "embedding_manifest_sha256": hashlib.sha256(
                (ROOT / "evals/data/embedding_manifest.json").read_bytes()
            ).hexdigest(),
        },
    )
