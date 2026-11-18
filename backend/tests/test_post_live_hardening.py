"""CONTRACT_TEST_ONLY: new development inputs; no historical Live replay."""

from copy import deepcopy
from uuid import uuid4

import pytest
from test_v215_recommendations import product, runtime_for

from agentmall.agents.context import SpecialistResult
from agentmall.agents.graph import render


@pytest.mark.parametrize("modes", [("有线", "有线", "无线"), ("无线", "有线", "无线")])
def test_final_recommendations_cap_exploration_and_preserve_comparison(modes):
    products = [product(201 + i, mode) for i, mode in enumerate(modes)]
    runtime = runtime_for("开发比较：对照有线和无线键盘，推荐两款，不购买", products)
    runtime.completed["explore"] = SpecialistResult(
        subtask_id="explore",
        target="shopping",
        status="done",
        summary="verified reads",
        entity_refs=list(runtime.references.values()),
    )
    original = deepcopy(runtime.facts)
    result = render(runtime, "finish")
    selected = [f for f in result.facts if f["kind"] == "product"]
    assert len(selected) == 2
    assert {f["data"]["attributes"]["connection"] for f in selected} == {"有线", "无线"}
    assert result.answer.count("商品 ") == 2
    assert {str(x.id) for x in result.entity_refs} == {f["id"] for f in selected}
    assert len(result.results[0].entity_refs) == 2
    assert runtime.facts == original and len(runtime.completed["explore"].entity_refs) == 3


def test_single_comparison_requires_one_dual_capability_product():
    runtime = runtime_for(
        "比较有线和无线键盘，推荐一款", [product(211, "有线"), product(212, "无线")]
    )
    assert render(runtime, "finish").status == "needs_input"


def test_dual_label_cannot_falsely_cover_explicit_wired_comparison():
    dual = product(223, "无线")
    dual.attributes = {"connection": "双模", "connection_capabilities": ["wired", "wireless"]}
    runtime = runtime_for("比较有线和无线键盘，推荐一款", [product(221, "有线"), dual])
    result = render(runtime, "finish")
    # Existing domain policy treats dual-mode as a wireless comparison option,
    # not as a replacement for the explicit wired-labelled option.
    assert result.status == "needs_input"
    assert len([f for f in result.facts if f["kind"] == "product"]) == 1


def test_purchase_does_not_trim_transaction_facts_by_recommendation_count():
    runtime = runtime_for(
        "推荐一款，准备购买一件键盘，送演示宿舍", [product(231, "有线"), product(232, "无线")]
    )
    assert len(render(runtime, "finish").facts) == 2


def test_production_clock_rollback_guard_still_stops_before_arm(tmp_path):
    from evals.smoke_runner import SmokeBatch, SmokeStopped
    from test_v217_smoke_contract import proposal

    now = [1000.0]
    gate = SmokeBatch(tmp_path / "clock.json", proposal(), "e" * 64, clock=lambda: now[0])
    now[0] -= 1
    with pytest.raises(SmokeStopped, match="CLOCK_ROLLBACK"):
        gate.arm("contract-A")
    assert gate.read()["tasks"] == []


def test_resume_command_is_prepared_only_from_the_current_successful_decision():
    from evals import smoke_cli

    assert callable(getattr(smoke_cli, "prepare_resume_command", None))
    pid, cid = str(uuid4()), str(uuid4())
    inspection = {"proposal": {"proposal_id": pid}}
    confirmed = {
        "proposal_id": pid,
        "confirmation_id": cid,
        "decision": "approve",
        "consumed_at": None,
    }
    command = smoke_cli.prepare_resume_command(inspection, confirmed)
    assert command["op"] == "resume" and command["confirmation_id"] == cid
    assert (
        command["request_id"]
        != smoke_cli.prepare_resume_command(inspection, confirmed)["request_id"]
    )
    for changes in (
        {"proposal_id": str(uuid4())},
        {"consumed_at": "already"},
        {"confirmation_id": None},
    ):
        with pytest.raises(smoke_cli.SmokeStopped):
            smoke_cli.prepare_resume_command(inspection, confirmed | changes)


