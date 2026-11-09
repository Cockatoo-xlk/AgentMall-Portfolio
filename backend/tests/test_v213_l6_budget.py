"""Synthetic L5-shaped choices over real SDK/PG, never reconstructed model prose."""

import json
from contextlib import AsyncExitStack
from uuid import uuid4

import httpx
import pytest
from multiagent_helpers import ai, call, final, route
from sqlalchemy import text
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env
from test_v213_l4_business import goal, sdk, setup_order


class BudgetProgram:
    def __init__(self, order_id, profile="optimized", *, fault=None):
        self.order_id, self.profile, self.fault = order_id, profile, fault
        self.requests, self.counts = [], {}
        self.selection = None

    def plan(self, state):
        completed = {r["subtask_id"] for r in state["completed"]}
        if "assess" not in completed:
            return route("aftersales", "assess_return", "assess")
        if "return" not in completed:
            if self.fault == "expired_assessment":
                self.expire()
            return route(
                "aftersales", "prepare_return", "return", depends=["assess"], read_only=False
            )
        if "shop" not in completed:
            return route("shopping", "find_products", "shop", depends=["return"])
        if "buy" not in completed:
            return route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False)
        return route("finish")

    def choose(self, role, body):
        from langchain_core.messages import HumanMessage

        human = [
            HumanMessage(content=m["content"]) for m in body["messages"] if m["role"] == "user"
        ]
        state = json.loads(human[-1].content)
        tools = [m for m in body["messages"] if m["role"] == "tool"]
        if role == "supervisor":
            return self.plan(state)(human)
        if role == "aftersales":
            wire_names = {
                call["id"]: call["function"]["name"]
                for message in body["messages"]
                for call in message.get("tool_calls", [])
            }
            names = {wire_names[m["tool_call_id"]] for m in tools}
            if state["goal"] == "assess_return":
                if not tools:
                    reads = [
                        call("get_order", {"order_id": self.order_id}),
                        call(
                            "retrieve_policies",
                            {"order_id": self.order_id, "query": "质量问题退货期限"},
                        ),
                    ]
                    if self.fault == "missing_policy":
                        reads = [call("get_order", {"order_id": self.order_id})]
                    if self.fault == "illegal_batch":
                        reads += [
                            call(
                                "prepare_return",
                                {
                                    "order_id": self.order_id,
                                    "reason_code": "QUALITY_ISSUE",
                                    "description": "synthetic",
                                },
                            )
                        ]
                    if self.profile == "batched":
                        reads += [
                            call(
                                "check_eligibility",
                                {"order_id": self.order_id, "reason_code": "QUALITY_ISSUE"},
                            )
                        ]
                    return ai(*reads)
                if "check_eligibility" not in names and self.fault != "missing_eligibility":
                    return ai(
                        call(
                            "check_eligibility",
                            {"order_id": self.order_id, "reason_code": "QUALITY_ISSUE"},
                        )
                    )
                return final("评估结束（合成程序，非历史模型文字）。")
            if self.profile == "observed_shape" and not tools:
                return ai(
                    call("get_order", {"order_id": self.order_id}),
                    call(
                        "check_eligibility",
                        {"order_id": self.order_id, "reason_code": "QUALITY_ISSUE"},
                    ),
                )
            assert state["verified_assessments"][0]["ready"]
            return ai(
                call(
                    "prepare_return",
                    {
                        "order_id": self.order_id,
                        "reason_code": "QUALITY_ISSUE",
                        "description": "合成质量问题",
                    },
                )
            )
        if role == "shopping":
            return ai(call("retrieve_products", {"query": "静音键盘"})) if not tools else final()
        if not tools:
            facts = state.get("verified_candidates", [])
            if self.fault == "unobserved_product":
                return ai(call("prepare_checkout", {"product_id": str(uuid4())}))
            if self.profile == "observed_shape" or not facts:
                # Baseline fallback: same batch shape observed in L5, synthetic IDs from refs.
                refs = [
                    r
                    for r in state["entity_refs"]
                    if r["kind"] == "product" and r["relation"] == "replacement"
                ]
                return ai(*(call("get_product", {"product_id": r["id"]}) for r in refs[:3]))
            # Model simulator chooses by explicit facts, not fixed SKU or first rank.
            candidates = [
                f
                for f in facts
                if f["product"]["available"] >= 1 and f["product"]["price_cents"] <= 50000
            ]
            self.selection = min(
                candidates, key=lambda f: (f["product"]["price_cents"], f["product"]["id"])
            )["product"]["id"]
            return ai(call("get_product", {"product_id": self.selection}))
        product = json.loads(tools[0]["content"])["data"]
        if self.fault in {"price", "stock", "delist"}:
            self.change(product["id"])
        if self.selection is None:
            self.selection = product["id"]
        return ai(call("prepare_checkout", {"product_id": product["id"]}))

    def transport(self, role):
        def respond(request):
            body = json.loads(request.content)
            self.requests.append({"role": role, "body": body})
            self.counts[role] = self.counts.get(role, 0) + 1
            message = self.choose(role, body)
            calls = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": json.dumps(c["args"], ensure_ascii=False),
                    },
                }
                for c in message.tool_calls
            ]
            return httpx.Response(
                200,
                json={
                    "id": "mock-l6-" + str(len(self.requests)),
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if calls else "stop",
                            "message": {
                                "role": "assistant",
                                "content": message.content,
                                **({"tool_calls": calls} if calls else {}),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
                },
            )

        return httpx.MockTransport(respond)


def capture(env):
    # Separate synchronous engine/physical connection from async domain sessions.
    with env[1].connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        result = {}
        fields = {
            "orders": "id, proposal_id, status, total_cents, version",
            "order_items": "order_id, product_id, quantity, unit_price_cents",
            "aftersales_cases": "id, order_id, status",
            "confirmations": "id, proposal_id, decision, consumed_at, result_ref",
            "action_proposals": "id, action_type, status, canonical_payload, payload_hash",
            "products": "id, on_hand, reserved",
            "payments": "id, order_id, status",
            "idempotency_requests": "id, operation, action_id, result",
        }
        for table, projection in fields.items():
            result[table] = connection.scalar(
                text(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) "
                    f"FROM (SELECT {projection} FROM {table} ORDER BY id) t"
                )
            )
        return result


