"""CONTRACT_TEST_ONLY: shared direct/Thread price semantics, not Live scoring."""

from uuid import uuid4

import pytest

from agentmall.agents.context import MultiRequest, user_constraints
from agentmall.agents.memory import resolve_preferences
from agentmall.agents.run_schemas import RunCreate
from agentmall.infra.errors import DomainError


def parse(message, *, threaded=False, previous=None, constraints=None):
    if threaded:
        return resolve_preferences(
            previous or {},
            RunCreate(request_id=uuid4(), message=message, constraints=constraints),
        )[1]
    return user_constraints(
        MultiRequest(
            request_id=uuid4(), thread_id=uuid4(), message=message, constraints=constraints
        )
    ).model_dump(mode="json")


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
@pytest.mark.parametrize(
    "message,cap,quantity,buy",
    [
        ("推荐199元的静音键盘，不购买", 19900, None, False),
        ("推荐199元以内的静音键盘", 19900, None, False),
        # Bare action topics retain their existing non-authorizing semantics.
        ("购买两件199元的键盘", None, None, False),
        ("购买两件199元键盘", None, None, False),
        ("购买两件键盘，总预算199元", 19900, None, False),
        ("购买两件199元键盘，总预算600元", 60000, None, False),
        ("准备购买两件199元的键盘", None, 2, True),
        ("准备购买两件199元键盘", None, 2, True),
        ("准备购买两件键盘，总预算199元", 19900, 2, True),
        ("准备购买两件199元键盘，总预算600元", 60000, 2, True),
        ("准备购买两件单价199元的键盘，总金额上限400元", 40000, 2, True),
    ],
)
def test_shared_price_meanings(threaded, message, cap, quantity, buy):
    result = parse(message, threaded=threaded)
    assert result["max_price_cents"] == cap
    assert result["quantity"] == quantity
    assert result["purchase_requested"] is buy


def test_unit_quote_does_not_clear_a_thread_budget():
    result = parse(
        "准备购买两件199元的键盘",
        threaded=True,
        previous={"max_price_cents": 30000},
    )
    assert result["max_price_cents"] == 30000
    assert result["quantity"] == 2


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_multiple_incompatible_caps_require_clarification(threaded):
    with pytest.raises(DomainError) as error:
        parse("购买两件键盘，预算300元，不超过400元", threaded=threaded)
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_conflicting_unit_quotes_still_require_clarification(threaded):
    with pytest.raises(DomainError) as error:
        parse("准备购买一件199元的键盘，单价299元", threaded=threaded)
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
@pytest.mark.parametrize("typed_cap", [None, 60000])
def test_typed_cap_cannot_erase_or_widen_textual_limit(threaded, typed_cap):
    try:
        result = parse(
            "购买两件键盘，总预算199元",
            threaded=threaded,
            constraints={"max_price_cents": typed_cap},
        )
    except DomainError as error:
        assert error.code == "CONTEXT_CLARIFICATION_REQUIRED"
    else:
        assert result["max_price_cents"] == 19900


@pytest.mark.parametrize("threaded", [False, True], ids=["direct", "thread"])
def test_typed_purchase_preserves_unit_quote_semantics(threaded):
    result = parse(
        "请购买两件199元的键盘，送演示宿舍",
        threaded=threaded,
        constraints={"purchase_requested": True, "quantity": 2},
    )
    assert result["purchase_requested"] is True
    assert result["max_price_cents"] is None


