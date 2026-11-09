"""Actual SDK wire round-trip and real PostgreSQL; synthetic malformed calls only."""

import json
from contextlib import AsyncExitStack
from uuid import uuid4

import httpx
import pytest
from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import install
from playground_helpers import SDKProgram
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env

from agentmall.infra.llm import deepseek_model


async def direct_sdk(env, wire):
    clients = AsyncExitStack()
    models = {}
    for role in ("supervisor", "shopping", "order", "aftersales"):
        channel = wire.transport(role)
        sync = clients.enter_context(httpx.Client(transport=channel, trust_env=False))
        asynchronous = await clients.enter_async_context(
            httpx.AsyncClient(transport=channel, trust_env=False)
        )
        models[role] = deepseek_model(
            "synthetic-not-live", http_client=sync, http_async_client=asynchronous
        )
    await install(env, models)
    return clients


@pytest.mark.parametrize("fault", ["json", "schema"])
async def test_sdk_b2_repairs_in_place_keeps_reads_and_two_confirmations(
    durable_env, buyer, product, tmp_path, monkeypatch, fault
):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    original = SDKProgram.transport
    checked = []

    def transport(program, role):
        base = original(program, role)

        async def respond(request):
            index = program.counts.get(role, 0)
            body = json.loads(request.content)
            if role == "aftersales" and index == 3:
                content = json.loads(
                    next(m["content"] for m in body["messages"] if m["role"] == "user")
                )
                assert content["orchestration_feedback"]["error_code"] == "INVALID_TOOL_BATCH"
                assert {r["name"] for r in content["prior_tool_results"]} == {
                    "get_order",
                    "check_eligibility",
                    "retrieve_policies",
                }
                c = content["constraints"]
                assert c["max_price_cents"] == 50000 and c["quantity"] == 1
                assert c["noise_preference"] == "quiet" and c["address_label"] == "demo_dorm"
                assert product in c["exclude_product_ids"]
                checked.append(content)
            response = await base.handle_async_request(request)
            if role == "aftersales" and index == 2:
                value = response.json()
                value["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
                    '{"order_id":' if fault == "json" else json.dumps({"order_id": order["id"]})
                )
                return httpx.Response(200, json=value)
            return response

        return httpx.MockTransport(respond)

    monkeypatch.setattr(SDKProgram, "transport", transport)
    wire = SDKProgram("return_replace", order["id"])
    clients = await direct_sdk(env, wire)
    before = row(
        env[1],
        "SELECT (SELECT count(*) FROM orders) orders, "
        "(SELECT count(*) FROM payments) payments, "
        "(SELECT count(*) FROM confirmations) confirmations",
    )
    try:
        tid = await thread(env, buyer)
        first = (
            await start(
                env,
                buyer,
                tid,
                message=f"订单{order['id']}有质量问题，申请退货，再推荐另一款500元以内的静音键盘，并准备购买一件，送演示宿舍。",
            )
        ).json()
        assert first["status"] == "WAITING_INPUT", {
            "status": first["status"],
            "error": first.get("last_error"),
            "result": first.get("result"),
            "counts": wire.counts,
        }
        assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        assert len(checked) == 1 and wire.counts["aftersales"] == 4
        assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
        cid1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        rid1 = str(uuid4())
        second = (await resume(env, buyer, tid, first, cid1, rid1)).json()
        assert second["status"] == "WAITING_INPUT", {
            "error": second.get("last_error"),
            "codes": second["result"]["error_codes"],
            "counts": wire.counts,
            "results": second["result"]["results"],
        }
        assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
        assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == before["orders"]
        assert (await resume(env, buyer, tid, second, cid1)).status_code == 409
        cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        rid2 = str(uuid4())
        done = (await resume(env, buyer, tid, second, cid2, rid2)).json()
        assert done["status"] == "COMPLETED", done
        assert done["budget"]["models"] == 11 and done["budget"]["tools"] == 6
        calls = len(wire.requests)
        assert (await resume(env, buyer, tid, second, cid2, rid2)).json() == done
        assert (await resume(env, buyer, tid, first, cid1, rid1)).json() == done
        assert len(wire.requests) == calls
        assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == before["orders"] + 1
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == before["payments"]
        assert (
            row(env[1], "SELECT count(*) n FROM confirmations")["n"] == before["confirmations"] + 2
        )
        item = row(
            env[1],
            "SELECT oi.product_id,oi.quantity,oi.unit_price_cents,p.attributes,p.reserved "
            "FROM order_items oi JOIN orders o ON o.id=oi.order_id "
            "JOIN products p ON p.id=oi.product_id WHERE o.status='PENDING_PAYMENT'",
        )
        assert str(item["product_id"]) != product and item["quantity"] == item["reserved"] == 1
        assert item["unit_price_cents"] <= 50000 and item["attributes"]["noise"] == "较安静"
        errors = row(
            env[1], "SELECT count(*) n FROM run_events WHERE event_type='tool_batch_rejected'"
        )
        assert errors["n"] == 1
        detail = row(
            env[1], "SELECT payload_summary FROM run_events WHERE event_type='tool_batch_rejected'"
        )["payload_summary"]
        assert detail["diagnostic_code"] == (
            "TOOL_ARGUMENT_JSON_INVALID" if fault == "json" else "TOOL_ARGUMENT_SCHEMA_INVALID"
        )
        assert detail["tools_executed"] is False
        assert detail["tool_names"] == ["prepare_return"]
        assert detail["repair_consumed"] is False
    finally:
        await clients.aclose()