async def exercise(env, buyer, profile, *, record_property=None):
    order, original = await setup_order(env, buyer)
    before = capture(env)
    program = BudgetProgram(order["id"], profile)
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        tid = await thread(env, buyer)
        first = (await start(env, buyer, tid, message=goal(order))).json()
        if record_property:
            record_property("l6_first_phase", json.dumps(first))
            with env[1].connect() as connection:
                events = connection.scalar(
                    text(
                        "SELECT jsonb_agg(jsonb_build_object('kind',event_type)||payload_summary "
                        "ORDER BY seq) FROM run_events WHERE run_id=:id"
                    ),
                    {"id": first["id"]},
                )
            record_property("l6_first_events", json.dumps(events))
        assert first["status"] == "WAITING_INPUT", (
            first.get("last_error"),
            first.get("result"),
            program.counts,
        )
        assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        assert len(capture(env)["orders"]) == len(before["orders"])
        assert capture(env)["aftersales_cases"] == []
        cid1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        req1 = str(uuid4())
        second = (await resume(env, buyer, tid, first, cid1, req1)).json()
        assert second["status"] == "WAITING_INPUT", second
        assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
        waiting = capture(env)
        assert (
            len(waiting["aftersales_cases"]) == 1
            and waiting["aftersales_cases"][0]["status"] == "REQUESTED"
        )
        assert len(waiting["orders"]) == len(before["orders"])
        assert (await resume(env, buyer, tid, second, cid1)).status_code == 409
        cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        req2 = str(uuid4())
        done = (await resume(env, buyer, tid, second, cid2, req2)).json()
        assert done["status"] == "COMPLETED", done
        assert done["budget"]["models"] == (10 if profile == "batched" else 11)
        assert (await resume(env, buyer, tid, second, cid2, req2)).json() == done
        assert (await resume(env, buyer, tid, first, cid1, req1)).json() == done
        after = capture(env)
        assert len(after["orders"]) == len(before["orders"]) + 1
        assert len(after["aftersales_cases"]) == 1
        assert len(after["payments"]) == len(before["payments"])
        assert len(after["confirmations"]) == len(before["confirmations"]) + 2
        assert cid1 != cid2
        new_order = next(o for o in after["orders"] if o["id"] != order["id"])
        item = next(i for i in after["order_items"] if i["order_id"] == new_order["id"])
        assert new_order["status"] == "PENDING_PAYMENT"
        assert item["product_id"] != original and item["quantity"] == 1
        assert item["product_id"] == program.selection
        assert new_order["total_cents"] == item["unit_price_cents"] <= 50000
        old_stock = {p["id"]: p for p in before["products"]}
        for p in after["products"]:
            expected = old_stock[p["id"]] | (
                {"reserved": old_stock[p["id"]]["reserved"] + 1}
                if p["id"] == item["product_id"]
                else {}
            )
            assert p == expected
        assert done["budget"]["models"] == len(program.requests)
        assert done["budget"]["models"] <= (10 if profile == "batched" else 11)
        assert done["budget"]["delegations"] == 4 and done["budget"]["steps"] <= 24
        if record_property:
            record_property(
                "l6_database_oracle",
                json.dumps(
                    {
                        "before": before,
                        "waiting": waiting,
                        "after": after,
                        "budget": done["budget"],
                        "roles": program.counts,
                        "mode": "SDK_MOCK_TRANSPORT",
                        "decisions": "TEST_OPERATOR",
                    }
                ),
            )
    return done, program


