"""DEVELOPMENT / CONTRACT_TEST_ONLY. Real PG/API/SDK; never the new Live inputs."""

import json
from time import perf_counter, time
from uuid import uuid4

import httpx
import pytest
from evals.smoke_runner import SmokeBatch, SmokeStopped, load_verified
from evals.smoke_session import SmokeSession, sql_facts
from playground_helpers import SDKProgram
from retrieval_helpers import FixtureEncoder
from test_v217_live1_transport import price
from test_v217_smoke_contract import proposal


class SingleWire:
    def transport(self, role):
        def respond(request):
            body = json.loads(request.content)
            state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            tools = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            done = any(
                f["kind"] == "proposal" and f["data"]["status"] in {"EXECUTED", "REJECTED"}
                for f in state.get("committed_facts", [])
            )
            call = None
            if not done and not tools:
                call = ("retrieve_products", {"query": "静音键盘"})
            elif (
                not done
                and state["constraints"]["purchase_requested"]
                and tools
                and not any(t.get("action_type") for t in tools)
            ):
                call = ("prepare_checkout", {"product_id": tools[0]["data"]["items"][0]["id"]})
            message = {"role": "assistant", "content": '{"terminal":"finish"}'}
            if call:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_" + uuid4().hex,
                            "type": "function",
                            "function": {"name": call[0], "arguments": json.dumps(call[1])},
                        }
                    ],
                }
            return httpx.Response(
                200,
                json={
                    "id": "dev_" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if call else "stop",
                            "message": message,
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                },
            )

        return httpx.MockTransport(respond)


