"""CONTRACT_TEST_ONLY price scopes; SDK MockTransport and real API/PG, never Live."""

import json
from contextlib import AsyncExitStack
from uuid import uuid4

import httpx
import pytest
from conftest import row
from evals.smoke_runner import static_admission
from sqlalchemy import text
from t09_helpers import durable_env as durable_env  # noqa: F401
from test_price_contract import parse
from test_v217_live2_product_contract import frozen_proposal

from agentmall.agents.context import Constraints
from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.infra.errors import DomainError
from agentmall.infra.llm import deepseek_model


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
@pytest.mark.parametrize(
    "message,total,unit,unit_max",
    [
        ("买两件，每件199元。", None, 19900, None),
        ("买两件，每件最多199元。", None, None, 19900),
        ("买两件，总预算300元。", 30000, None, None),
        ("买两件，每件199元，总预算300元。", 30000, 19900, None),
        ("买两件，每件199元，总预算400元。", 40000, 19900, None),
        ("买两件，单件价格是199元，总金额不超过400元。", 40000, 19900, None),
        ("买两件，每只不超过199元。", None, None, 19900),
        ("买两件，单价199元以内。", None, None, 19900),
    ],
)
def test_unit_amounts_never_become_order_total(threaded, message, total, unit, unit_max):
    value = parse(message, threaded=threaded)
    assert value["max_price_cents"] == total
    assert value["product_needs"].get("unit_price_cents") == unit
    assert value["product_needs"].get("max_unit_price_cents") == unit_max


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
@pytest.mark.parametrize("message", ["买两件，199元。", "买两件，单价199元，单价299元。"])
def test_ambiguous_or_conflicting_price_scope_requires_clarification(threaded, message):
    with pytest.raises(DomainError) as caught:
        parse(message, threaded=threaded)
    assert caught.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_thread_unit_price_preserves_total_budget_and_explicit_clear():
    prior = {"max_price_cents": 30000}
    prefs, value = resolve_preferences(
        prior, RunCreate(request_id=uuid4(), message="买两件，每件199元。")
    )
    assert value["max_price_cents"] == 30000
    assert value["product_needs"].get("unit_price_cents") == 19900
    _, cleared = resolve_preferences(
        prefs, RunCreate(request_id=uuid4(), message="清除预算，单价不变")
    )
    assert cleared["max_price_cents"] is None
    assert cleared["product_needs"].get("unit_price_cents") == 19900


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_typed_unit_cap_cannot_silently_widen_textual_cap(threaded):
    with pytest.raises(DomainError) as caught:
        parse(
            "买两件，每件最多199元。",
            threaded=threaded,
            constraints={"product_needs": {"max_unit_price_cents": 29900}},
        )
    assert caught.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_bare_purchase_topic_does_not_gain_write_authority_from_a_unit_quote():
    value = parse("买两件，每件199元。")
    assert not value["purchase_requested"] and value["quantity"] is None


def test_absent_unit_requirements_keep_old_constraint_payload():
    data = Constraints().model_dump(mode="json")
    assert "unit_price_cents" not in data["product_needs"]
    assert "max_unit_price_cents" not in data["product_needs"]


