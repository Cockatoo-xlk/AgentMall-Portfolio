"""CONTRACT_TEST_ONLY: explicit selection reuses the existing smoke lifecycle."""

from uuid import uuid4

import pytest
from evals.smoke_runner import SmokeBatch, SmokeStopped
from test_v217_smoke_contract import proposal


def test_selected_ac_preserves_original_case_identity_and_two_task_fee_hold(tmp_path):
    g = SmokeBatch(
        tmp_path / "batch.json", proposal(), "d" * 64, task_ids=["contract-A", "contract-C"]
    )
    assert g.read()["task_order"] == ["contract-A", "contract-C"]
    assert g.read()["batch_cost_limit_cny"] == "5.00"
    g.arm("contract-A")
    assert g.case_index() == 0
    g.initialized(str(uuid4()), "test_" + uuid4().hex, "cp_" + uuid4().hex)
    g.start_episode()
    g.end_episode()
    g.verified("a" * 64)
    with pytest.raises(SmokeStopped, match="TASK_ORDER"):
        g.arm("contract-B")
    g.arm("contract-C")
    assert g.case_index() == 2
    assert g.current_task()["architecture"] == "multi"
    assert g.current_task()["required_human_decisions"] == 2
    assert g.read()["task_fee_holds_cny"] == "5.00"
    assert [t["task_id"] for t in g.read()["tasks"]] == ["contract-A", "contract-C"]


@pytest.mark.parametrize(
    "selected", [[], ["contract-C", "contract-A"], ["contract-A", "contract-A"], ["unknown"]]
)
def test_invalid_selection_rejected_without_state_or_resources(tmp_path, selected):
    with pytest.raises(SmokeStopped, match="TASK_SELECTION_INVALID"):
        SmokeBatch(tmp_path / "batch.json", proposal(), "d" * 64, task_ids=selected)
    assert not list(tmp_path.iterdir())


def test_selection_is_immutable_on_reattach_and_does_not_authorize_live(tmp_path):
    SmokeBatch(tmp_path / "batch.json", proposal(), "d" * 64, task_ids=["contract-A", "contract-C"])
    with pytest.raises(SmokeStopped, match="EXECUTION_BINDING_MISMATCH"):
        SmokeBatch(tmp_path / "batch.json", proposal(), "d" * 64)
    with pytest.raises(SmokeStopped, match="OWNER_AUTHORIZATION_REQUIRED"):
        SmokeBatch(
            tmp_path / "live.json",
            proposal(),
            "d" * 64,
            task_ids=["contract-A", "contract-C"],
            mode="LIVE_DEEPSEEK",
        )
    assert not (tmp_path / "live.json").exists()


def test_original_three_task_default_is_preserved(tmp_path):
    g = SmokeBatch(tmp_path / "batch.json", proposal(), "d" * 64)
    assert g.read()["task_order"] == ["contract-A", "contract-B", "contract-C"]
    assert g.read()["batch_cost_limit_cny"] == "7.50"


