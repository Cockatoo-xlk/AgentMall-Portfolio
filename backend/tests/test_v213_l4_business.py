"""Real SDK MockTransport + domain services + owned PostgreSQL, no Provider requests."""

import json
from contextlib import AsyncExitStack
from uuid import uuid4

import httpx
import pytest
from aftersales_helpers import delivered_order
from conftest import row
from multiagent_helpers import install, payload, route
from playground_helpers import SDKProgram
from t09_helpers import confirm, resume, start, thread
from t09_helpers import durable_env as durable_env

from agentmall.infra.llm import deepseek_model


class AssessmentProgram(SDKProgram):
    def __init__(self, order_id, *, fault=None):
        super().__init__("return_replace", order_id)
        self.fault = fault

    def transport(self, role):
        base = super().transport(role)

        def respond(request):
            body = json.loads(request.content)
            data = next(
                (json.loads(m["content"]) for m in body["messages"] if m["role"] == "user"), {}
            )
            if (
                role == "aftersales"
                and self.fault == "before_tool"
                and data.get("goal") == "prepare_return"
            ):
                self.change()  # Concurrent change AFTER dispatch, before tool execution.
            return base.handle_request(request)

        return httpx.MockTransport(respond)

    def plan(self, messages):
        state = payload(messages)
        completed = {r["subtask_id"] for r in state["completed"]}
        if "assessment" not in completed:
            return route("aftersales", "assess_return", "assessment")(messages)
        if self.fault == "readonly_only":
            return route("finish")(messages)
        if "return" not in completed:
            if self.fault == "before_dispatch":
                self.change()  # Test-controlled concurrent DB change, never production routing.
            return route(
                "aftersales",
                "prepare_return",
                "return",
                depends=[] if self.fault == "no_dependency" else ["assessment"],
                read_only=self.fault == "implicit_readonly",
            )(messages)
        if "shop" not in completed:
            return route("shopping", "find_products", "shop", depends=["return"])(messages)
        if "buy" not in completed:
            return route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False)(
                messages
            )
        return route("finish")(messages)


async def sdk(env, program, stack):
    models = {}
    for role in ("supervisor", "aftersales", "shopping", "order"):
        transport = program.transport(role)
        sync = stack.enter_context(httpx.Client(transport=transport, trust_env=False))
        client = await stack.enter_async_context(
            httpx.AsyncClient(transport=transport, trust_env=False)
        )
        models[role] = deepseek_model(
            "offline-placeholder", http_client=sync, http_async_client=client
        )
    return await install(env, models)


def counts(env):
    return dict(
        row(
            env[1],
            "SELECT (SELECT count(*) FROM action_proposals WHERE "
            "action_type='RETURN_REQUEST') returns, "
            "(SELECT count(*) FROM aftersales_cases) cases, "
            "(SELECT count(*) FROM orders) orders, "
            "(SELECT count(*) FROM payments) payments, "
            "(SELECT count(*) FROM confirmations) confirmations",
        )
    )


async def setup_order(env, buyer):
    product = row(env[1], "SELECT id FROM products WHERE category='keyboard' ORDER BY id LIMIT 1")[
        "id"
    ]
    return await delivered_order(env[0], buyer, str(product)), str(product)


def goal(order):
    return (
        f"订单{order['id']}有质量问题，申请退货，"
        "再推荐另一款500元以内的静音键盘，准备购买一件，送演示宿舍。"
    )


