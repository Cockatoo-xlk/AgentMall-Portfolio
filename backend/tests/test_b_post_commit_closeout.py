"""CONTRACT_TEST_ONLY: exposed B/C development regressions, never historical rescoring.

The wire preserves the observed five tool turns, not unretained original response
bytes/arguments. It never changes its post-commit repeated-write reply to finish.
"""

import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
import pytest
from conftest import row
from evals.smoke_session import prepare_delivered_fixture, sql_facts
from playground_helpers import SDKProgram
from t09_helpers import confirm, resume, thread
from t09_helpers import durable_env as durable_env
from test_post_holdout_product_fix import attach_wire

PROPOSAL = json.loads(
    (Path(__file__).resolve().parents[2] / "evals/proposals/v217-product-smoke.json").read_text()
)


class ObservedCheckoutWire:
    """Event-constrained synthetic SDK responses; no real Provider or hidden constraints."""

    def __init__(self, product_id, continuation="repeat"):
        self.product_id = product_id
        self.continuation = continuation
        self.pre = self.post = 0
        self.frames = []

    def transport(self, role):
        def respond(request):
            body = json.loads(request.content)
            state = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
            committed = any(
                f["kind"] == "proposal" and f["data"]["status"] == "EXECUTED"
                for f in state.get("committed_facts", [])
            )
            self.frames.append(
                {
                    "committed": committed,
                    "state": state,
                    "visible_tools": [t["function"]["name"] for t in body["tools"]],
                }
            )
            if committed:
                self.post += 1
                call = (
                    ("get_product", {"product_id": self.product_id})
                    if self.post == 1
                    else ("prepare_checkout", {"product_id": self.product_id})
                )
            else:
                calls = [
                    ("retrieve_products", {"query": "宿舍静音 K68"}),
                    ("get_product", {"product_id": self.product_id}),
                    ("prepare_checkout", {"product_id": self.product_id}),
                ]
                call = calls[self.pre]
                self.pre += 1
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
            if committed and self.continuation == "empty_finish":
                message = {"role": "assistant", "content": '{"terminal":"finish"}'}
            if committed and self.continuation == "unrelated_read" and self.post > 1:
                message = {"role": "assistant", "content": '{"terminal":"finish"}'}
            if committed and self.continuation in {"unfinished", "unknown_usage"}:
                message = {"role": "assistant", "content": "仍有独立事项待核验"}
            data = {
                "id": "CONTRACT_TEST_ONLY_" + uuid4().hex,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                        "message": message,
                    }
                ],
            }
            if not (committed and self.continuation == "unknown_usage"):
                data["usage"] = {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}
            return httpx.Response(200, json=data)

        return httpx.MockTransport(respond)


async def start_original(env, buyer, tid, message):
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs",
        headers=buyer,
        json={"request_id": str(uuid4()), "message": message, "expected_context_version": 0},
    )
    assert response.status_code == 201, response.text
    return response.json()


def delta(before, after):
    old = {c["id"] for c in before["confirmations"]}
    cs = [c for c in after["confirmations"] if c["id"] not in old]
    return {
        "orders": len(after["orders"]) - len(before["orders"]),
        "cases": len(after["cases"]) - len(before["cases"]),
        "confirmations": len(cs),
        "consumed": sum(c["consumed_at"] is not None for c in cs),
        "reserved": sum(p["reserved"] for p in after["products"])
        - sum(p["reserved"] for p in before["products"]),
        "payments": after["payments"] - before["payments"],
        "refunds": after["refunds"] - before["refunds"],
    }