@pytest.mark.parametrize("mode", ["single", "multi", "legacy-multi", "legacy-single"])
@pytest.mark.parametrize(
    "prices,allowed",
    [
        ("每件199元", True),
        ("每件最多199元", True),
        ("总预算300元", False),
        ("每件199元，总预算300元", False),
        ("每件199元，总预算400元", True),
        ("每件189元", False),
        ("每件最多189元", False),
    ],
)
async def test_price_scopes_through_formal_apis_and_independent_sql(
    durable_env, buyer, mode, prices, allowed
):
    from playground_helpers import SDKProgram
    from retrieval_helpers import index

    env = durable_env
    client, db, app, _ = env
    with db.connect() as connection:
        product = dict(
            connection.execute(
                text("SELECT id,price_cents FROM products WHERE name='宿舍静音 K68'")
            )
            .mappings()
            .one()
        )
    assert product["price_cents"] == 19900
    pid = str(product["id"])
    message = f"请帮我买两件静音键盘，{prices}，送演示宿舍。"
    await index(env)
    wire = SDKProgram("purchase")

    def transport(role):
        if role in {"shopping", "supervisor", "order", "aftersales"}:
            return wire.transport(role)

        def respond(request):
            body = json.loads(request.content)
            tools = [m for m in body["messages"] if m["role"] == "tool"]
            legacy = role == "legacy"
            committed = (
                False
                if legacy
                else any(
                    f["kind"] == "proposal" and f["data"]["status"] == "EXECUTED"
                    for f in payload_from_body(body).get("committed_facts", [])
                )
            )
            call = None
            if not tools and not committed:
                call = ("get_product", {"product_id": pid})
            elif len(tools) == 1 and not committed:
                call = (
                    "prepare_checkout",
                    {"items": [{"product_id": pid, "quantity": 2}], "address_label": "demo_dorm"}
                    if legacy
                    else {"product_id": pid},
                )
            output = {"role": "assistant", "content": '{"terminal":"finish"}'}
            if call:
                output.update(
                    content="",
                    tool_calls=[
                        {
                            "id": "unit_" + uuid4().hex,
                            "type": "function",
                            "function": {"name": call[0], "arguments": json.dumps(call[1])},
                        }
                    ],
                )
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if call else "stop",
                            "message": output,
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                },
            )

        return httpx.MockTransport(respond)

    def payload_from_body(body):
        return json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))

    async with AsyncExitStack() as stack:
        models = {}
        for role in ["single", "legacy", "supervisor", "shopping", "order", "aftersales"]:
            channel = transport(role)
            sync = stack.enter_context(httpx.Client(transport=channel, trust_env=False))
            asynchronous = await stack.enter_async_context(
                httpx.AsyncClient(transport=channel, trust_env=False)
            )
            models[role] = deepseek_model(
                "CONTRACT_TEST_ONLY", http_client=sync, http_async_client=asynchronous
            )
        app.state.agent_model = models["legacy"]
        app.state.durable_single_model = models["single"]
        app.state.multi_models = {
            k: models[k] for k in ["supervisor", "shopping", "order", "aftersales"]
        }
        request_id = str(uuid4())
        if mode.startswith("legacy"):
            body = {"request_id": request_id, "message": message}
            if mode == "legacy-multi":
                body["thread_id"] = str(uuid4())
            response = await client.post(
                "/api/v1/agent/messages"
                if mode == "legacy-single"
                else "/api/v1/agent/multi/messages",
                headers=buyer,
                json=body,
            )
            assert response.status_code == 200, response.text
            result = response.json()
            proposals = result.get("proposal_refs", result.get("proposal_ids", []))
        else:
            created = await client.post("/api/v1/agent/threads", headers=buyer, json={"mode": mode})
            tid = created.json()["id"]
            response = await client.post(
                f"/api/v1/agent/threads/{tid}/runs",
                headers=buyer,
                json={"request_id": request_id, "message": message, "expected_context_version": 0},
            )
            assert response.status_code == 201, response.text
            result = response.json()
            pending = result.get("pending_confirmation") or {}
            proposals = [pending["proposal_id"]] if pending.get("proposal_id") else []
        before = row(
            db,
            "SELECT (SELECT count(*) FROM orders) orders,"
            "(SELECT sum(reserved) FROM products) reserved,"
            "(SELECT count(*) FROM confirmations) confirmations",
        )
        assert before == {"orders": 0, "reserved": 0, "confirmations": 0}
        if not allowed:
            assert not proposals, result
            assert row(db, "SELECT count(*) n FROM action_proposals")["n"] == 0
            return
        assert len(proposals) == 1, result
        proposal = await client.get("/api/v1/proposals/" + proposals[0], headers=buyer)
        assert proposal.status_code == 200
        snapshot = proposal.json()["canonical_payload"]
        assert snapshot["total_cents"] == 39800
        assert snapshot["items"][0]["unit_price_cents"] == 19900
        assert snapshot["items"][0]["quantity"] == 2
        decision = await client.post(
            f"/api/v1/proposals/{proposals[0]}/confirmations",
            headers=buyer,
            json={"decision": "approve"},
        )
        assert decision.status_code == 201
        cid = decision.json()["confirmation_id"]
        assert row(db, "SELECT count(*) n FROM orders")["n"] == 0
        if mode.startswith("legacy"):
            body = {"proposal_id": proposals[0], "confirmation_id": cid}
            headers = {**buyer, "Idempotency-Key": str(uuid4())}
            done = await client.post("/api/v1/orders", headers=headers, json=body)
            replay = await client.post("/api/v1/orders", headers=headers, json=body)
            assert (done.status_code, replay.status_code) == (201, 200)
        else:
            body = {
                "request_id": str(uuid4()),
                "run_id": result["id"],
                "interrupt_id": pending["interrupt_id"],
                "proposal_id": proposals[0],
                "confirmation_id": cid,
            }
            done = await client.post(
                f"/api/v1/agent/threads/{tid}/resume", headers=buyer, json=body
            )
            replay = await client.post(
                f"/api/v1/agent/threads/{tid}/resume", headers=buyer, json=body
            )
            assert done.status_code == replay.status_code == 200
            assert done.json()["status"] == "COMPLETED", done.text
            assert done.json() == replay.json()
        assert row(
            db,
            "SELECT (SELECT count(*) FROM orders) orders,"
            "(SELECT sum(reserved) FROM products) reserved,"
            "(SELECT count(*) FROM confirmations WHERE consumed_at IS NOT NULL) consumed,"
            "(SELECT count(*) FROM payments) payments,(SELECT count(*) FROM refunds) refunds",
        ) == {"orders": 1, "reserved": 2, "consumed": 1, "payments": 0, "refunds": 0}