@pytest.mark.parametrize("profile", ["optimized", "batched"])
async def test_full_sdk_b2_at_fixed_budget(durable_env, buyer, record_property, profile):
    await exercise(durable_env, buyer, profile, record_property=record_property)


async def test_completed_read_goal_is_not_redelegated_under_a_new_id(durable_env, buyer):
    from multiagent_helpers import install, make_models

    env = durable_env
    before = capture(env)
    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("shopping", "find_products", "new_id"),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
    )
    await install(env, models)
    result = (
        await start(
            env, buyer, await thread(env, buyer), message="推荐500元以内静音键盘，不要购买。 "
        )
    ).json()
    assert "REPEATED_DELEGATION" in result["result"]["error_codes"], result
    assert result["budget"]["delegations"] == 1
    assert capture(env) == before


@pytest.mark.parametrize("fault", ["missing_eligibility", "missing_policy", "illegal_batch"])
async def test_missing_reads_and_illegal_batch_never_create_proposal(durable_env, buyer, fault):
    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = capture(env)
    program = BudgetProgram(order["id"], fault=fault)
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        result = (await start(env, buyer, await thread(env, buyer), message=goal(order))).json()
        assert result["status"] == "PARTIAL", result
        assert capture(env) == before
        assessment = next(r for r in result["result"]["results"] if r["subtask_id"] == "assess")
        assert assessment["status"] != "done"
        if fault == "illegal_batch":
            assert result["budget"]["tools"] == 0


@pytest.mark.parametrize("fault", ["price", "stock", "delist", "unobserved_product"])
async def test_checkout_checks_current_facts_and_preserves_return(durable_env, buyer, fault):
    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = capture(env)
    program = BudgetProgram(order["id"], fault=fault)

    def change(product_id):
        update = {
            "price": "price_cents=price_cents+100,catalog_version=catalog_version+1",
            "stock": "on_hand=reserved",
            "delist": "active=false,catalog_version=catalog_version+1",
        }[fault]
        with env[1].begin() as connection:
            connection.execute(
                text(f"UPDATE products SET {update} WHERE id=:id"), {"id": product_id}
            )

    program.change = change
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        tid = await thread(env, buyer)
        first = (await start(env, buyer, tid, message=goal(order))).json()
        assert first["status"] == "WAITING_INPUT", first
        cid = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        result = (await resume(env, buyer, tid, first, cid)).json()
        assert result["status"] == "PARTIAL", result
        after = capture(env)
        assert len(after["aftersales_cases"]) == 1
        assert len(after["orders"]) == len(before["orders"])
        assert len(after["payments"]) == len(before["payments"])
        assert all(
            p["action_type"] != "CHECKOUT"
            for p in after["action_proposals"]
            if p["id"] not in {p["id"] for p in before["action_proposals"]}
        )
        assert all(p["reserved"] == 0 for p in after["products"])


