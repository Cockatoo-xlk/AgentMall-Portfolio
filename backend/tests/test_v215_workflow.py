"""CONTRACT_TEST_ONLY: new synthetic phrasing, real SDK/SQL; no historical task replay."""

import json
from uuid import uuid4

import httpx
from aftersales_helpers import delivered_order
from conftest import row
from playground_helpers import SDKProgram
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env
from test_v213_l2_sdk import direct_sdk


async def test_explicit_proposal_and_procurement_preserve_two_independent_confirmations(
    durable_env, buyer, product
):
    env = durable_env
    original = await delivered_order(env[0], buyer, product)
    before = row(
        env[1],
        "SELECT (SELECT count(*) FROM orders) orders, "
        "(SELECT count(*) FROM confirmations) confirmations, "
        "(SELECT count(*) FROM payments) payments",
    )
    wire = SDKProgram("return_replace", original["id"])
    clients = await direct_sdk(env, wire)
    try:
        tid = await thread(env, buyer)
        first = (
            await start(
                env,
                buyer,
                tid,
                message=f"本人订单{original['id']}有质量问题，请生成退货提案；"
                "再推荐另一款静音键盘，整笔预算900元以内，采购两把送演示家庭。",
            )
        ).json()
        assert first["status"] == "WAITING_INPUT", first
        assert first["constraints"]["quantity"] == 2
        assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
        cid1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        rid1 = str(uuid4())
        second = (await resume(env, buyer, tid, first, cid1, rid1)).json()
        assert second["status"] == "WAITING_INPUT", second
        assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
        assert (
            second["pending_confirmation"]["proposal_id"]
            != first["pending_confirmation"]["proposal_id"]
        )
        assert (await resume(env, buyer, tid, second, cid1)).status_code == 409
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == before["orders"]
        cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        rid2 = str(uuid4())
        done = (await resume(env, buyer, tid, second, cid2, rid2)).json()
        assert done["status"] == "COMPLETED", done
        requests = len(wire.requests)
        assert (await resume(env, buyer, tid, first, cid1, rid1)).json() == done
        assert (await resume(env, buyer, tid, second, cid2, rid2)).json() == done
        assert len(wire.requests) == requests
        assert (
            row(env[1], "SELECT count(*) n FROM aftersales_cases WHERE status='REQUESTED'")["n"]
            == 1
        )
        assert row(env[1], "SELECT count(*) n FROM orders WHERE status='PENDING_PAYMENT'")["n"] == 1
        assert (
            row(env[1], "SELECT count(*) n FROM confirmations")["n"] == before["confirmations"] + 2
        )
        assert (
            row(
                env[1],
                "SELECT count(*) n FROM confirmations WHERE id IN (:a,:b) "
                "AND consumed_at IS NOT NULL",
                a=cid1,
                b=cid2,
            )["n"]
            == 2
        )
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == before["payments"]
        assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
        item = row(
            env[1],
            "SELECT oi.quantity,p.reserved,p.id,p.attributes,o.address_label FROM orders o "
            "JOIN order_items oi ON oi.order_id=o.id JOIN products p ON p.id=oi.product_id "
            "WHERE o.status='PENDING_PAYMENT'",
        )
        assert item["quantity"] == item["reserved"] == 2
        assert str(item["id"]) != product and item["address_label"] == "demo_home"
        assert item["attributes"]["noise"] == "较安静"
        observed = [
            json.loads(m["content"])
            for req in wire.requests
            if req["role"] == "supervisor"
            for m in req["body"]["messages"]
            if m["role"] == "user"
        ]
        assert any(
            any(
                outcome["status"] == "EXECUTED" and outcome["action_type"] == "RETURN_REQUEST"
                for outcome in content["action_outcomes"]
            )
            for content in observed
        )
        for key, limit in {"models": 12, "tools": 16, "delegations": 4, "steps": 24}.items():
            assert done["budget"][key] <= limit
    finally:
        await clients.aclose()


async def test_later_sdk_parse_failure_preserves_case_and_consumed_return_confirmation(
    durable_env, buyer, product, monkeypatch
):
    env = durable_env
    original = await delivered_order(env[0], buyer, product)
    transport = SDKProgram.transport

    def with_failure(program, role):
        if role != "shopping":
            return transport(program, role)

        def invalid(request):
            program.requests.append({"role": role, "body": json.loads(request.content)})
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-after-return",
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": "SYNTHETIC_INVALID_MESSAGE",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )

        return httpx.MockTransport(invalid)

    monkeypatch.setattr(SDKProgram, "transport", with_failure)
    wire = SDKProgram("return_replace", original["id"])
    clients = await direct_sdk(env, wire)
    try:
        tid = await thread(env, buyer)
        first = (
            await start(
                env,
                buyer,
                tid,
                message=f"订单{original['id']}质量问题，申请退货并推荐另一款静音键盘；准备购买一件，送演示宿舍。",
            )
        ).json()
        assert first["status"] == "WAITING_INPUT", first
        cid = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        request_id = str(uuid4())
        done = (await resume(env, buyer, tid, first, cid, request_id)).json()
        assert done["status"] == "PARTIAL", done
        assert "MODEL_RESPONSE_INVALID" in done["result"]["error_codes"]
        assert (
            row(env[1], "SELECT count(*) n FROM aftersales_cases WHERE status='REQUESTED'")["n"]
            == 1
        )
        assert (
            row(env[1], "SELECT consumed_at FROM confirmations WHERE id=:id", id=cid)["consumed_at"]
            is not None
        )
        assert row(env[1], "SELECT count(*) n FROM orders WHERE status='PENDING_PAYMENT'")["n"] == 0
        before = len(wire.requests)
        assert (await resume(env, buyer, tid, first, cid, request_id)).json() == done
        assert len(wire.requests) == before
        observation = row(
            env[1],
            "SELECT payload_summary FROM run_events WHERE run_id=:id AND event_type='model_end' "
            "AND payload_summary->>'error_code'='MODEL_RESPONSE_INVALID'",
            id=done["id"],
        )["payload_summary"]
        assert observation["provider_usage_state"] == "OBSERVED_VALID"
        assert observation["output_budget_state"] == "UNRESOLVED"
        assert observation["usage"] == "UNKNOWN"
    finally:
        await clients.aclose()