async def test_original_b_committed_receipt_completes_without_another_write_turn(
    durable_env, buyer, tmp_path, record_property
):
    env = durable_env
    pid = str(row(env[1], "SELECT id FROM products WHERE name='宿舍静音 K68'")["id"])
    wire = ObservedCheckoutWire(pid)
    provider = await attach_wire(env, tmp_path, wire)
    try:
        before = sql_facts(env[3])
        tid = await thread(env, buyer, "single")
        waiting = await start_original(env, buyer, tid, PROPOSAL["tasks"][1]["user_request"])
        assert waiting["status"] == "WAITING_INPUT", waiting
        pre_approval = delta(before, sql_facts(env[3]))
        assert all(value == 0 for value in pre_approval.values()), pre_approval
        record_property("B_before_approval_delta", json.dumps(pre_approval))
        inspection = await env[0].get(
            f"/api/v1/proposals/{waiting['pending_confirmation']['proposal_id']}", headers=buyer
        )
        assert inspection.status_code == 200 and inspection.json()["status"] == "PENDING"
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        request_id = str(uuid4())
        response = await resume(env, buyer, tid, waiting, cid, request_id)
        assert response.status_code == 200, response.text
        done = response.json()
        after = sql_facts(env[3])
        change = delta(before, after)
        assert change == {
            "orders": 1,
            "cases": 0,
            "confirmations": 1,
            "consumed": 1,
            "reserved": 2,
            "payments": 0,
            "refunds": 0,
        }
        assert after["orders"][0]["status"] == "PENDING_PAYMENT"
        assert after["orders"][0]["total_cents"] == 39800
        assert after["items"][0]["quantity"] == 2 and after["items"][0]["unit_price_cents"] == 19900
        assert after["items"][0]["product_id"] == pid
        assert after["confirmations"][0]["id"] == cid
        assert (
            after["confirmations"][0]["proposal_id"]
            == waiting["pending_confirmation"]["proposal_id"]
        )
        record_property("B_pending_order_cents", after["orders"][0]["total_cents"])
        post = [f for f in wire.frames if f["committed"]]
        record_property("SQL_delta", json.dumps(change))
        record_property("Run_status", done["status"])
        record_property("error_codes", json.dumps(done["result"]["error_codes"]))
        record_property("post_commit_context", json.dumps(post, ensure_ascii=False))
        if post:  # Characterize the baseline RED failure before the behavior assertion.
            assert post[0]["state"]["user_goal"] == PROPOSAL["tasks"][1]["user_request"]
            assert "goal" not in post[0]["state"]
            assert any(
                f["kind"] == "proposal" and f["data"]["result"]["status"] == "PENDING_PAYMENT"
                for f in post[0]["state"]["committed_facts"]
            )
        assert done["status"] == "COMPLETED", done
        assert "待付款" in done["result"]["answer"]
        assert done["budget"]["models"] == waiting["budget"]["models"]
        replay = await resume(env, buyer, tid, waiting, cid, request_id)
        assert replay.json() == done and sql_facts(env[3]) == after
    finally:
        await provider.close()


@pytest.mark.parametrize("continuation", ["repeat", "unfinished", "unknown_usage"])
async def test_independent_work_is_not_completed_by_checkout_receipt(
    durable_env, buyer, tmp_path, continuation
):
    env = durable_env
    pid = str(row(env[1], "SELECT id FROM products WHERE name='宿舍静音 K68'")["id"])
    provider = await attach_wire(env, tmp_path, ObservedCheckoutWire(pid, continuation))
    try:
        tid = await thread(env, buyer, "single")
        waiting = await start_original(
            env, buyer, tid, PROPOSAL["tasks"][1]["user_request"] + "另外查询本人的全部订单。"
        )
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, waiting, cid)).json()
        assert done["status"] != "COMPLETED", done
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert (
            row(env[1], "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL")["n"]
            == 1
        )
        if continuation == "repeat":
            assert "REPEATED_TOOL_CALL" in done["result"]["error_codes"]
        if continuation == "unknown_usage":
            assert provider.ledger.read()["halted"] == "PROVIDER_USAGE_UNKNOWN"
    finally:
        await provider.close()


@pytest.mark.parametrize("second", ["然后再买 K68 键盘", "再买 K68 键盘"])
async def test_second_purchase_is_not_satisfied_by_the_first_receipt(
    durable_env, buyer, tmp_path, second, record_property
):
    env = durable_env
    pid = str(row(env[1], "SELECT id FROM products WHERE name='宿舍静音 K68'")["id"])
    wire = ObservedCheckoutWire(pid)
    provider = await attach_wire(env, tmp_path, wire)
    try:
        before = sql_facts(env[3])
        tid = await thread(env, buyer, "single")
        waiting = await start_original(env, buyer, tid, "请购买一件 K68，送演示宿舍。" + second)
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = (await resume(env, buyer, tid, waiting, cid)).json()
        after = sql_facts(env[3])
        assert delta(before, after) == {
            "orders": 1,
            "cases": 0,
            "confirmations": 1,
            "consumed": 1,
            "reserved": 1,
            "payments": 0,
            "refunds": 0,
        }
        record_property("second_purchase_Run_status", done["status"])
        record_property("second_purchase_SQL_delta", json.dumps(delta(before, after)))
        assert done["status"] == "PARTIAL", done
        assert "REPEATED_TOOL_CALL" in done["result"]["error_codes"]
        assert wire.post == 2
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "extra,continuation",
    [
        ("再帮我记账", "empty_finish"),
        ("然后再买 K68 键盘", "empty_finish"),
        ("请申请质量退货", "empty_finish"),
        ("请查询本人的全部订单", "unrelated_read"),
    ],
)
async def test_unsubstantiated_finish_after_checkout_keeps_the_next_goal_open(
    durable_env, buyer, tmp_path, extra, continuation
):
    env = durable_env
    product = row(env[1], "SELECT id FROM products WHERE name='宿舍静音 K68'")["id"]
    wire = ObservedCheckoutWire(str(product), continuation)
    provider = await attach_wire(env, tmp_path, wire)
    try:
        tid = await thread(env, buyer, "single")
        waiting = await start_original(env, buyer, tid, "请购买一件静音键盘，送演示宿舍。" + extra)
        proposal_id = waiting["pending_confirmation"]["proposal_id"]
        confirmation_id = await confirm(env, buyer, proposal_id)
        done = (await resume(env, buyer, tid, waiting, confirmation_id)).json()
        assert done["status"] in {"WAITING_INPUT", "PARTIAL"}, done
        assert wire.post >= 1
        facts = sql_facts(env[3])
        assert len(facts["orders"]) == len(facts["confirmations"]) == 1
        assert facts["orders"][0]["status"] == "PENDING_PAYMENT"
        assert not facts["cases"] and not facts["payments"] and not facts["refunds"]
    finally:
        await provider.close()