async def test_return_model_reuses_receipts_without_removing_domain_revalidation(
    durable_env, buyer, monkeypatch
):
    from agentmall.agents import return_handoff

    actual = return_handoff.revalidate_return
    checked = []

    async def revalidate(*args, **kwargs):
        result = await actual(*args, **kwargs)
        checked.append(str(args[-1].id))
        return result

    monkeypatch.setattr(return_handoff, "revalidate_return", revalidate)
    done, program = await exercise(durable_env, buyer, "optimized")
    assert len(checked) >= 2
    prepare = [
        r
        for r in program.requests
        if r["role"] == "aftersales"
        and json.loads(next(m["content"] for m in r["body"]["messages"] if m["role"] == "user"))[
            "goal"
        ]
        == "prepare_return"
    ]
    assert len(prepare) == 1 and done["budget"]["models"] == 11


@pytest.mark.parametrize("cap", [4, 5])
async def test_lower_budget_still_stops_safely(durable_env, buyer, monkeypatch, cap):
    from agentmall.agents import run_service
    from agentmall.agents.budgets import Limits
    from agentmall.agents.durable_budget import DurableBudget

    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = capture(env)
    monkeypatch.setattr(
        run_service, "DurableBudget", lambda fence: DurableBudget(fence, Limits(models=cap))
    )
    program = BudgetProgram(order["id"])
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        tid = await thread(env, buyer)
        result = (await start(env, buyer, tid, message=goal(order))).json()
        if cap == 5:
            assert result["status"] == "WAITING_INPUT", result
            cid = await confirm(env, buyer, result["pending_confirmation"]["proposal_id"])
            result = (await resume(env, buyer, tid, result, cid)).json()
        assert result["status"] == "PARTIAL", result
        assert result["budget"]["models"] == cap
        assert "BUDGET_EXCEEDED" in result["result"]["error_codes"]
        after = capture(env)
        assert len(after["orders"]) == len(before["orders"])
        assert len(after["aftersales_cases"]) == (1 if cap == 5 else 0)


async def test_l5_shaped_control_preserves_one_case_and_no_checkout_at_12(
    durable_env, buyer, monkeypatch, record_property
):
    from agentmall.agents import model_control

    def no_shortcut(runtime, context):
        return None

    # Controlled ablation of only the new readonly completion hook. All budgets,
    # dynamic Supervisor model decisions, guards and domain services remain real.
    monkeypatch.setattr(model_control, "finish_read_batch", no_shortcut)
    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = capture(env)
    program = BudgetProgram(order["id"], "observed_shape")
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        tid = await thread(env, buyer)
        first = (await start(env, buyer, tid, message=goal(order))).json()
        cid = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        result = (await resume(env, buyer, tid, first, cid)).json()
        assert result["status"] == "PARTIAL" and result["last_error"] == "BUDGET_EXCEEDED"
        assert program.counts == {"supervisor": 4, "aftersales": 5, "shopping": 2, "order": 1}
        after = capture(env)
        assert len(after["orders"]) == len(before["orders"]) and len(after["aftersales_cases"]) == 1
        assert result["budget"]["models"] == 12 and result["budget"]["tools"] == 10
        record_property(
            "l6_l5_shaped_control",
            json.dumps(
                {
                    "mode": "SYNTHETIC_CONTROL_NOT_HISTORICAL_TRACE",
                    "budget": result["budget"],
                    "roles": program.counts,
                    "before": before,
                    "after": after,
                }
            ),
        )


async def test_frozen_multi_budget_fault_still_exhausts_without_completed_read_goal():
    from pathlib import Path

    from evals.fixtures import ROOT
    from evals.run import run_episode
    from evals.schema import load_tasks

    task = next(
        t
        for t in load_tasks(Path(ROOT) / "evals/data/agent_dev.jsonl")
        if t.task_id == "eval_dev_E1_02"
    )
    result = await run_episode(task, "multi", 0)
    assert result["success"], result["oracle"]
    assert result["model_calls"] == 12
    assert "BUDGET_EXCEEDED" in result["result"]["error_codes"]


async def test_elapsed_return_window_is_rechecked_even_with_same_version(durable_env, buyer):
    from datetime import UTC, datetime, timedelta

    from test_aftersales import rewrite_owned_order

    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = capture(env)
    program = BudgetProgram(order["id"], fault="expired_assessment")
    program.expire = lambda: rewrite_owned_order(
        env[1], order["id"], delivered_at=datetime.now(UTC) - timedelta(days=8)
    )
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        result = (await start(env, buyer, await thread(env, buyer), message=goal(order))).json()
        assert result["status"] == "PARTIAL", result
        assert "AFTERSALES_INELIGIBLE" in result["result"]["error_codes"]
        assert capture(env) == before