def test_original_frozen_abc_admission_is_unchanged():
    result = static_admission(frozen_proposal())
    assert result["codes"] == [] and result["state"] == "STATIC_COMPATIBLE_NOT_AUTHORIZED"


def test_thread_clear_cannot_silently_drop_a_new_price():
    with pytest.raises(DomainError) as caught:
        resolve_preferences(
            {"product_needs": {"unit_price_cents": 29900}},
            RunCreate(
                request_id=uuid4(),
                message="清除单价要求，请帮我买两件键盘，每件199元，送演示宿舍。",
            ),
        )
    assert caught.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
@pytest.mark.parametrize(
    "message,typed",
    [
        ("请帮我买两件键盘，每件199元。", {"max_unit_price_cents": 18900}),
        ("请帮我买两件键盘，每件最多199元。", {"unit_price_cents": 29900}),
    ],
)
def test_merged_typed_unit_price_conflicts_require_clarification(threaded, message, typed):
    with pytest.raises(DomainError) as caught:
        parse(message, threaded=threaded, constraints={"product_needs": typed})
    assert caught.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_thread_persisted_cap_cannot_accept_a_conflicting_exact_price():
    with pytest.raises(DomainError) as caught:
        parse(
            "请帮我买两件键盘，每件299元。",
            threaded=True,
            previous={"product_needs": {"max_unit_price_cents": 19900}},
        )
    assert caught.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "message,extra,want_total,want_unit",
    [
        ("请帮我买两件键盘，每件199元。", "单价299元，送演示宿舍", None, 29900),
        ("请帮我买两件键盘，总预算600元。", "每件199元，送演示宿舍", 60000, 19900),
    ],
)
def test_legacy_clarification_keeps_unit_prices_separate(message, extra, want_total, want_unit):
    from types import SimpleNamespace

    from agentmall.agents.context import MultiRequest, user_constraints
    from agentmall.agents.durable_graph import apply_legacy_clarification

    request = MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
    runtime = SimpleNamespace(
        input=request, constraints=user_constraints(request), exclusions=set()
    )
    apply_legacy_clarification(runtime, extra)
    assert runtime.constraints.max_price_cents == want_total
    assert runtime.constraints.product_needs.unit_price_cents == want_unit
    assert runtime.constraints.purchase_requested and runtime.constraints.quantity == 2
