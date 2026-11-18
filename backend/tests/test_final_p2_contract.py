"""CONTRACT_TEST_ONLY: scoped requirements and post-transaction continuation."""

import json
from uuid import uuid4

import httpx
import pytest
from aftersales_helpers import delivered_order
from conftest import row
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env
from test_post_holdout_product_fix import (
    ReadAfterCheckoutWire,
    RepeatCheckoutWire,
    attach_wire,
)

from agentmall.agents.context import MultiRequest, user_constraints
from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.infra.errors import DomainError


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize(
    "constraint",
    [
        "退货后新鼠标必须有线",
        "退掉旧商品以后鼠标必须有线",
        "原订单的替换鼠标必须有线",
        "原订单的鼠标要换成有线鼠标",
        "原订单的鼠标退掉后改用有线鼠标",
        "原订单退货后鼠标必须有线",
    ],
)
def test_new_item_constraints_survive_return_time_phrases(threaded, constraint):
    message = (
        "订单123的耳机坏了，请申请质量退货；另外帮我购买一只无线鼠标，"
        + constraint
        + "，送演示家庭。"
    )
    with pytest.raises(DomainError) as error:
        if threaded:
            resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
        else:
            user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("threaded", [False, True])
def test_original_reference_can_constrain_replacement_without_new_marker(threaded):
    message = (
        "订单123的鼠标坏了，请申请质量退货；另外帮我购买一只鼠标，"
        "原订单的鼠标要换成有线鼠标，送演示家庭。"
    )
    if threaded:
        actual = resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))[1]
    else:
        actual = user_constraints(
            MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
        ).model_dump()
    assert actual["product_needs"]["connection"] == "有线"


@pytest.mark.parametrize("threaded", [False, True])
def test_explicit_old_item_scoped_but_new_item_requirement_retained(threaded):
    message = (
        "我的原订单里的有线耳机坏了，请申请质量退货；另外帮我购买一只鼠标，"
        "退货后新鼠标必须无线，送演示家庭。"
    )
    if threaded:
        actual = resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))[1]
    else:
        actual = user_constraints(
            MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
        ).model_dump()
    assert actual["category"] == "mouse"
    assert actual["product_needs"]["connection"] == "无线"


@pytest.mark.parametrize("extra", ["并查一下本人的全部订单", "另帮我看一下自己的订单列表"])
async def test_checkout_receipt_does_not_prove_independent_query(
    durable_env, buyer, tmp_path, extra
):
    env = durable_env
    provider = await attach_wire(env, tmp_path, ReadAfterCheckoutWire())
    try:
        tid = await thread(env, buyer, "single")
        waiting = (
            await start(
                env,
                buyer,
                tid,
                message="请购买一件300元以内的静音键盘，送演示宿舍，" + extra,
            )
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        request_id = str(uuid4())
        response = await resume(env, buyer, tid, waiting, cid, request_id)
        assert response.status_code == 200, response.text
        done = response.json()
        assert done["status"] == "COMPLETED", done
        assert any(f["kind"] == "order_list" for f in done["result"]["facts"])
        assert (await resume(env, buyer, tid, waiting, cid, request_id)).json() == done
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
        assert (
            row(env[1], "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL")["n"]
            == 1
        )
    finally:
        await provider.close()


class UnfinishedAfterCheckoutWire(RepeatCheckoutWire):
    """No new results and no structured completion signal after the transaction."""

    def transport(self, role):
        original = super().transport(role)

        def respond(request):
            response = original.handle_request(request)
            body = json.loads(request.content)
            state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            if any(
                f["kind"] == "proposal" and f["data"]["status"] == "EXECUTED"
                for f in state.get("committed_facts", [])
            ):
                data = response.json()
                data["choices"][0]["finish_reason"] = "stop"
                data["choices"][0]["message"] = {"role": "assistant", "content": "还有事项待核实"}
                return httpx.Response(200, json=data)
            return response

        return httpx.MockTransport(respond)


@pytest.mark.parametrize("repeat_write", [False, True])
async def test_committed_order_does_not_turn_unfinished_or_repeated_call_into_success(
    durable_env, buyer, tmp_path, repeat_write
):
    env = durable_env
    wire = RepeatCheckoutWire() if repeat_write else UnfinishedAfterCheckoutWire()
    provider = await attach_wire(env, tmp_path, wire)
    try:
        tid = await thread(env, buyer, "single")
        waiting = (
            await start(env, buyer, tid, message="请购买一件300元以内的静音键盘，送演示宿舍")
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, waiting, cid)).json()
        assert done["status"] != "COMPLETED", done
        if repeat_write:
            assert "REPEATED_TOOL_CALL" in done["result"]["error_codes"]
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
        assert (
            row(env[1], "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL")["n"]
            == 1
        )
        assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 1
    finally:
        await provider.close()


class AftersalesReadAfterCheckoutWire(ReadAfterCheckoutWire):
    def __init__(self, order_id):
        self.order_id = order_id

    def transport(self, role):
        original = super().transport(role)

        def respond(request):
            data = original.handle_request(request).json()
            for call in data["choices"][0]["message"].get("tool_calls", []):
                if call["function"]["name"] == "list_orders":
                    call["function"] = {
                        "name": "get_order",
                        "arguments": json.dumps({"order_id": self.order_id}),
                    }
            return httpx.Response(200, json=data)

        return httpx.MockTransport(respond)


async def test_checkout_keeps_independent_aftersales_read(durable_env, buyer, product, tmp_path):
    env = durable_env
    original = await delivered_order(env[0], buyer, product)
    from evals.smoke_session import sql_facts

    before = sql_facts(env[3])
    provider = await attach_wire(env, tmp_path, AftersalesReadAfterCheckoutWire(original["id"]))
    try:
        tid = await thread(env, buyer, "single")
        waiting = (
            await start(
                env,
                buyer,
                tid,
                message="请购买一件300元以内的静音键盘，送演示宿舍；再查一下之前订单的售后状态。",
            )
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, waiting, cid)).json()
        assert done["status"] == "COMPLETED", done
        assert any(
            f["kind"] == "order"
            and f["id"] == original["id"]
            and f["data"]["status"] == "DELIVERED"
            for f in done["result"]["facts"]
        )
        assert (
            row(
                env[1],
                "SELECT count(*) n FROM run_events WHERE event_type='tool' "
                "AND payload_summary->>'name'='get_order' "
                "AND payload_summary->>'ok'='true'",
            )["n"]
            == 1
        )
        after = sql_facts(env[3])
        assert len(after["orders"]) - len(before["orders"]) == 1
        assert len(after["confirmations"]) - len(before["confirmations"]) == 1
        assert after["payments"] == before["payments"]
        assert after["refunds"] == before["refunds"]
        assert after["checkpoint_count"] > 0
    finally:
        await provider.close()
