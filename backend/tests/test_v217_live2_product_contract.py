"""Frozen-input OFFLINE contract regression; no Provider permission is granted."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from evals.smoke_runner import static_admission

from agentmall.agents.context import MultiRequest, user_constraints
from agentmall.infra.errors import DomainError

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = ROOT / "evals/proposals/v217-product-smoke.json"
PROPOSAL_SHA = "4dd539b51bc1b3162825a3721bb3e99c59d264ad9794d49db6107603fa620230"


def frozen_proposal():
    raw = PROPOSAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == PROPOSAL_SHA
    return json.loads(raw)


def parsed(message):
    return user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))


@pytest.mark.parametrize("index", [0, 1, 2])
def test_original_frozen_request_permissions_and_price_scope(index):
    value = parsed(frozen_proposal()["tasks"][index]["user_request"])
    if index == 0:
        assert not value.purchase_requested and not value.return_requested
        assert value.max_price_cents == 40000
    elif index == 1:
        assert value.purchase_requested and value.quantity == 2
        assert value.max_price_cents is None
    else:
        assert value.return_requested and value.reason_code == "QUALITY_ISSUE"
        assert value.purchase_requested and value.quantity == 1
        assert value.max_price_cents == 25000
        assert (
            value.product_needs.layout is None
        )  # The old SKU is not a replacement layout request.


def test_explicit_key_count_constraint_remains_a_layout_requirement():
    assert parsed("推荐87键的有线静音键盘").product_needs.layout == "87键"


@pytest.mark.parametrize(
    "message,budget",
    [
        ("购买两件199元的键盘", None),
        ("购买两件单价199元的键盘，预算400元", 40000),
        ("购买两件199元的键盘，总价不超过398元", 39800),
        ("购买两件键盘，预算199元", 19900),
        ("购买两件键盘，总金额上限199元", 19900),
        ("推荐预算199元的键盘，不购买", 19900),
        ("推荐单价360元以内的静音键盘，不购买", 36000),
        ("预算只有199元的情况下，准备购买两件静音键盘，送演示宿舍", 19900),
        ("预算：199元的情况下，准备购买两件静音键盘，送演示宿舍", 19900),
    ],
)
def test_unit_price_is_not_a_total_budget_and_explicit_caps_remain(message, budget):
    assert parsed(message).max_price_cents == budget


@pytest.mark.parametrize("message", ["申请质量退货", "因质量问题申请退货", "按键失灵，请申请退货"])
def test_explicit_quality_return_reason(message):
    value = parsed(message)
    assert value.return_requested and value.reason_code == "QUALITY_ISSUE"


@pytest.mark.parametrize(
    "message",
    [
        "不要申请质量退货",
        "我昨天已经申请质量退货",
        "记录里写着申请质量退货",
        "商家申请质量退货",
        "请客服申请质量退货",
        "客服让我申请质量退货",
        "如果按键失灵，请申请质量退货",
        "审核通过后请申请质量退货",
        "申请质量退货是我昨天的要求，现在先不操作",
        "申请质量退货是客服的建议，我还没决定",
        "退货",
    ],
)
def test_quality_wording_does_not_grant_denied_reported_or_conditional_authority(message):
    try:
        value = parsed(message)
    except DomainError as exc:
        assert exc.code == "CONTEXT_CLARIFICATION_REQUIRED"
    else:
        assert value.return_requested is False


def test_original_frozen_static_admission_is_compatible_but_not_authorized():
    result = static_admission(frozen_proposal())
    assert result["state"] == "STATIC_COMPATIBLE_NOT_AUTHORIZED"
    assert result["codes"] == [] and result["agent_episodes"] == 0


@pytest.mark.parametrize("history", ["之前的订单已申请质量退货", "之前键盘按键失灵的问题已经解决"])
def test_historical_quality_reason_does_not_override_current_return_reason(history):
    value = parsed(history + "。现在这件商品只是改变主意，请申请退货。")
    assert value.return_requested and value.reason_code is None


async def test_frozen_abc_formal_api_sql_and_independent_confirmations(
    env, tmp_path, record_property
):
    import httpx
    from evals.controlled_offline import Operator
    from evals.smoke_assertions import score_verified
    from evals.smoke_runner import SmokeBatch, SmokeStopped
    from evals.smoke_session import SmokeSession, sql_facts
    from playground_helpers import SDKProgram
    from retrieval_helpers import FixtureEncoder
    from test_v217_live1_transport import price

    p = frozen_proposal()  # No task/message/constraints changes, including C's owned-order slot.
    gate = SmokeBatch(tmp_path / "batch.json", p, PROPOSAL_SHA)
    summaries = []
    schemas = []
    for index, task in enumerate(p["tasks"]):
        gate.arm(task["id"])
        session = SmokeSession(gate, tmp_path / task["id"])
        wire = SDKProgram("return_replace")
        product_ids = []

        def transport(role, wire=wire, session=session, index=index, product_ids=product_ids):
            if index == 2:
                wire.order_id = session.setup["order_id"]
                return wire.transport(role)

            def compare(request):
                # Explicit synthetic model choice from the real catalogue API,
                # not invented tool results, a changed request or typed constraints.
                body = json.loads(request.content)
                state = json.loads(
                    next(m["content"] for m in body["messages"] if m["role"] == "user")
                )
                done = any(
                    f["kind"] == "proposal" and f["data"]["status"] in {"EXECUTED", "REJECTED"}
                    for f in state.get("committed_facts", [])
                )
                tools = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
                calls = []
                if not done and not tools:
                    calls = [("get_product", {"product_id": pid}) for pid in product_ids]
                elif not done and index == 1 and not any(t.get("action_type") for t in tools):
                    calls = [("prepare_checkout", {"product_id": product_ids[0]})]
                message = {"role": "assistant", "content": '{"terminal":"finish"}'}
                if calls:
                    message = {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_" + uuid4().hex,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args),
                                },
                            }
                            for name, args in calls
                        ],
                    }
                result = {
                    "id": "contract_" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if calls else "stop",
                            "message": message,
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                }
                return httpx.Response(200, json=result)

            return httpx.MockTransport(compare)

        try:
            await session.initialize(
                env[3].database_url.get_secret_value(),
                price(),
                encoder_factory=FixtureEncoder,
                transport_factory=transport,
            )
            schemas.append(session.settings.db_schema)
            if index in {0, 1}:
                catalogue = await session.client.get(
                    "/api/v1/products?limit=100", headers=session.auth
                )
                assert catalogue.status_code == 200
                products = catalogue.json()["items"]
                if index == 0:
                    wired = next(
                        p
                        for p in products
                        if p["attributes"]["connection"] == "有线"
                        and p["attributes"]["switch"] == "静音轴"
                        and p["price_cents"] <= 40000
                    )
                    wireless = next(
                        p
                        for p in products
                        if "wireless" in p["attributes"]["connection_capabilities"]
                        and p["attributes"]["switch"] == "静音轴"
                        and p["price_cents"] <= 40000
                    )
                    product_ids.extend([wired["id"], wireless["id"]])
                else:
                    product_ids.append(
                        next(
                            p["id"]
                            for p in products
                            if p["name"].replace(" ", "") in task["user_request"]
                        )
                    )
            run = await session.start()
            confirmations = []
            if index:
                assert run["status"] == "WAITING_INPUT", run
                first = await session.inspect()
                assert first["proposal"]["action_type"] == (
                    "RETURN_REQUEST" if index == 2 else "CHECKOUT"
                )
                confirmation = await session.decide(
                    first, "approve", operator="TEST_OPERATOR_CODEX"
                )
                confirmations.append(confirmation["confirmation_id"])
                request_id = str(uuid4())
                run = await session.resume(first, confirmations[0], request_id)
                inspection = first
                if index == 2:
                    assert run["status"] == "WAITING_INPUT", run
                    middle = sql_facts(
                        session.settings
                    )  # Independent SQL connection, no API writes.
                    assert len(middle["cases"]) == 1 and len(middle["orders"]) == 1
                    second = await session.inspect()
                    assert second["proposal"]["action_type"] == "CHECKOUT"
                    with pytest.raises(SmokeStopped, match="CONFIRMATION_BINDING_INVALID"):
                        await session.resume(second, confirmations[0], str(uuid4()))
                    confirmation = await session.decide(
                        second, "approve", operator="TEST_OPERATOR_CODEX"
                    )
                    confirmations.append(confirmation["confirmation_id"])
                    assert len(set(confirmations)) == 2
                    request_id = str(uuid4())
                    run = await session.resume(second, confirmations[1], request_id)
                    inspection = second
                assert run["status"] == "COMPLETED", run
                budget = run["budget"]
                # Exercise original formal API replay, not just the Runner's cached receipt.
                assert (
                    await Operator(session.client, session.auth).resume(
                        session.thread_id, inspection, confirmations[-1], request_id
                    )
                    == run
                )
                assert run["budget"] == budget
            assert run["status"] == "COMPLETED", run
            evidence_sha, evidence = await session.freeze_export_verify()
            assertion = score_verified(session.directory)
            assert assertion["status"] == "PASS", assertion
            assert not assertion["violations"]
            assert evidence["after"]["checkpoint_count"] > 0
            assert all(not r["has_worker"] and not r["has_lock"] for r in evidence["after"]["runs"])
            summaries.append(
                {
                    "task_id": task["id"],
                    "architecture": task["architecture"],
                    "evidence_class": "OFFLINE_SDK_MOCK_FORMAL_API_REAL_POSTGRESQL",
                    "run_id": run["id"],
                    "thread_id": session.thread_id,
                    "assertion": assertion,
                    "budget": run["budget"],
                    "confirmation_ids": confirmations,
                    "evidence_sha256": evidence_sha,
                    "http_mock_requests": len(evidence["ledger"]["attempts"]),
                }
            )
            gate.verified(evidence_sha)
            await session.close()
            await session.cleanup("CONTRACT_TEST_ONLY-LIVE2-independent-owned-cleanup")
        finally:
            await session.close()
    assert len(set(schemas)) == 3
    record_property("frozen_input_offline_results", json.dumps(summaries))
