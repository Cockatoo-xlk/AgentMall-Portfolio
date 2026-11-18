"""CONTRACT_TEST_ONLY: exposed scenarios are development regressions, never re-scoring."""

import json
from uuid import uuid4

import httpx
import pytest
from aftersales_helpers import delivered_order
from conftest import row
from playground_helpers import SDKProgram
from sqlalchemy import text
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env
from test_v217_live1_integration import SingleWire

from agentmall.agents.context import MultiRequest, user_constraints
from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.infra.errors import DomainError


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize(
    "message,category,connection",
    [
        (
            "订单123里的有线耳机坏了，我要申请质量退货。另外帮我买一只无线鼠标，送演示家庭。",
            "mouse",
            "无线",
        ),
        (
            "订单123的无线鼠标有质量问题，请申请退货；另准备购买一件有线键盘，送演示宿舍。",
            "keyboard",
            "有线",
        ),
        (
            "订单123的有线耳机，请申请质量退货，再帮我推荐无线鼠标，不购买。",
            "mouse",
            "无线",
        ),
        (
            "我准备购买一件无线键盘，送演示家庭；订单123的有线键盘坏了，请申请质量退货。",
            "keyboard",
            "无线",
        ),
    ],
)
def test_original_item_attributes_do_not_constrain_new_item(
    threaded, message, category, connection
):
    if threaded:
        _, actual = resolve_preferences(
            {}, RunCreate(request_id=uuid4(), message=message, expected_context_version=0)
        )
    else:
        actual = user_constraints(
            MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
        ).model_dump()
    assert actual["category"] == category
    assert actual["product_needs"]["connection"] == connection
    assert actual["return_requested"] is True


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize(
    "message",
    [
        "订单123的耳机坏了，请申请质量退货；另外帮我购买必须有线且必须无线的鼠标。",
        "订单123的必须有线且必须无线的耳机坏了，请申请质量退货；另外帮我购买无线鼠标。",
    ],
)
def test_same_item_connection_conflict_still_rejected(threaded, message):
    with pytest.raises(DomainError) as error:
        if threaded:
            resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
        else:
            user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("threaded", [False, True])
def test_unmarked_new_product_requirement_is_not_discarded(threaded):
    message = "订单123的耳机坏了，请申请质量退货；帮我购买无线鼠标，质量要求是有线鼠标。"
    with pytest.raises(DomainError) as error:
        if threaded:
            resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))
        else:
            user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("conflicting", [False, True])
def test_new_order_attributes_remain_in_scope(threaded, conflicting):
    message = (
        "订单123的有线耳机坏了，请申请质量退货；另外帮我购买一只"
        + ("无线鼠标，新订单的鼠标必须有线" if conflicting else "鼠标，新订单的鼠标必须无线")
        + "，送演示家庭。"
    )

    def parse():
        if threaded:
            return resolve_preferences({}, RunCreate(request_id=uuid4(), message=message))[1]
        return user_constraints(
            MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
        ).model_dump()

    if conflicting:
        with pytest.raises(DomainError) as error:
            parse()
        assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
    else:
        assert parse()["product_needs"]["connection"] == "无线"


async def test_independent_product_projection_matches_public_catalogue(durable_env):
    from evals.smoke_session import sql_facts

    env = durable_env
    catalogue = (await env[0].get("/api/v1/products?limit=100")).json()["items"]
    projected = {p["id"]: p for p in sql_facts(env[3])["products"]}
    assert {p["category"] for p in catalogue} >= {"keyboard", "mouse", "headphones"}
    for product in catalogue:
        sql_product = projected[product["id"]]
        for field in ("id", "name", "category", "price_cents", "attributes"):
            assert sql_product[field] == product[field]
        assert sql_product["on_hand"] - sql_product["reserved"] == product["available"]


class RepeatCheckoutWire(SingleWire):
    """A model that would repeat a committed write if unnecessarily called again."""

    def transport(self, role):
        normal = super().transport(role)

        def respond(request):
            body = json.loads(request.content)
            state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            if any(
                f["kind"] == "proposal" and f["data"]["status"] == "EXECUTED"
                for f in state.get("committed_facts", [])
            ):
                product = next(f["id"] for f in state["committed_facts"] if f["kind"] == "product")
                return httpx.Response(
                    200,
                    json={
                        "id": "contract-post-commit",
                        "model": "deepseek-flash",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "tool_calls",
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_" + uuid4().hex,
                                            "type": "function",
                                            "function": {
                                                "name": "prepare_checkout",
                                                "arguments": json.dumps({"product_id": product}),
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 30,
                            "total_tokens": 130,
                        },
                    },
                )
            return normal.handle_request(request)

        return httpx.MockTransport(respond)


async def attach_wire(env, directory, wire):
    from datetime import UTC, datetime

    from retrieval_helpers import index

    from agentmall.playground.app import attach_models
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint

    env[2].state.retrieval_encoder = await index(env)
    policy = PlaygroundPolicy(
        enabled=True,
        evidence_mode="MOCK_TRANSPORT",
        session_id=uuid4(),
        environment_id=uuid4(),
        source_sha256=source_fingerprint(),
        price_checked_at=datetime.now(UTC),
    )
    return attach_models(env[2], policy, directory, "CONTRACT_TEST_ONLY_SYNTHETIC", wire.transport)