async def test_original_c_keeps_two_independent_confirmations(
    durable_env, buyer, tmp_path, record_property
):
    env = durable_env
    setup = await prepare_delivered_fixture(env[0], buyer, "静音 K87")
    before = sql_facts(env[3])
    wire = SDKProgram("return_replace", setup["order_id"])
    provider = await attach_wire(env, tmp_path, wire)
    try:
        tid = await thread(env, buyer, "multi")
        message = PROPOSAL["tasks"][2]["user_request"].replace(
            "{delivered_order_id}", setup["order_id"]
        )
        began = perf_counter()
        first = await start_original(env, buyer, tid, message)
        first_ready = perf_counter()
        assert (
            first["status"] == "WAITING_INPUT"
            and first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        )
        inspected = await env[0].get(
            f"/api/v1/proposals/{first['pending_confirmation']['proposal_id']}", headers=buyer
        )
        assert inspected.status_code == 200 and inspected.json()["status"] == "PENDING"
        c1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        second = (await resume(env, buyer, tid, first, c1)).json()
        assert (
            second["status"] == "WAITING_INPUT"
            and second["pending_confirmation"]["action_type"] == "CHECKOUT"
        )
        mid = sql_facts(env[3])
        assert len(mid["cases"]) == len(before["cases"]) + 1 and len(mid["orders"]) == len(
            before["orders"]
        )
        bad = await resume(env, buyer, tid, second, c1)
        assert bad.status_code == 409 and sql_facts(env[3]) == mid
        record_property("C_after_first_resume_delta", json.dumps(delta(before, mid)))
        record_property("C_cross_proposal_response", bad.status_code)
        second_ready = perf_counter()
        inspected = await env[0].get(
            f"/api/v1/proposals/{second['pending_confirmation']['proposal_id']}", headers=buyer
        )
        assert inspected.status_code == 200 and inspected.json()["status"] == "PENDING"
        c2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        assert c1 != c2
        resume_id = str(uuid4())
        done = (await resume(env, buyer, tid, second, c2, resume_id)).json()
        after = sql_facts(env[3])
        change = delta(before, after)
        assert done["status"] == "COMPLETED", done
        assert change == {
            "orders": 1,
            "cases": 1,
            "confirmations": 2,
            "consumed": 2,
            "reserved": 1,
            "payments": 0,
            "refunds": 0,
        }
        assert after["checkpoint_count"] > 0
        original_ids = {o["id"] for o in before["orders"]}
        new_order = next(o for o in after["orders"] if o["id"] not in original_ids)
        new_item = next(i for i in after["items"] if i["order_id"] == new_order["id"])
        assert new_order["status"] == "PENDING_PAYMENT" and new_order["total_cents"] <= 25000
        assert new_item["quantity"] == 1
        assert after["cases"][0]["reason_code"] == "QUALITY_ISSUE"
        assert after["cases"][0]["order_id"] == setup["order_id"]
        assert perf_counter() - began < 90
        replay = await resume(env, buyer, tid, second, c2, resume_id)
        assert replay.status_code == 200 and replay.json() == done
        assert sql_facts(env[3]) == after
        consumed = {c["id"]: c["proposal_id"] for c in after["confirmations"] if c["consumed_at"]}
        assert consumed[c1] == first["pending_confirmation"]["proposal_id"]
        assert consumed[c2] == second["pending_confirmation"]["proposal_id"]
        record_property("C_replayed_resume_sql_unchanged", True)
        record_property("C_SQL_delta", json.dumps(change))
        record_property(
            "C_phase_seconds",
            json.dumps(
                {
                    "first_proposal": first_ready - began,
                    "first_approval_and_resume_to_second_proposal": second_ready - first_ready,
                    "second_approval_and_resume_to_done": perf_counter() - second_ready,
                }
            ),
        )
    finally:
        await provider.close()