@pytest.mark.parametrize("fault", ["duplicate", "policy", "exhausted"])
async def test_sdk_nonrecoverable_or_second_repair_stops_without_new_writes(
    durable_env, buyer, product, monkeypatch, fault
):
    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    original = SDKProgram.transport

    def transport(program, role):
        base = original(program, role)

        async def respond(request):
            index = program.counts.get(role, 0)
            response = await base.handle_async_request(request)
            if (fault != "exhausted" and role == "aftersales" and index == 2) or (
                fault == "exhausted"
                and role in {"aftersales", "order"}
                and index == (2 if role == "aftersales" else 0)
            ):
                value = response.json()
                function = value["choices"][0]["message"]["tool_calls"][0]["function"]
                if fault == "duplicate":
                    function["arguments"] = (
                        '{"order_id":"'
                        + order["id"]
                        + '","order_id":"'
                        + order["id"]
                        + '","reason_code":"QUALITY_ISSUE","description":"synthetic"}'
                    )
                elif fault == "policy":
                    function["name"] = "execute_confirmed_action"
                    function["arguments"] = "{}"
                else:
                    function["arguments"] = "{}"
                return httpx.Response(200, json=value)
            return response

        return httpx.MockTransport(respond)

    monkeypatch.setattr(SDKProgram, "transport", transport)
    wire = SDKProgram("return_replace", order["id"])
    clients = await direct_sdk(env, wire)
    try:
        tid = await thread(env, buyer)
        first = (
            await start(
                env,
                buyer,
                tid,
                message=f"订单{order['id']}质量问题，申请退货，再推荐另一款500元以内静音键盘并准备购买一件，送演示宿舍",
            )
        ).json()
        if fault == "exhausted":
            assert first["status"] == "WAITING_INPUT", first
            cid = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
            first = (await resume(env, buyer, tid, first, cid)).json()
            assert wire.counts["order"] == 1  # no second specialist-local repair allowance
        else:
            assert wire.counts["aftersales"] == 3  # policy/duplicate failures do not retry
        assert first["status"] == "PARTIAL", first
        assert first["result"]["error_codes"]
        assert first["budget"]["models"] <= 12
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == (
            1 if fault == "exhausted" else 0
        )
        if fault == "exhausted":
            exhausted = row(
                env[1],
                "SELECT payload_summary FROM run_events "
                "WHERE event_type='orchestration_repair_exhausted' ORDER BY seq LIMIT 1",
            )["payload_summary"]
            assert exhausted["failure_class"] == "REPAIR_EXHAUSTED"
            assert exhausted["repair_consumed"] is True
        else:
            with env[1].connect() as connection:
                from sqlalchemy import text

                observed = (
                    connection.execute(
                        text(
                            "SELECT payload_summary FROM run_events "
                            "WHERE event_type='tool_batch_rejected'"
                        )
                    )
                    .scalars()
                    .all()
                )
            assert len(observed) == 1, observed
            detail = row(
                env[1],
                "SELECT payload_summary FROM run_events WHERE event_type='tool_batch_rejected'",
            )["payload_summary"]
            assert detail["diagnostic_code"] == (
                "TOOL_ARGUMENT_DUPLICATE_KEY" if fault == "duplicate" else "TOOL_NOT_ALLOWLISTED"
            )
            assert detail["repairable"] is False
    finally:
        await clients.aclose()
