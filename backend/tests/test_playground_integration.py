"""Real PostgreSQL, official Checkpoint, domain services and real SDK with MockTransport."""

import json
from uuid import uuid4

import pytest
from conftest import row
from playground_helpers import install_sdk
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env


async def test_runtime_status_is_authenticated_and_disabled_without_provider(durable_env, buyer):
    client = durable_env[0]
    assert (await client.get("/api/v1/agent/runtime")).status_code == 401
    reply = await client.get("/api/v1/agent/runtime", headers=buyer)
    assert reply.status_code == 200
    assert reply.json()["mode"] == "MODEL_DISABLED"


@pytest.mark.parametrize(
    "program,message,expected_tool",
    [
        ("recommend", "推荐一款300元以内静音键盘，不要购买", "retrieve_products"),
        ("orders", "查看我本人的订单状态，不要购买", "list_orders"),
    ],
)
async def test_sdk_model_decides_distinct_real_tool_paths(
    durable_env, buyer, tmp_path, program, message, expected_tool
):
    env = durable_env
    provider, wire = await install_sdk(env, tmp_path, program)
    try:
        tid = await thread(env, buyer)
        response = await start(env, buyer, tid, message=message)
        run = response.json()
        assert response.status_code == 201 and run["status"] == "COMPLETED", run
        events = (
            await env[0].get(f"/api/v1/agent/runs/{run['id']}/events?limit=100", headers=buyer)
        ).json()["items"]
        tools = [e["payload_summary"].get("name") for e in events if e["event_type"] == "tool"]
        assert expected_tool in tools, events
        status = (
            await env[0].get(f"/api/v1/agent/runtime?run_id={run['id']}", headers=buyer)
        ).json()
        assert status["mode"] == "MOCK_TRANSPORT" and status["valid_responses"] >= 3
        assert wire.requests[0]["body"]["tools"][0]["function"]["name"] == "route"
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    finally:
        await provider.close()


async def test_sdk_checkout_independent_confirmation_idempotency_and_restore(
    durable_env, buyer, buyer2, tmp_path
):
    env = durable_env
    provider, wire = await install_sdk(env, tmp_path)
    try:
        tid = await thread(env, buyer)
        rid = str(uuid4())
        first = await start(env, buyer, tid, rid)
        run = first.json()
        assert first.status_code == 201 and run["status"] == "WAITING_INPUT", run
        before = len(wire.requests)
        again = await start(env, buyer, tid, rid)
        assert again.json()["id"] == run["id"] and len(wire.requests) == before
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert (
            await env[0].get(f"/api/v1/agent/runtime?run_id={run['id']}", headers=buyer2)
        ).status_code == 404
        approval = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
        request_id = str(uuid4())
        result = await resume(env, buyer, tid, run, approval, request_id)
        assert result.status_code == 200 and result.json()["status"] == "COMPLETED", result.text
        count = len(wire.requests)
        repeat = await resume(env, buyer, tid, run, approval, request_id)
        assert repeat.status_code == 200 and len(wire.requests) == count
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM business_events")["n"] == 1
        recovered = await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)
        assert recovered.json()["runs"][0]["id"] == run["id"]
        status = (
            await env[0].get(f"/api/v1/agent/runtime?run_id={run['id']}", headers=buyer)
        ).json()
        assert (
            status["requests_reserved"] == len(wire.requests)
            and status["actual_bill_cny"] == "UNKNOWN"
        )
        assert (
            row(env[1], f'SELECT count(*) n FROM "{env[3].checkpoint_schema}".checkpoints')["n"] > 0
        )
    finally:
        await provider.close()


async def test_sdk_return_and_replacement_have_two_confirmations(
    durable_env, buyer, product, tmp_path
):
    from aftersales_helpers import delivered_order

    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    provider, _ = await install_sdk(env, tmp_path, "return_replace", order["id"])
    try:
        tid = await thread(env, buyer)
        run = (
            await start(
                env,
                buyer,
                tid,
                message=f"订单{order['id']}有质量问题，想退掉，再帮我推荐一款500元以内静音键盘准备购买，送演示宿舍",
            )
        ).json()
        assert run["status"] == "WAITING_INPUT", run
        first = run["pending_confirmation"]
        cid = await confirm(env, buyer, first["proposal_id"])
        second = (await resume(env, buyer, tid, run, cid)).json()
        assert second["status"] == "WAITING_INPUT", second
        assert second["pending_confirmation"]["proposal_id"] != first["proposal_id"]
        assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
        wrong = await resume(env, buyer, tid, second, cid)
        assert wrong.status_code == 409
        cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        done = await resume(env, buyer, tid, second, cid2)
        assert done.status_code == 200 and done.json()["status"] == "COMPLETED", done.text
        assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
    finally:
        await provider.close()


@pytest.mark.parametrize("program", ["timeout", "missing_usage", "malicious"])
async def test_sdk_provider_failure_or_payment_tool_cannot_create_business_or_retry(
    durable_env, buyer, tmp_path, program
):
    env = durable_env
    provider, wire = await install_sdk(env, tmp_path, program)
    try:
        tid = await thread(env, buyer)
        run = (await start(env, buyer, tid)).json()
        assert run["status"] == "PARTIAL", run
        assert len(wire.requests) == 1
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
        assert provider.ledger.read()["halted"]
        another = await thread(env, buyer)
        await start(env, buyer, another)
        assert len(wire.requests) == 1
        assert "synthetic provider error" not in json.dumps(run)
    finally:
        await provider.close()


async def test_sdk_single_mode_uses_real_sdk_and_preserves_domain_boundary(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, wire = await install_sdk(env, tmp_path, "orders")
    try:
        tid = await thread(env, buyer, "single")
        run = (await start(env, buyer, tid, message="查询本人的订单，不要下单")).json()
        assert run["status"] == "COMPLETED", run
        assert {r["role"] for r in wire.requests} == {"single"}
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    finally:
        await provider.close()


async def test_same_user_words_follow_changed_model_route_not_keyword_script(
    durable_env, buyer, tmp_path
):
    paths = []
    for program in ["recommend", "orders"]:
        provider, _ = await install_sdk(durable_env, tmp_path / program, program)
        try:
            tid = await thread(durable_env, buyer)
            run = (await start(durable_env, buyer, tid, message="请帮我看看")).json()
            events = (
                await durable_env[0].get(
                    f"/api/v1/agent/runs/{run['id']}/events?limit=100", headers=buyer
                )
            ).json()["items"]
            paths.append(
                [e["payload_summary"].get("name") for e in events if e["event_type"] == "tool"]
            )
        finally:
            await provider.close()
    assert "retrieve_products" in paths[0] and "list_orders" not in paths[0]
    assert "list_orders" in paths[1] and "retrieve_products" not in paths[1]