async def test_projected_candidate_ranks_and_identity_follow_the_visible_subset(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agentmall.actions.service import payload_hash
    from agentmall.agents import memory

    products = [product(301, "有线"), product(302, "有线"), product(303, "无线")]
    runtime = runtime_for("比较有线和无线键盘，推荐两款", products)
    context = SimpleNamespace(version=1, preferences={}, focus={}, provenance={})
    runtime.thread_snapshot = {"version": 1, "preferences": {}}
    original_id = str(uuid4())
    runtime.candidate_lists = {
        original_id: {
            "preferences_digest": payload_hash({}),
            "items": [{"id": str(p.id), "rank": i + 1} for i, p in enumerate(products)],
        }
    }
    monkeypatch.setattr(memory, "locked_context", AsyncMock(return_value=context))
    monkeypatch.setattr(memory, "database_now", AsyncMock(return_value=None))
    session = SimpleNamespace(
        get=AsyncMock(return_value=None), add=lambda record: records.append(record)
    )
    run = SimpleNamespace(context_snapshot=True, thread_id=uuid4(), id=uuid4())
    records = []
    await memory.publish_candidates(session, run, runtime)
    first = records[0]
    assert [p["rank"] for p in first.items] == [1, 2]
    assert [p["id"] for p in first.items] == [str(products[0].id), str(products[2].id)]
    assert str(first.id) != original_id
    # A later explicit count clarification publishes a new immutable list.
    context.version = 1
    runtime.constraints.recommendation.count = 3
    await memory.publish_candidates(session, run, runtime)
    assert len(records[1].items) == 3 and records[1].id != first.id
    assert len(first.items) == 2  # Previously offered identity is never overwritten.
    context.version = 1
    runtime.thread_snapshot["preferences"] = {"max_price_cents": 30000}
    runtime.constraints.max_price_cents = 30000
    await memory.publish_candidates(session, run, runtime)
    assert records[2].items == records[1].items
    assert records[2].id != records[1].id  # Same items, different trusted preference binding.
    assert context.offered_ids == [str(records[2].id)]


async def test_mock_sdk_exploration_yields_two_final_products_through_real_api_sql(env, tmp_path):
    import json

    import httpx
    from evals.smoke_runner import SmokeBatch
    from evals.smoke_session import SmokeSession, sql_facts
    from retrieval_helpers import FixtureEncoder
    from test_v217_live1_transport import price
    from test_v217_smoke_contract import proposal

    p = proposal()
    p["tasks"][0]["user_request"] = (
        "开发合同样本：比较两款500元以内键盘，有线和无线都需覆盖，只比较不购买。"
    )
    gate = SmokeBatch(tmp_path / "batch.json", p, "d" * 64)
    gate.arm(p["tasks"][0]["id"])
    session = SmokeSession(gate, tmp_path / "dev-recommendation")
    selected_for_exploration = []

    def transport(role):
        def respond(request):
            body = json.loads(request.content)
            explored = any(m["role"] == "tool" for m in body["messages"])
            calls = (
                []
                if explored
                else [
                    {
                        "id": "dev_" + uuid4().hex,
                        "type": "function",
                        "function": {
                            "name": "get_product",
                            "arguments": json.dumps({"product_id": pid}),
                        },
                    }
                    for pid in selected_for_exploration
                ]
            )
            if not explored:
                calls.append(
                    {
                        "id": "dev_" + uuid4().hex,
                        "type": "function",
                        "function": {
                            "name": "retrieve_products",
                            "arguments": json.dumps({"query": "键盘"}),
                        },
                    }
                )
            message = {"role": "assistant", "content": '{"terminal":"finish"}'}
            if calls:
                message = {"role": "assistant", "content": "", "tool_calls": calls}
            return httpx.Response(
                200,
                json={
                    "id": "dev_" + uuid4().hex,
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls" if calls else "stop",
                            "message": message,
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
        response = await session.client.get("/api/v1/products", params={"limit": 100})
        products = response.json()["items"]
        for name in ("宿舍静音 K68", "静音 K87", "办公 K108"):
            selected_for_exploration.append(next(x["id"] for x in products if x["name"] == name))
        # Opt into the product's trusted thread context, using a fresh DEV Run.
        gate.start_episode()
        session.start_request_id = str(uuid4())
        response = await session.client.post(
            "/api/v1/agent/threads/" + session.thread_id + "/runs",
            headers=session.auth,
            json={
                "request_id": session.start_request_id,
                "message": p["tasks"][0]["user_request"],
                "expected_context_version": 0,
            },
        )
        assert response.status_code == 201, response.text
        run = session.run = response.json()
        assert run["status"] == "COMPLETED", run
        gate.end_episode()
        final_products = [x for x in run["result"]["facts"] if x["kind"] == "product"]
        assert len(final_products) == 2
        assert run["result"]["answer"].count("商品 ") == 2
        assert {x["data"]["attributes"]["connection"] for x in final_products} & {
            "双模",
            "三模",
            "无线",
        }
        assert run["budget"]["tools"] == 4  # All exploratory reads remain audited.
        facts = sql_facts(session.settings)
        assert not facts["orders"] and not facts["confirmations"] and not facts["proposals"]
        assert facts["checkpoint_count"] > 0
        context = await session.client.get(
            "/api/v1/agent/threads/" + session.thread_id, headers=session.auth
        )
        assert context.status_code == 200
        visible = {x["id"] for x in final_products}
        sets = context.json()["context"]["candidate_sets"]
        assert len(sets) == 1 and {x["id"] for x in sets[0]["items"]} == visible
        assert [x["rank"] for x in sets[0]["items"]] == [1, 2]
        value, evidence = await session.freeze_export_verify()
        assert len(evidence["product_facts"]) == 2
        gate.verified(value)
        await session.close()
        await session.cleanup("CONTRACT_TEST_ONLY-fresh-dev-owned-cleanup")
    finally:
        await session.close()