@pytest.mark.parametrize("break_stock", [False, True])
async def test_single_receipt_finishes_without_replanning_checkout(
    durable_env, buyer, tmp_path, break_stock, record_property
):
    env = durable_env
    provider = await attach_wire(env, tmp_path, RepeatCheckoutWire())
    try:
        tid = await thread(env, buyer, "single")
        waiting = (
            await start(env, buyer, tid, message="请购买一件300元以内的静音键盘，送演示宿舍")
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        pid = waiting["pending_confirmation"]["proposal_id"]
        cid = await confirm(env, buyer, pid)
        models_before = waiting["budget"]["models"]
        if break_stock:
            with env[1].begin() as conn:
                conn.execute(text("UPDATE products SET on_hand=0"))
        request_id = str(uuid4())
        response = await resume(env, buyer, tid, waiting, cid, request_id)
        assert response.status_code == 200, response.text
        done = response.json()
        if break_stock:
            assert done["status"] == "PARTIAL", done
            assert done["result"]["error_codes"]
            assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
            assert row(env[1], "SELECT consumed_at FROM confirmations")["consumed_at"] is None
        else:
            assert done["status"] == "COMPLETED", done
            assert done["budget"]["models"] == models_before
            assert (await resume(env, buyer, tid, waiting, cid, request_id)).json() == done
            assert (await resume(env, buyer, tid, waiting, cid)).status_code == 409
            assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
            assert row(env[1], "SELECT status FROM orders")["status"] == "PENDING_PAYMENT"
            assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
            assert (
                row(env[1], "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL")[
                    "n"
                ]
                == 1
            )
            from evals.smoke_session import sql_facts

            facts = sql_facts(env[3])  # Separate read-only SQL connection.
            assert facts["payments"] == facts["refunds"] == 0
            assert sum(p["reserved"] for p in facts["products"]) == 1
            assert facts["items"][0]["quantity"] == 1
            assert facts["orders"][0]["total_cents"] == facts["items"][0]["unit_price_cents"]
            assert facts["orders"][0]["proposal_id"] == facts["confirmations"][0]["proposal_id"]
            assert facts["checkpoint_count"] > 0
            record_property(
                "single_committed_sql",
                json.dumps(
                    {
                        "run_id": done["id"],
                        "order": facts["orders"][0],
                        "confirmation": facts["confirmations"][0],
                        "checkpoint_count": facts["checkpoint_count"],
                    },
                    default=str,
                ),
            )
        assert (
            row(
                env[1],
                "SELECT count(*) n FROM agent_runs "
                "WHERE worker_token IS NOT NULL OR lock_pid IS NOT NULL",
            )["n"]
            == 0
        )
    finally:
        await provider.close()


class ReadAfterCheckoutWire(RepeatCheckoutWire):
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
                message = data["choices"][0]["message"]
                if any(m["role"] == "tool" for m in body["messages"]):
                    data["choices"][0]["finish_reason"] = "stop"
                    message.pop("tool_calls", None)
                    message["content"] = '{"terminal":"finish"}'
                else:
                    message["tool_calls"][0]["function"] = {
                        "name": "list_orders",
                        "arguments": "{}",
                    }
                return httpx.Response(200, json=data)
            return response

        return httpx.MockTransport(respond)


async def test_committed_checkout_does_not_skip_requested_order_read(durable_env, buyer, tmp_path):
    env = durable_env
    provider = await attach_wire(env, tmp_path, ReadAfterCheckoutWire())
    try:
        tid = await thread(env, buyer, "single")
        waiting = (
            await start(
                env,
                buyer,
                tid,
                message=("请购买一件300元以内的静音键盘，送演示宿舍，并查询本人的全部订单。"),
            )
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, waiting, cid)).json()
        assert done["status"] == "COMPLETED", done
        assert any(
            f["kind"] == "order_list" and f["data"]["count"] == 1 for f in done["result"]["facts"]
        )
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    finally:
        await provider.close()


class CompareAfterCheckoutWire(ReadAfterCheckoutWire):
    def __init__(self, product_id):
        self.product_id = product_id

    def transport(self, role):
        original = super().transport(role)

        def respond(request):
            response = original.handle_request(request)
            data = response.json()
            for call in data["choices"][0]["message"].get("tool_calls", []):
                if call["function"]["name"] == "list_orders":
                    call["function"] = {
                        "name": "get_product",
                        "arguments": json.dumps({"product_id": self.product_id}),
                    }
            return httpx.Response(200, json=data)

        return httpx.MockTransport(respond)