@pytest.mark.parametrize(
    "threaded,message,cap,buy,blocked,previous_cap,typed_cap,clarification",
    [
        (threaded, *case, None, "unset", None)
        for threaded in (False, True)
        for case in (
            ("推荐199元的静音键盘，不购买", 19900, False, False),
            ("推荐199元以内的静音键盘", 19900, False, False),
            ("准备购买两件199元的键盘，送演示宿舍", None, True, False),
            ("准备购买两件键盘，总预算199元，送演示宿舍", 19900, True, True),
            ("准备购买两件199元键盘，总预算600元，送演示宿舍", 60000, True, False),
        )
    ]
    + [
        (True, "准备购买两件199元的键盘，送演示宿舍", 30000, True, True, 30000, "unset", None),
        (False, "准备购买两件键盘，总预算199元，送演示宿舍", 19900, True, True, None, 60000, None),
        (True, "准备购买两件键盘，总预算199元，送演示宿舍", 19900, True, True, None, 60000, None),
        (False, "准备购买两件键盘，总预算199元，送演示宿舍", 19900, True, True, None, None, None),
        (True, "准备购买两件键盘，总预算199元，送演示宿舍", 19900, True, True, None, None, None),
        pytest.param(
            True,
            "准备购买两件键盘，预算600元",
            60000,
            True,
            False,
            None,
            "unset",
            "单价199元，送演示宿舍",
            id="unfinished-unit-price-clarification",
        ),
    ],
)
async def test_prices_through_sdk_mock_formal_api_and_independent_sql(
    env,
    tmp_path,
    threaded,
    message,
    cap,
    buy,
    blocked,
    previous_cap,
    typed_cap,
    clarification,
    record_property,
):
    import json
    from time import perf_counter, time

    import httpx
    from evals.controlled_offline import Operator
    from evals.smoke_runner import SmokeBatch
    from evals.smoke_session import SmokeSession, sql_facts
    from retrieval_helpers import FixtureEncoder
    from test_v217_live1_transport import price
    from test_v217_smoke_contract import proposal

    p = proposal()
    p["tasks"][0]["user_request"] = message
    epoch, mono = time(), perf_counter()
    gate = SmokeBatch(
        tmp_path / "batch.json", p, "e" * 64, clock=lambda: epoch + perf_counter() - mono
    )
    gate.arm(p["tasks"][0]["id"])
    session = SmokeSession(gate, tmp_path / "price-contract")
    product_id = None

    def transport(role):
        def respond(request):
            body = json.loads(request.content)
            state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            tools = [m for m in body["messages"] if m["role"] == "tool"]
            done = any(
                f["kind"] == "proposal" and f["data"]["status"] == "EXECUTED"
                for f in state.get("committed_facts", [])
            )
            call = None
            missing_address = buy and not state["constraints"]["address_label"]
            if not tools and not done and not missing_address:
                call = (
                    ("get_product", {"product_id": product_id})
                    if buy
                    else ("retrieve_products", {"query": "静音键盘"})
                )
            elif buy and len(tools) == 1 and not done:
                # The real server must refuse the over-budget checkout even if
                # a model asks for it; no synthetic constraint/tool result here.
                call = ("prepare_checkout", {"product_id": product_id})
            terminal = "clarify" if missing_address else "finish"
            output = {"role": "assistant", "content": json.dumps({"terminal": terminal})}
            if call:
                output = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "price_" + uuid4().hex,
                            "type": "function",
                            "function": {"name": call[0], "arguments": json.dumps(call[1])},
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
                            "finish_reason": "tool_calls" if call else "stop",
                            "message": output,
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                },
            )

        return httpx.MockTransport(respond)

    try:
        await session.initialize(
            env[3].database_url.get_secret_value(),
            price(),
            encoder_factory=FixtureEncoder,
            transport_factory=transport,
        )
        catalogue = (await session.client.get("/api/v1/products?limit=100")).json()["items"]
        target = next(x for x in catalogue if x["name"] == "宿舍静音 K68")
        assert target["price_cents"] == 19900
        assert any(x["price_cents"] == 39900 for x in catalogue)
        product_id = target["id"]
        version = 0
        if previous_cap is not None:
            updated = await session.client.patch(
                f"/api/v1/agent/threads/{session.thread_id}/context",
                headers=session.auth,
                json={
                    "request_id": str(uuid4()),
                    "expected_version": 0,
                    "operations": [
                        {"op": "SET", "field": "max_price_cents", "value": previous_cap}
                    ],
                },
            )
            assert updated.status_code == 200, updated.text
            version = updated.json()["applied_version"]
        gate.start_episode()
        session.start_request_id = str(uuid4())
        payload = {"request_id": session.start_request_id, "message": message}
        if threaded:
            payload["expected_context_version"] = version
        if typed_cap != "unset":
            payload["constraints"] = {
                "max_price_cents": typed_cap,
                "purchase_requested": True,
                "quantity": 2,
                "address_label": "demo_dorm",
            }
        response = await session.client.post(
            f"/api/v1/agent/threads/{session.thread_id}/runs",
            headers=session.auth,
            json=payload,
        )
        if threaded and typed_cap == 60000:
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
            rejected = sql_facts(session.settings)
            assert not rejected["runs"] and not rejected["orders"] and not rejected["proposals"]
            assert not session.provider.ledger.read()["attempts"]
            gate.stop("CONTRACT_TEST_ONLY_EXPECTED_TYPED_CONFLICT")
            return
        assert response.status_code == 201, response.text
        run = session.run = response.json()
        if clarification is not None:
            assert run["status"] == "WAITING_INPUT", run
            assert run["pending_confirmation"]["type"] == "clarification"
            response = await session.client.post(
                f"/api/v1/agent/threads/{session.thread_id}/resume",
                headers=session.auth,
                json={
                    "request_id": str(uuid4()),
                    "run_id": run["id"],
                    "interrupt_id": run["pending_confirmation"]["interrupt_id"],
                    "clarification": clarification,
                },
            )
            assert response.status_code == 200, response.text
            run = session.run = response.json()
        assert run["constraints"]["max_price_cents"] == cap
        assert run["constraints"]["purchase_requested"] is buy
        before = sql_facts(session.settings)
        assert not before["orders"] and not before["items"]
        assert all(x["reserved"] == 0 for x in before["products"])
        if buy and not blocked:
            assert run["constraints"]["quantity"] == 2
            assert run["status"] == "WAITING_INPUT", run
            operator = Operator(session.client, session.auth)
            inspected = await operator.inspect(session.thread_id, run["id"])
            assert inspected["proposal"]["action_type"] == "CHECKOUT"
            assert inspected["proposal"]["canonical_payload"]["total_cents"] == 39800
            confirmation = await operator.decide(inspected, decision="approve")
            assert not sql_facts(session.settings)["orders"]
            rid = str(uuid4())
            run = session.run = await operator.resume(
                session.thread_id, inspected, confirmation["confirmation_id"], rid
            )
            assert run["status"] == "COMPLETED", run
            after = sql_facts(session.settings)
            assert len(after["orders"]) == len(after["items"]) == 1
            assert after["orders"][0]["status"] == "PENDING_PAYMENT"
            assert after["orders"][0]["total_cents"] == 39800
            assert after["items"][0]["quantity"] == 2
            assert after["items"][0]["unit_price_cents"] == 19900
            assert next(x for x in after["products"] if x["id"] == product_id)["reserved"] == 2
            assert after["confirmations"][0]["consumed_at"] is not None
            assert (
                await operator.resume(
                    session.thread_id, inspected, confirmation["confirmation_id"], rid
                )
                == run
            )
            assert sql_facts(session.settings) == after
        else:
            after = before
            assert not after["proposals"] and not after["confirmations"]
            if blocked:
                assert "CONSTRAINT_MISMATCH" in run["result"]["error_codes"], run
                amount = 2 * target["price_cents"]
                assert f"2件合计{amount}分，超过整单预算{cap}分" in run["result"]["answer"]
            else:
                assert run["status"] == "COMPLETED", run
                products = [x for x in run["result"]["facts"] if x["kind"] == "product"]
                assert products and all(x["data"]["price_cents"] <= 19900 for x in products)
        assert after["payments"] == after["refunds"] == 0
        assert after["checkpoint_count"] > 0
        if threaded:
            response = await session.client.get(
                f"/api/v1/agent/threads/{session.thread_id}", headers=session.auth
            )
            assert response.status_code == 200
            prefs = response.json()["context"]["preferences"]
            assert prefs.get("max_price_cents") == cap
        gate.end_episode()
        value, evidence = await session.freeze_export_verify()
        assert all(a["state"] == "SETTLED" for a in evidence["ledger"]["attempts"])
        gate.verified(value)
        record_property(
            "CONTRACT_TEST_ONLY_price_sql",
            json.dumps(
                {
                    "threaded": threaded,
                    "cap": cap,
                    "orders": after["orders"],
                    "items": after["items"],
                    "status": run["status"],
                }
            ),
        )
        await session.close()
        await session.cleanup("CONTRACT_TEST_ONLY-price-owned-schema")
    finally:
        await session.close()