@pytest.mark.real_bge
async def test_selected_ac_real_bge_formal_api_sql(tmp_path, record_property):
    """Offline scripted operator assertions are not evidence of human Live latency."""
    import json
    import os
    from time import perf_counter, time

    import httpx
    from evals.controlled_offline import Operator
    from evals.smoke_assertions import score_verified
    from evals.smoke_cli import prepare_resume_command
    from evals.smoke_session import SmokeSession, sql_facts
    from playground_helpers import SDKProgram
    from test_v217_live1_transport import price
    from test_v217_live2_product_contract import frozen_proposal

    from agentmall.retrieval.embedding import LocalEncoder, validate_vectors

    p = frozen_proposal()
    selected = [p["tasks"][i]["id"] for i in (0, 2)]
    encoder = LocalEncoder()
    vector = encoder.encode(["CONTRACT_TEST_ONLY 静音键盘"], query=True)
    validate_vectors(encoder, vector, 1)
    assert str(next(encoder.model.parameters()).device) == "cpu"
    epoch, mono = time(), perf_counter()
    gate = SmokeBatch(
        tmp_path / "batch.json",
        p,
        "e" * 64,
        task_ids=selected,
        clock=lambda: epoch + perf_counter() - mono,
    )
    timings, results = [], []

    async def timed(case, stage, operation):
        start = perf_counter()
        result = await operation
        timings.append({"case": case, "stage": stage, "seconds": perf_counter() - start})
        return result

    for task_id in selected:
        row = gate.arm(task_id)
        index = gate.case_index()
        session = SmokeSession(gate, tmp_path / row["execution_id"])
        wire = SDKProgram("return_replace")
        explored = set()

        def transport(role, *, index=index, wire=wire, session=session, explored=explored):
            if index == 2:
                wire.order_id = session.setup["order_id"]
                return wire.transport(role)

            def compare(request):
                body = json.loads(request.content)
                tools = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
                for tool in tools:
                    explored.update(item["id"] for item in tool.get("data", {}).get("items", []))
                message = {"role": "assistant", "content": '{"terminal":"finish"}'}
                queries = ["静音键盘", "有线静音键盘", "无线静音键盘"]
                if len(tools) < len(queries):
                    message = {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "contract_" + uuid4().hex,
                                "type": "function",
                                "function": {
                                    "name": "retrieve_products",
                                    "arguments": json.dumps({"query": queries[len(tools)]}),
                                },
                            }
                        ],
                    }
                return httpx.Response(
                    200,
                    json={
                        "id": "contract_" + uuid4().hex,
                        "model": "deepseek-flash",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "tool_calls"
                                if len(tools) < len(queries)
                                else "stop",
                                "message": message,
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 30,
                            "total_tokens": 130,
                        },
                    },
                )

            return httpx.MockTransport(compare)

        try:
            await timed(
                index,
                "initialize_real_bge_indices",
                session.initialize(
                    os.environ["AGENTMALL_TEST_DATABASE_URL"],
                    price(),
                    encoder_factory=lambda: encoder,
                    transport_factory=transport,
                ),
            )
            run = await timed(
                index,
                "start_to_first_proposal_or_result",
                session.start(expected_context_version=0),
            )
            confirmations = []
            if index == 0:
                assert run["status"] == "COMPLETED", run
                visible = {f["id"] for f in run["result"]["facts"] if f["kind"] == "product"}
                assert len(visible) == 2 and visible <= explored
                assert len(explored) > len(visible)  # Exploration is not the final recommendation.
                thread = await session.client.get(
                    f"/api/v1/agent/threads/{session.thread_id}", headers=session.auth
                )
                candidates = thread.json()["context"]["candidate_sets"]
                assert len(candidates) == 1
                assert {item["id"] for item in candidates[0]["items"]} == visible
            else:
                assert run["status"] == "WAITING_INPUT", run
                first = await timed(index, "inspect_return", session.inspect())
                assert first["proposal"]["action_type"] == "RETURN_REQUEST"
                assert (
                    first["proposal"]["canonical_payload"]["order_id"] == session.setup["order_id"]
                )
                c1 = await timed(
                    index,
                    "explicit_return_test_approval",
                    session.decide(first, "approve", operator="TEST_OPERATOR_CODEX"),
                )
                confirmations.append(c1["confirmation_id"])
                cmd = prepare_resume_command(first, c1)
                run = await timed(
                    index,
                    "explicit_return_resume_to_second_proposal",
                    session.resume(first, cmd["confirmation_id"], cmd["request_id"]),
                )
                assert run["status"] == "WAITING_INPUT", run
                middle = sql_facts(session.settings)
                assert len(middle["cases"]) == 1 and len(middle["orders"]) == 1
                second = await timed(index, "inspect_purchase", session.inspect())
                assert second["proposal"]["action_type"] == "CHECKOUT"
                payload = second["proposal"]["canonical_payload"]
                assert len(payload["items"]) == 1 and payload["items"][0]["quantity"] == 1
                assert payload["total_cents"] <= 25000
                with pytest.raises(SmokeStopped, match="CONFIRMATION_BINDING_INVALID"):
                    await session.resume(second, c1["confirmation_id"], str(uuid4()))
                c2 = await timed(
                    index,
                    "explicit_purchase_test_approval",
                    session.decide(second, "approve", operator="TEST_OPERATOR_CODEX"),
                )
                confirmations.append(c2["confirmation_id"])
                assert confirmations[0] != confirmations[1]
                cmd = prepare_resume_command(second, c2)
                run = await timed(
                    index,
                    "explicit_purchase_resume",
                    session.resume(second, cmd["confirmation_id"], cmd["request_id"]),
                )
                assert run["status"] == "COMPLETED", run
                before_replay = sql_facts(session.settings)
                count = len(session.provider.ledger.read()["attempts"])
                assert (
                    await Operator(session.client, session.auth).resume(
                        session.thread_id, second, cmd["confirmation_id"], cmd["request_id"]
                    )
                    == run
                )
                assert sql_facts(session.settings) == before_replay
                assert len(session.provider.ledger.read()["attempts"]) == count
            value, evidence = await session.freeze_export_verify()
            assert evidence["case_index"] == index
            assertion = score_verified(session.directory)
            assert assertion["status"] == "PASS", assertion
            assert evidence["after"]["checkpoint_count"] > 0
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=session.app), base_url="http://readback"
            ) as reopened:
                read = await reopened.get(
                    f"/api/v1/agent/threads/{session.thread_id}", headers=session.auth
                )
                assert read.status_code == 200
                assert read.json()["runs"][0]["id"] == run["id"]
                assert read.json()["runs"][0]["status"] == "COMPLETED"
            results.append(
                {
                    "task_id": task_id,
                    "original_case_index": index,
                    "assertion": assertion,
                    "evidence_sha256": value,
                    "execution_id": row["execution_id"],
                    "confirmations": confirmations,
                    "explored_product_ids": sorted(explored),
                    "episode_seconds": gate.read()["tasks"][-1]["episode_finished_at"]
                    - gate.read()["tasks"][-1]["episode_started_at"],
                }
            )
            gate.verified(value)
            await session.close()
            await session.cleanup("POSTFIX_OFFLINE_ONLY_EXACT_OWNED_SCHEMAS")
        finally:
            await session.close()
    assert [task["task_id"] for task in gate.read()["tasks"]] == selected
    assert gate.read()["task_fee_holds_cny"] == "5.00"
    record_property("postfix_ac_offline_results", json.dumps(results))
    record_property("postfix_ac_offline_timings", json.dumps(timings))