@pytest.mark.parametrize(
    "comparison", ["另请比较有线与无线键盘的差异。", "另请对比不同连接方式的键盘。"]
)
async def test_committed_checkout_keeps_independent_comparison_goal(
    durable_env, buyer, tmp_path, comparison
):
    env = durable_env
    product_id = str(
        row(
            env[1],
            "SELECT id FROM products WHERE category='keyboard' "
            "AND attributes->'connection_capabilities' ? 'wireless' "
            "AND attributes->>'noise'='较安静' AND price_cents<=60000 "
            "ORDER BY price_cents DESC LIMIT 1",
        )["id"]
    )
    provider = await attach_wire(env, tmp_path, CompareAfterCheckoutWire(product_id))
    try:
        tid = await thread(env, buyer, "single")
        waiting = (
            await start(
                env,
                buyer,
                tid,
                message="请购买一件600元以内的静音键盘，送演示宿舍。" + comparison,
            )
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, waiting, cid)).json()
        assert done["status"] == "COMPLETED", done
        assert (
            row(
                env[1],
                "SELECT count(*) n FROM run_events WHERE event_type='tool' "
                "AND payload_summary->>'name'='get_product' "
                "AND payload_summary->>'ok'='true'",
            )["n"]
            == 1
        )
        assert any(
            f["kind"] == "product" and f["id"] == product_id for f in done["result"]["facts"]
        )
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    finally:
        await provider.close()


class CrossCategoryWire(SDKProgram):
    def transport(self, role):
        original = super().transport(role)

        def respond(request):
            if role == "shopping":
                # Change only the synthetic SDK response's retrieval query, never the request.
                response = original.handle_request(request)
                data = response.json()
                calls = data["choices"][0]["message"].get("tool_calls", [])
                for call in calls:
                    if call["function"]["name"] == "retrieve_products":
                        call["function"]["arguments"] = json.dumps({"query": "无线鼠标"})
                return httpx.Response(200, json=data)
            return original.handle_request(request)

        return httpx.MockTransport(respond)


@pytest.mark.parametrize("threaded", [False, True])
async def test_cross_category_return_purchase_independent_confirmations(
    durable_env, buyer, tmp_path, record_property, threaded
):
    env = durable_env
    original_id = str(
        row(env[1], "SELECT id FROM products WHERE category='headphones' LIMIT 1")["id"]
    )
    original = await delivered_order(env[0], buyer, original_id)
    wire = CrossCategoryWire("return_replace", original["id"])
    provider = await attach_wire(env, tmp_path, wire)
    try:
        from evals.smoke_session import sql_facts

        before = sql_facts(env[3])
        tid = await thread(env, buyer)
        # H04 is now exposed DEVELOPMENT_REGRESSION, never a new Holdout score.
        response = await env[0].post(
            f"/api/v1/agent/threads/{tid}/runs",
            headers=buyer,
            json={
                "request_id": str(uuid4()),
                "message": (
                    f"订单{original['id']}里的有线耳机H1出现质量问题，我要申请退货。"
                    "另外帮我买一只无线鼠标M2，送到演示家庭。退货和购买请分别让我确认。"
                ),
                **({"expected_context_version": 0} if threaded else {}),
            },
        )
        assert response.status_code == 201, response.text
        first = response.json()
        assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        c1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        second = (await resume(env, buyer, tid, first, c1)).json()
        assert second["status"] == "WAITING_INPUT", second
        assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
        assert (await resume(env, buyer, tid, second, c1)).status_code == 409
        middle = sql_facts(env[3])
        assert len(middle["cases"]) == len(before["cases"]) + 1
        assert len(middle["orders"]) == len(before["orders"])
        c2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        assert c1 != c2
        request_id = str(uuid4())
        done = (await resume(env, buyer, tid, second, c2, request_id)).json()
        assert done["status"] == "COMPLETED", done
        assert (await resume(env, buyer, tid, second, c2, request_id)).json() == done
        after = sql_facts(env[3])
        assert len(after["cases"]) == len(before["cases"]) + 1
        assert len(after["orders"]) == len(before["orders"]) + 1
        assert len(after["confirmations"]) == len(before["confirmations"]) + 2
        assert (
            sum(c["consumed_at"] is not None for c in after["confirmations"])
            == sum(c["consumed_at"] is not None for c in before["confirmations"]) + 2
        )
        assert (
            sum(p["reserved"] for p in after["products"])
            == sum(p["reserved"] for p in before["products"]) + 1
        )
        assert after["payments"] == before["payments"] and after["refunds"] == before["refunds"]
        assert after["checkpoint_count"] > 0
        new_order = next(
            o for o in after["orders"] if o["id"] not in {o["id"] for o in before["orders"]}
        )
        item = next(i for i in after["items"] if i["order_id"] == new_order["id"])
        product = next(p for p in after["products"] if p["id"] == item["product_id"])
        assert product["category"] == "mouse" and item["quantity"] == 1
        assert new_order["total_cents"] == product["price_cents"] == 18900
        record_property(
            "business_sql",
            json.dumps(
                {
                    "case_delta": 1,
                    "order_delta": 1,
                    "confirmation_delta": 2,
                    "stock_reserved_delta": 1,
                    "payments_delta": 0,
                    "refunds_delta": 0,
                    "run_status": done["status"],
                }
            ),
        )
    finally:
        await provider.close()
