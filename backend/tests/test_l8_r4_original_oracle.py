"""Original DEV/TEST contracts over SDK Mock HTTP and owned PostgreSQL.

This intentionally tests the formal runtime guard, not the frozen private Native
pre-SDK response contract. No Oracle expected fields enter fixture model inputs.
CI_OFFLINE_CORE uses FixtureEncoder; LOCAL_FULL_WITH_BGE keeps real local BGE.
"""

import json
from contextlib import AsyncExitStack
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from evals.fixture_model import fixture_models
from evals.fixtures import episode_database
from evals.oracles import assess, read_snapshot
from evals.schema import load_tasks
from langchain_core.messages import AIMessage, ToolMessage, convert_to_messages
from t09_helpers import confirm, resume, start, thread

from agentmall.agents.context import Constraints, MultiRequest, user_constraints
from agentmall.agents.persistence import checkpoint_config, checkpoint_saver
from agentmall.infra.llm import deepseek_model

ROOT = Path(__file__).resolve().parents[2]


async def sdk_models(task, resources, architecture, stack):
    env, refs = resources["env"], resources["refs"]
    goal = task.user_goal.format(**refs)
    single, multi = fixture_models(task.fixture_program, goal, refs, task.fault.kind)
    decisions = {"single": single} if architecture == "single" else multi
    calls = []
    models = {}
    for role, model in decisions.items():

        async def respond(request, model=model, role=role):
            body = json.loads(request.content)
            assert "expected" not in body
            names, messages = {}, []
            for message in convert_to_messages(body["messages"]):
                if isinstance(message, AIMessage):
                    names.update({c["id"]: c["name"] for c in message.tool_calls})
                if isinstance(message, ToolMessage) and message.name is None:
                    message = message.model_copy(update={"name": names[message.tool_call_id]})
                messages.append(message)
            msg = await model.bind_tools(body["tools"]).ainvoke(
                messages, max_tokens=body["max_tokens"]
            )
            calls.append({"role": role, "tools": [c["name"] for c in msg.tool_calls]})
            tools = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": json.dumps(c["args"], ensure_ascii=False),
                    },
                }
                for c in msg.tool_calls
            ]
            return httpx.Response(
                200,
                json={
                    "id": "r4-mock-" + str(len(calls)),
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if tools else "stop",
                            "message": {
                                "role": "assistant",
                                "content": msg.content or "",
                                "tool_calls": tools,
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": msg.usage_metadata["input_tokens"],
                        "completion_tokens": msg.usage_metadata["output_tokens"],
                        "total_tokens": msg.usage_metadata["total_tokens"],
                    },
                },
            )

        transport = httpx.MockTransport(respond)
        sync = stack.enter_context(httpx.Client(transport=transport, trust_env=False))
        client = await stack.enter_async_context(
            httpx.AsyncClient(transport=transport, trust_env=False)
        )
        models[role] = deepseek_model(
            "synthetic-not-live", http_client=sync, http_async_client=client
        )
    if architecture == "single":
        env[2].state.durable_single_model = models["single"]
    else:
        env[2].state.multi_models = models
    return calls