async def test_sdk_assess_then_authorized_return_then_purchase(durable_env, buyer, record_property):
    env = durable_env
    order, original = await setup_order(env, buyer)
    before = counts(env)
    inventory = row(env[1], "SELECT sum(on_hand) on_hand, sum(reserved) reserved FROM products")
    program = AssessmentProgram(order["id"])
    async with AsyncExitStack() as stack:
        trace = await sdk(env, program, stack)
        tid = await thread(env, buyer)
        first = (await start(env, buyer, tid, message=goal(order))).json()
        assert first["status"] == "WAITING_INPUT", (first, trace)
        assert first["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        assert counts(env) == before | {"returns": 1}
        cid1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
        request1 = str(uuid4())
        second = (await resume(env, buyer, tid, first, cid1, request1)).json()
        assert second["status"] == "WAITING_INPUT", (second, trace)
        assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
        assert counts(env)["orders"] == before["orders"]
        assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
        assert (await resume(env, buyer, tid, second, cid1)).status_code == 409
        # No second decision: no order. Only TEST_OPERATOR explicitly approves below.
        cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
        request2 = str(uuid4())
        done = (await resume(env, buyer, tid, second, cid2, request2)).json()
        assert done["status"] == "COMPLETED", (done, trace)
        assert (await resume(env, buyer, tid, second, cid2, request2)).json() == done
        assert (await resume(env, buyer, tid, first, cid1, request1)).json() == done
        assert counts(env) == before | {
            "returns": 1,
            "cases": 1,
            "orders": before["orders"] + 1,
            "confirmations": before["confirmations"] + 2,
        }
        actual = row(
            env[1],
            "SELECT o.id, o.status, o.total_cents, i.product_id, i.quantity, "
            "i.unit_price_cents, p.reserved, p.attributes, p.on_hand FROM orders o "
            "JOIN order_items i ON i.order_id=o.id "
            "JOIN products p ON p.id=i.product_id WHERE o.id <> :old",
            old=order["id"],
        )
        assert actual["status"] == "PENDING_PAYMENT"
        assert str(actual["product_id"]) != original and actual["quantity"] == 1
        assert actual["total_cents"] == actual["unit_price_cents"] <= 50000
        assert actual["attributes"]["noise"] in {"静音", "较安静"}
        now = row(env[1], "SELECT sum(on_hand) on_hand, sum(reserved) reserved FROM products")
        assert now == {"on_hand": inventory["on_hand"], "reserved": inventory["reserved"] + 1}
        assert actual["reserved"] == 1
        budgets = done["budget"]
        assert budgets["models"] == len(program.requests) == 11
        assert budgets["tools"] == 6 and budgets["delegations"] == 4
        assert budgets["steps"] <= 24 and budgets["output_tokens"] <= 12000
        events = row(
            env[1],
            "SELECT jsonb_agg(jsonb_build_object('kind', event_type) || "
            "payload_summary ORDER BY seq) events FROM run_events WHERE run_id=:id",
            id=done["id"],
        )["events"]
        visible = [e for e in events if e["kind"] == "task_tools_visible"]
        assert all(
            "prepare_return" not in e["tool_names"] for e in visible if e["goal"] == "assess_return"
        )
        assert any(e["kind"] == "return_assessment_completed" and e["ok"] for e in events)
        record_property(
            "database_oracle",
            json.dumps(
                {
                    "counts": counts(env),
                    "order": actual,
                    "inventory_before": inventory,
                    "inventory_after": now,
                    "budget": budgets,
                    "mode": "SDK_MOCK_TRANSPORT_FIXTURE",
                    "decisions": "TEST_OPERATOR",
                },
                default=str,
            ),
        )


@pytest.mark.parametrize("fault", ["no_dependency", "implicit_readonly"])
async def test_invalid_write_handoff_has_no_business_writes(durable_env, buyer, fault):
    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = counts(env)
    program = AssessmentProgram(order["id"], fault=fault)
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        result = (await start(env, buyer, await thread(env, buyer), message=goal(order))).json()
        assert result["status"] == "PARTIAL", result
        assert counts(env) == before
        assert program.counts["aftersales"] == 2


async def test_policy_only_never_prepares_return(durable_env, buyer):
    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = counts(env)
    program = AssessmentProgram(order["id"], fault="readonly_only")
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        result = (
            await start(
                env,
                buyer,
                await thread(env, buyer),
                message=f"订单{order['id']}质量问题可以退货吗？只查退货资格和政策，不申请退货。",
            )
        ).json()
        assert result["status"] == "COMPLETED", result
        assert counts(env) == before


@pytest.mark.parametrize(
    "column,value", [("version", "version+1"), ("policy_version", "'changed-policy'")]
)
@pytest.mark.parametrize("when", ["before_dispatch", "before_tool"])
async def test_changed_order_or_policy_cannot_use_assessed_evidence(
    durable_env, buyer, column, value, when
):
    from sqlalchemy import text

    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = counts(env)
    program = AssessmentProgram(order["id"], fault=when)

    def change():
        if column == "policy_version":
            from test_aftersales import rewrite_owned_order

            # Explicit chaos fixture: the immutable order snapshot normally forbids this.
            rewrite_owned_order(env[1], order["id"], policy_version="changed-policy")
            return
        with env[1].begin() as connection:
            connection.execute(
                text(f"UPDATE orders SET {column}={value} WHERE id=:id"), {"id": order["id"]}
            )

    program.change = change
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        result = (await start(env, buyer, await thread(env, buyer), message=goal(order))).json()
        assert result["status"] == "PARTIAL", result
        assert counts(env) == before
        assert program.counts["aftersales"] == (2 if when == "before_dispatch" else 3)
        current = row(
            env[1], "SELECT version, policy_version FROM orders WHERE id=:id", id=order["id"]
        )
        assert current[column] != order[column]


@pytest.mark.parametrize(
    "scenario", ["no_return_intent", "ineligible", "existing_proposal", "foreign_order"]
)
async def test_assessment_does_not_authorize_illegal_return(durable_env, buyer, buyer2, scenario):
    from aftersales_helpers import return_proposal
    from lifecycle_helpers import create_order

    env = durable_env
    order, _ = await setup_order(env, buyer2 if scenario == "foreign_order" else buyer)
    if scenario == "ineligible":
        product = row(
            env[1], "SELECT id FROM products WHERE category='keyboard' ORDER BY id LIMIT 1"
        )["id"]
        order = await create_order(env[0], buyer, str(product))
    if scenario == "existing_proposal":
        await return_proposal(env[0], buyer, order)
    before = counts(env)
    program = AssessmentProgram(order["id"])
    message = (
        goal(order)
        if scenario != "no_return_intent"
        else f"订单{order['id']}有质量问题，查询资格与政策，不申请退货。"
    )
    async with AsyncExitStack() as stack:
        trace = await sdk(env, program, stack)
        result = (await start(env, buyer, await thread(env, buyer), message=message)).json()
        assert result["status"] == "PARTIAL", (result, trace)
        assert counts(env) == before
        assert result["pending_confirmation"] is None


async def test_rejected_return_is_not_approval_and_purchase_still_requires_own_decision(
    durable_env, buyer
):
    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = counts(env)
    program = AssessmentProgram(order["id"])
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        tid = await thread(env, buyer)
        first = (await start(env, buyer, tid, message=goal(order))).json()
        assert first["status"] == "WAITING_INPUT", first
        reject = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"], "reject")
        second = (await resume(env, buyer, tid, first, reject)).json()
        assert second["status"] == "WAITING_INPUT", second
        assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
        assert counts(env)["cases"] == 0 and counts(env)["orders"] == before["orders"]
        assert (await resume(env, buyer, tid, second, reject)).status_code == 409
        assert counts(env)["orders"] == before["orders"]


async def test_expired_pending_return_does_not_block_new_assessed_proposal(durable_env, buyer):
    from aftersales_helpers import return_proposal
    from checkout_helpers import timed_proposal

    env = durable_env
    order, _ = await setup_order(env, buyer)
    prior = await return_proposal(env[0], buyer, order)
    expired = timed_proposal(env[1], prior, -1)
    await confirm(env, buyer, prior["proposal_id"], "reject")
    assert (
        row(env[1], "SELECT status FROM action_proposals WHERE id=:id", id=expired["proposal_id"])[
            "status"
        ]
        == "PENDING"
    )
    program = AssessmentProgram(order["id"])
    async with AsyncExitStack() as stack:
        await sdk(env, program, stack)
        result = (await start(env, buyer, await thread(env, buyer), message=goal(order))).json()
        assert result["status"] == "WAITING_INPUT", result
        assert result["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
        assert result["pending_confirmation"]["proposal_id"] not in {
            prior["proposal_id"],
            expired["proposal_id"],
        }
        assert counts(env)["cases"] == 0


async def test_two_origins_cannot_prepare_duplicate_return(durable_env, buyer, monkeypatch):
    import asyncio
    from uuid import UUID

    from sqlalchemy import select

    from agentmall.aftersales import service as aftersales
    from agentmall.agents.budgets import GraphBudget
    from agentmall.agents.context import MultiRequest, SpecialistResult, TaskSpec
    from agentmall.agents.return_handoff import record_assessment
    from agentmall.agents.runtime import RunContext
    from agentmall.agents.specialist_tools import SpecialistTools
    from agentmall.identity.models import User
    from agentmall.identity.service import actor_for

    env = durable_env
    order, _ = await setup_order(env, buyer)
    before = counts(env)
    await install(env, {})
    async with env[2].state.sessions.begin() as session:
        actor = actor_for(await session.scalar(select(User).where(User.login == "buyer1")), env[3])
    contexts = []
    for _ in range(2):
        runtime = RunContext(
            actor,
            env[3],
            env[2].state.sessions,
            MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=goal(order)),
            {},
            env[2].state.retrieval_encoder,
            GraphBudget(),
            {},
        )
        await runtime.hydrate_explicit_entities()
        task = TaskSpec(
            subtask_id="assess",
            target="aftersales",
            goal="assess_return",
            constraints=runtime.handoff_constraints(),
            read_only=True,
        )
        envelope = (await runtime.validate_tasks([task]))[0]
        tools = SpecialistTools(runtime, envelope)
        for name, args in [
            ("get_order", {"order_id": order["id"]}),
            ("check_eligibility", {"order_id": order["id"], "reason_code": "QUALITY_ISSUE"}),
            ("retrieve_policies", {"order_id": order["id"], "query": "质量问题退货期限"}),
        ]:
            assert (await tools.execute(name, args))["ok"]
        completed = SpecialistResult(
            subtask_id="assess", target="aftersales", status="done", summary="verified"
        )
        record_assessment(runtime, tools, completed)
        runtime.completed["assess"] = completed
        runtime.pending.pop("assess")
        task = TaskSpec(
            subtask_id="prepare",
            target="aftersales",
            goal="prepare_return",
            constraints=runtime.handoff_constraints(),
            read_only=False,
            entity_refs=list(runtime.references.values()),
            evidence_refs=[UUID(c) for c in runtime.citations],
            depends_on=["assess"],
        )
        envelope = (await runtime.validate_tasks([task]))[0]
        contexts.append(SpecialistTools(runtime, envelope))
    original = aftersales.prepare_action

    async def delayed(*args, **kwargs):
        # Widen the race after the duplicate query but before domain preparation.
        # The adapter must retain its owned-order lock over this gap.
        await asyncio.sleep(0.05)
        return await original(*args, **kwargs)

    monkeypatch.setattr(aftersales, "prepare_action", delayed)
    results = await asyncio.gather(
        *(
            c.execute(
                "prepare_return",
                {
                    "order_id": order["id"],
                    "reason_code": "QUALITY_ISSUE",
                    "description": "synthetic",
                },
            )
            for c in contexts
        )
    )
    assert sum(result["ok"] for result in results) == 1, results
    assert {result["error_code"] for result in results if not result["ok"]} == {
        "RETURN_PROPOSAL_EXISTS"
    }
    assert counts(env) == before | {"returns": 1}