async def test_full_api_single_multi_operator_and_freeze_lifecycle(env, tmp_path, record_property):
    from evals.smoke_cli import prepare_resume_command

    timings = []

    async def timed(stage, operation):
        start = perf_counter()
        result = await operation
        timings.append({"stage": stage, "seconds": perf_counter() - start})
        return result

    p = proposal()
    p["tasks"][0]["user_request"] = "推荐一款300元以内静音键盘，仅供选择，不购买。"
    # Product max_price is a total purchase constraint: two299yuan items need598.
    # This development contract input is not one of the frozen Smoke inputs.
    p["tasks"][1]["user_request"] = "预算600元，推荐静音键盘，准备购买两件，送演示宿舍。"
    p["tasks"][2]["user_request"] = (
        "订单{delivered_order_id}有质量问题，申请退货，再推荐另一款500元以内静音键盘准备购买一件，送演示宿舍。"
    )
    p["tasks"][2]["fixture"]["original_product"] = "静音 K87"
    epoch, monotonic_start = time(), perf_counter()
    # Real elapsed test time, resilient to VM/NTP wall-clock adjustments. The
    # production rollback guard remains unchanged and is tested separately.
    g = SmokeBatch(
        tmp_path / "batch.json",
        p,
        "c" * 64,
        clock=lambda: epoch + perf_counter() - monotonic_start,
    )
    sql = []
    schemas = []
    for index, task in enumerate(p["tasks"]):
        g.arm(task["id"])
        s = SmokeSession(g, tmp_path / task["id"])
        wire = SDKProgram("return_replace") if index == 2 else SingleWire()

        def transport(role, wire=wire, s=s):
            if isinstance(wire, SDKProgram):
                wire.order_id = s.setup["order_id"]
            return wire.transport(role)

        try:
            await timed(
                f"{index}:initialize",
                s.initialize(
                    env[3].database_url.get_secret_value(),
                    price(),
                    encoder_factory=FixtureEncoder,
                    transport_factory=transport,
                ),
            )
            schemas.append(s.settings.db_schema)
            run = await timed(f"{index}:start-to-first-result", s.start())
            before = sql_facts(s.settings)
            if index == 0:
                assert run["status"] == "COMPLETED"
                assert not before["orders"] and not before["confirmations"]
            else:
                assert run["status"] == "WAITING_INPUT", run
                first = await timed(f"{index}:inspect-first", s.inspect())
                expected = "RETURN_REQUEST" if index == 2 else "CHECKOUT"
                assert first["proposal"]["action_type"] == expected
                assert len(before["orders"]) == (index == 2)
                # Exercise the real API denial too, rather than just the local adapter.
                from evals.controlled_offline import Operator

                model_calls = len(s.provider.ledger.read()["attempts"])
                with pytest.raises(httpx.HTTPStatusError):
                    await Operator(s.client, s.auth).resume(
                        s.thread_id, first, str(uuid4()), str(uuid4())
                    )
                assert len(s.provider.ledger.read()["attempts"]) == model_calls
                with pytest.raises(
                    SmokeStopped,
                    match="EXPLICIT_OPERATOR_DECISION_REQUIRED|CONFIRMATION_BINDING_INVALID",
                ):
                    await s.resume(first, str(uuid4()), str(uuid4()))
                c1 = await timed(
                    f"{index}:explicit-first-approval",
                    s.decide(first, "approve", operator="TEST_OPERATOR_CODEX"),
                )
                assert len(sql_facts(s.settings)["orders"]) == len(before["orders"])
                command = prepare_resume_command(first, c1)
                rid = command["request_id"]
                run = await timed(
                    f"{index}:explicit-first-resume",
                    s.resume(first, command["confirmation_id"], rid),
                )
                if index == 2:
                    assert run["status"] == "WAITING_INPUT", run
                    middle = sql_facts(s.settings)
                    assert len(middle["cases"]) == 1 and len(middle["orders"]) == 1
                    second = await timed(f"{index}:inspect-second", s.inspect())
                    assert second["proposal"]["action_type"] == "CHECKOUT"
                    with pytest.raises(SmokeStopped, match="CONFIRMATION_BINDING_INVALID"):
                        await s.resume(second, c1["confirmation_id"], str(uuid4()))
                    c2 = await timed(
                        f"{index}:explicit-second-approval",
                        s.decide(second, "approve", operator="TEST_OPERATOR_CODEX"),
                    )
                    assert c1["confirmation_id"] != c2["confirmation_id"]
                    command = prepare_resume_command(second, c2)
                    rid = command["request_id"]
                    run = await timed(
                        f"{index}:explicit-second-resume",
                        s.resume(second, command["confirmation_id"], rid),
                    )
                    original = second
                    cid = c2["confirmation_id"]
                else:
                    original, cid = first, c1["confirmation_id"]
                assert run["status"] == "COMPLETED", run
                budget = run["budget"]
                assert await s.resume(original, cid, rid) == run
                assert run["budget"] == budget
                assert (
                    await Operator(s.client, s.auth).resume(s.thread_id, original, cid, rid) == run
                )
                assert len(s.provider.ledger.read()["attempts"]) == run["budget"]["models"]
                with pytest.raises(SmokeStopped, match="IDEMPOTENCY_CONFLICT"):
                    await s.resume(original, str(uuid4()), rid)
                after = sql_facts(s.settings)
                assert len(after["orders"]) == len(s.baseline["orders"]) + 1
                assert after["payments"] == s.baseline["payments"]
                assert after["refunds"] == s.baseline["refunds"] == 0
            value, evidence = await s.freeze_export_verify()
            assert load_verified(s.directory) == evidence
            assert evidence["ledger"]["halted"] is None
            assert all(a["state"] == "SETTLED" for a in evidence["ledger"]["attempts"])
            assert evidence["after"]["checkpoint_count"] > 0
            assert len(evidence["after"]["runs"]) == 1
            assert evidence["after"]["runs"][0]["has_lock"] is False
            sql.append(evidence)
            # Completion of contract evidence is explicit; no automatic next task.
            g.verified(value)
            assert hasattr(s, "cleanup"), "Verified exact-schema cleanup is missing"
            await s.close()
            assert (s.directory / "clients-closed.json").exists()
            # A new HTTP client reads persisted Run/checkpoint state after client shutdown;
            # no Recover, Resume, new model or new execution is invoked.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=s.app), base_url="http://127.0.0.1"
            ) as reopened:
                readback = await reopened.get(
                    "/api/v1/agent/threads/" + s.thread_id, headers=s.auth
                )
                assert readback.status_code == 200
                assert readback.json()["runs"][0]["id"] == run["id"]
                assert readback.json()["runs"][0]["status"] == "COMPLETED"
            await s.cleanup("CONTRACT_TEST_ONLY-owned-cleanup")
        finally:
            await s.close()
    assert len(set(schemas)) == 3
    assert g.read()["task_fee_holds_cny"] == "7.50"
    assert len(sql[1]["after"]["orders"]) == 1 and len(sql[2]["after"]["orders"]) == 2
    record_property("CONTRACT_TEST_ONLY_stage_timings", json.dumps(timings))