@pytest.mark.parametrize(
    "task_id,architecture,dataset",
    [
        ("eval_test_S1_03", "single", "agent_test.jsonl"),
        ("eval_dev_B2_01", "multi", "agent_dev.jsonl"),
    ],
)
async def test_original_task_oracle_and_committed_business_state(
    task_id, architecture, dataset, record_property, pytestconfig
):
    task = next(t for t in load_tasks(ROOT / "evals/data" / dataset) if t.task_id == task_id)
    embedding = "fixture" if pytestconfig.getoption("--ci-offline-core") else "local"
    async with AsyncExitStack() as stack:
        resources = await stack.enter_async_context(episode_database(task, embedding=embedding))
        env, refs = resources["env"], resources["refs"]
        auth = resources["auth"][task.actor]
        initial = read_snapshot(env)
        from sqlalchemy import text

        with env[1].connect() as connection:
            actors_before = (
                connection.execute(text("SELECT * FROM users ORDER BY id")).mappings().all()
            )
        calls = await sdk_models(task, resources, architecture, stack)
        tid = await thread(env, auth, architecture)
        goal = task.user_goal.format(**refs)
        body = {"request_id": str(uuid4()), "message": goal}
        choices = [
            d.quantity
            for d in task.user_script.decisions
            if d.action_type == "CHECKOUT" and d.quantity
        ]
        if choices:
            body["constraints"] = user_constraints(
                MultiRequest(
                    request_id=body["request_id"],
                    thread_id=tid,
                    message=goal,
                    constraints=Constraints(quantity=choices[0]),
                )
            ).model_dump(mode="json")
        response = await env[0].post(f"/api/v1/agent/threads/{tid}/runs", headers=auth, json=body)
        assert response.status_code == 201, response.text
        run = response.json()
        approvals = []
        if task_id == "eval_dev_B2_01":
            assert run["status"] == "WAITING_INPUT"
            assert run["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
            pid1 = run["pending_confirmation"]["proposal_id"]
            inspect1 = await env[0].get(f"/api/v1/proposals/{pid1}", headers=auth)
            assert (
                inspect1.status_code == 200 and inspect1.json()["action_type"] == "RETURN_REQUEST"
            )
            assert len(read_snapshot(env)["aftersales_cases"]) == len(initial["aftersales_cases"])
            cid1 = await confirm(env, auth, pid1)
            req1 = str(uuid4())
            first = run
            second_response = await resume(env, auth, tid, first, cid1, req1)
            assert second_response.status_code == 200, second_response.text
            second = second_response.json()
            assert (
                second["status"] == "WAITING_INPUT"
                and second["pending_confirmation"]["action_type"] == "CHECKOUT"
            )
            mid = read_snapshot(env)
            assert len(mid["aftersales_cases"]) == len(initial["aftersales_cases"]) + 1
            assert len(mid["orders"]) == len(initial["orders"])
            assert (await resume(env, auth, tid, second, cid1)).status_code == 409
            pid2 = second["pending_confirmation"]["proposal_id"]
            inspect2 = await env[0].get(f"/api/v1/proposals/{pid2}", headers=auth)
            assert inspect2.status_code == 200 and inspect2.json()["action_type"] == "CHECKOUT"
            assert pid1 != pid2
            cid2 = await confirm(env, auth, pid2)
            assert cid1 != cid2
            req2 = str(uuid4())
            done = await resume(env, auth, tid, second, cid2, req2)
            assert done.status_code == 200, done.text
            run = done.json()
            assert run["status"] == "COMPLETED"
            before_replay = len(calls)
            assert (await resume(env, auth, tid, second, cid2, req2)).json() == run
            assert (await resume(env, auth, tid, first, cid1, req1)).json() == run
            assert len(calls) == before_replay
            approvals = [
                {
                    "operator": "TEST_OPERATOR_CODEX",
                    "action": "RETURN_REQUEST",
                    "proposal_id": pid1,
                    "confirmation_id": cid1,
                },
                {
                    "operator": "TEST_OPERATOR_CODEX",
                    "action": "CHECKOUT",
                    "proposal_id": pid2,
                    "confirmation_id": cid2,
                },
            ]
        else:
            assert run["status"] == "PARTIAL" and run["result"]["error_codes"] == [
                "INVALID_TOOL_BATCH"
            ]
            assert calls[0]["tools"] == ["retrieve_products"]
        final = read_snapshot(env)
        with env[1].connect() as connection:
            assert (
                connection.execute(text("SELECT * FROM users ORDER BY id")).mappings().all()
                == actors_before
            )
        observed = [
            e["payload_summary"].get("name")
            for e in final["run_events"]
            if e["event_type"] == "tool"
        ]
        verdict = assess(
            task,
            initial,
            final,
            run["result"] or {},
            refs
            | {
                "run_status": run["status"],
                "observed_tools": observed,
                "agent_result_resources": final,
            },
        )
        assert verdict["success"] is True, verdict
        async with checkpoint_saver(env[3]) as saver:
            saved = await saver.aget_tuple(checkpoint_config(UUID(tid), UUID(run["id"])))
            assert saved is not None and not saved.pending_writes
        from conftest import row

        stored = row(
            env[1], "SELECT worker_token,lock_pid,status FROM agent_runs WHERE id=:id", id=run["id"]
        )
        assert (
            stored["worker_token"] is None
            and stored["lock_pid"] is None
            and stored["status"] == run["status"]
        )
        for name in ["models", "tools", "delegations", "steps"]:
            assert (
                run["budget"][name]
                <= {"models": 12, "tools": 16, "delegations": 4, "steps": 24}[name]
            )
        receipt = {
            "task_id": task_id,
            "architecture": architecture,
            "evidence": "DEVELOPMENT_REGRESSION_SDK_MOCK_PG",
            "embedding": {
                "kind": "FIXTURE" if embedding == "fixture" else "REAL_LOCAL_BGE",
                "model": resources["encoder"].model_id,
                "revision": resources["encoder"].revision,
            },
            "oracle": verdict,
            "run_status": run["status"],
            "budget": run["budget"],
            "sdk_http_calls": len(calls),
            "approvals": approvals,
            "delta": {
                k: len(final[k]) - len(initial[k])
                for k in ["orders", "aftersales_cases", "payments", "refunds", "confirmations"]
            },
            "checkpoint": {"present": True, "pending_writes": 0},
            "fence_cleared": True,
            "actor_rows_unchanged": True,
        }
        if task_id == "eval_test_S1_03":
            assert final["products"] == initial["products"]
            assert final["action_proposals"] == initial["action_proposals"]
            # Same Thread remains available after the guard's legitimate terminal rejection.
            followup = await start(env, auth, tid, message="查询键盘，不要购买")
            assert followup.status_code == 201 and followup.json()["id"] != run["id"], followup.text
            receipt["thread_reusable"] = True
        record_property("r4_receipt", json.dumps(receipt, ensure_ascii=False))
        print("R4_ORIGINAL_ORACLE", json.dumps(receipt, ensure_ascii=False))