def completed_purchase(message, *, name="宿舍静音 K68", category="keyboard", quantity=2):
    from test_checkout_goal_binding import checked_out

    from agentmall.catalog.schemas import ProductDTO

    product = ProductDTO(
        id=uuid4(),
        name=name,
        category=category,
        attributes={"noise": "较安静", "size": "68键"} if category == "keyboard" else {},
        description="合成商品",
        price_cents=19900,
        available=10,
        catalog_version=1,
    )
    return checked_out(message, product, quantity=quantity)


@pytest.mark.parametrize(
    "extra,expected",
    [
        ("", True),
        ("然后再生成购买提案。", False),
        ("另外查询本人的全部订单。", False),
        ("并查一下本人全部订单", False),
        ("另请比较两款商品", False),
        ("还有事项需要核验", False),
        ("再查之前订单的售后状态", False),
        ("请联系客服", False),
        ("然后付款", False),
    ],
)
def test_only_proven_checkout_scope_can_close(extra, expected):
    from agentmall.agents import goal_receipts

    message = PROPOSAL["tasks"][1]["user_request"] + extra
    runtime, pid = completed_purchase(message)
    assert bool(goal_receipts.completed_single_checkout(runtime, message, {pid})) is expected


@pytest.mark.parametrize(
    "followup,expected",
    [
        ("单件199元，送演示宿舍", True),
        ("单件209元，送演示宿舍", False),
        ("再帮我购买两件K68键盘，送演示宿舍", False),
    ],
)
def test_same_run_checkout_qualifiers_do_not_authorize_another_goal(followup, expected):
    from agentmall.agents.goal_receipts import completed_single_checkout

    goal = "准备购买两件K68键盘，预算600元"
    runtime, pid = completed_purchase(goal + "，送演示宿舍")
    runtime.input.message = followup
    assert bool(completed_single_checkout(runtime, goal, {pid})) is expected


@pytest.mark.parametrize(
    "next_turn,correct_proposal,expected", [(1, True, True), (2, True, False), (1, False, False)]
)
def test_clarification_is_bound_to_the_following_proposal(next_turn, correct_proposal, expected):
    from agentmall.agents.context import SpecialistResult
    from agentmall.agents.goal_receipts import completed_single_checkout

    goal = "准备购买两件K68键盘，预算600元"
    runtime, pid = completed_purchase(goal + "，送演示宿舍")
    runtime.input.message = "送演示宿舍"
    question = SpecialistResult(
        subtask_id="single_0", target="order", status="needs_input", summary=""
    )
    proposal = SpecialistResult(
        subtask_id=f"single_{next_turn}",
        target="order",
        status="proposal",
        summary="",
        proposal_ids=[pid if correct_proposal else uuid4()],
    )
    runtime.completed = {item.subtask_id: item for item in (question, proposal)}
    assert bool(completed_single_checkout(runtime, goal, {pid})) is expected


@pytest.mark.parametrize(
    "mutation",
    [
        "not_handled",
        "not_executed",
        "missing_result",
        "error",
        "wrong_action",
        "wrong_receipt_binding",
        "new_clarification",
    ],
)
def test_checkout_receipt_without_complete_current_proof_cannot_close(mutation):
    from agentmall.agents import goal_receipts

    message = PROPOSAL["tasks"][1]["user_request"]
    runtime, pid = completed_purchase(message)
    value = runtime.facts[("proposal", pid)]
    handled = {pid}
    if mutation == "not_handled":
        handled.clear()
    if mutation == "not_executed":
        value["status"] = "APPROVED"
    if mutation == "missing_result":
        value["result"] = None
    if mutation == "error":
        runtime.errors = ["PRICE_CHANGED"]
    if mutation == "wrong_action":
        value["action_type"] = "RETURN_REQUEST"
    if mutation == "wrong_receipt_binding":
        value["result"]["action_id"] = str(uuid4())
    if mutation == "new_clarification":
        runtime.input.message = "再查询本人的订单"
    assert not goal_receipts.completed_single_checkout(runtime, message, handled)


@pytest.mark.parametrize("catalog_name", ["宿舍静音 K68 查询本人的全部订单", "查询本人的全部订单"])
def test_catalog_free_text_cannot_erase_an_independent_goal(catalog_name):
    from agentmall.agents import goal_receipts

    message = "请购买一件300元以内的静音键盘，送演示宿舍。请查询本人的全部订单。"
    runtime, pid = completed_purchase(message, name=catalog_name, quantity=1)
    assert not goal_receipts.completed_single_checkout(runtime, message, {pid})


def test_category_descriptor_cannot_erase_independent_operation():
    from agentmall.agents import goal_receipts

    message = "请购买一件10000元以内的相机，送演示宿舍。然后帮我摄像。"
    runtime, pid = completed_purchase(message, name="相机 C1", category="camera", quantity=1)
    assert not goal_receipts.completed_single_checkout(runtime, message, {pid})
