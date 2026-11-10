"""Receipt gating and SDK parallel batch barrier; no model/business output invented."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from multiagent_helpers import ai, call
from test_v213_l2_batch import guard

from agentmall.agents.read_completion import finish_read_batch
from agentmall.agents.return_handoff import assessment_receipt
from agentmall.infra.observability import public_summary


def assessment(eligible=True):
    return SimpleNamespace(
        envelope=SimpleNamespace(goal="assess_return", read_only=True, subtask_id="assess"),
        records=[
            {
                "name": "get_order",
                "source_order_id": "order",
                "data": {"items": [{"version": 1, "policy_version": "v1", "items": []}]},
            },
            {
                "name": "check_eligibility",
                "source_order_id": "order",
                "data": {"eligible": eligible, "policy_version": "v1"},
            },
            {
                "name": "retrieve_policies",
                "source_order_id": "order",
                "citations": [{"id": "policy", "visibility": "public", "policy_version": "v1"}],
            },
        ],
    )


@pytest.mark.parametrize("fault", ["eligibility", "policy", "version", "private", "error"])
def test_incomplete_or_conflicting_receipts_never_finish(fault):
    context = assessment()
    if fault == "eligibility":
        context.records.pop(1)
    elif fault == "policy":
        context.records.pop()
    elif fault == "version":
        context.records[-1]["citations"][0]["policy_version"] = "other"
    elif fault == "private":
        context.records[-1]["citations"][0]["visibility"] = "private"
    else:
        context.records.append({"name": "check_eligibility", "error_code": "TOOL_FAILED"})
    proof = assessment_receipt(context)
    assert not proof["ready"] and not proof["reads_complete"]


def test_ineligible_read_result_is_complete_but_never_write_ready():
    proof = assessment_receipt(assessment(False))
    assert proof["reads_complete"] and not proof["ready"]


@pytest.mark.parametrize("single,bundle", [(True, None), (False, {"items": []})])
def test_single_and_bundle_reads_keep_original_model_loop(single, bundle):
    context = assessment()
    context.envelope.goal = "find_products"
    context.bound_tools = {"get_product": SimpleNamespace(return_direct=False)}
    runtime = SimpleNamespace(single=single, constraints=SimpleNamespace(bundle=bundle))
    finish_read_batch(runtime, context)
    assert not context.bound_tools["get_product"].return_direct
    assert not hasattr(context, "read_goal_completed")


@pytest.mark.parametrize("cancel", [False, True])
async def test_batch_barrier_waits_for_sibling_or_propagates_cancel(monkeypatch, cancel):
    from agentmall.agents import model_control

    middleware, _, _ = guard(role="shopping", goal="find_products", read_only=True)
    context = middleware.context
    context.observed = []
    context.bound_tools = {"retrieve_products": SimpleNamespace(return_direct=True)}
    calls = [call("retrieve_products", {"query": query}) for query in ("键盘", "静音键盘")]
    await middleware.aafter_model({"messages": [ai(*calls)]}, None)
    assert not context.bound_tools["retrieve_products"].return_direct
    finished = []
    monkeypatch.setattr(model_control, "finish_read_batch", lambda *args: finished.append(True))
    slow_started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if request.tool_call["id"] == calls[1]["id"]:
            slow_started.set()
            await release.wait()
        return ToolMessage(
            content=json.dumps({"ok": True, "data": {"items": []}}),
            name="retrieve_products",
            tool_call_id=request.tool_call["id"],
        )

    tasks = [
        asyncio.create_task(middleware.awrap_tool_call(SimpleNamespace(tool_call=c), handler))
        for c in calls
    ]
    try:
        await asyncio.wait_for(slow_started.wait(), 1)
        assert not tasks[0].done() and not finished
        if cancel:
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert all(isinstance(r, asyncio.CancelledError) for r in results)
            assert not finished and context.pending_tool_ids
        else:
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 1)
            assert finished == [True] and not context.pending_tool_ids
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_read_completion_diagnostic_is_allowlisted():
    result = public_summary(
        "read_goal_completed",
        {
            "completion_basis": "ASSESSMENT_RECEIPTS",
            "model_round_skipped": True,
            "tool_names": ["get_order", "execute_checkout", "private_sql"],
            "Authorization": "Bearer SYNTHETIC_SECRET",
            "prompt": "private prompt",
        },
    )
    assert result["completion_basis"] == "ASSESSMENT_RECEIPTS"
    assert result["model_round_skipped"] is True and result["tool_names"] == ["get_order"]
    assert "SYNTHETIC_SECRET" not in json.dumps(result) and "prompt" not in result
