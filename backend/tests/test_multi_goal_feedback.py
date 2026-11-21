"""Public explanations reflect catalog prices and the user's remaining work."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentmall.agents.context import Constraints
from agentmall.agents.graph import clarification_feedback
from agentmall.agents.specialist_tools import record_budget_conflict


@pytest.mark.parametrize("cap", [10000, 15000, 39800])
def test_budget_conflict_from_catalog_read(cap):
    item = SimpleNamespace(price_cents=19900, id=uuid4())
    runtime = SimpleNamespace(
        constraints=Constraints(quantity=2, purchase_requested=True, max_price_cents=cap),
        facts={},
    )
    assert record_budget_conflict(runtime, item) == (cap < 39800)
    if cap < 39800:
        assert runtime.facts == {
            ("checkout_budget_conflict", str(item.id)): {
                "quantity": 2,
                "unit_price_cents": 19900,
                "total_cents": 39800,
                "budget_cents": cap,
            }
        }
    else:
        assert runtime.facts == {}


@pytest.mark.parametrize(
    "followup,expected",
    [
        ("办完再查一遍我名下的全部订单", "订单查询仍待核实"),
        ("再查我名下的订单", "订单查询仍待核实"),
        ("成交后另买两件相同键盘", "第二笔购买仍待处理"),
        ("不要查看我的订单", "尚有需求"),
    ],
)
def test_clarification_after_first_receipt(followup, expected):
    runtime = SimpleNamespace(
        input=SimpleNamespace(message="请购买一件键盘。" + followup), facts={}
    )
    proposals = [{"data": {"action_type": "CHECKOUT", "status": "EXECUTED"}}]
    assert expected in clarification_feedback(runtime, proposals)
    assert "尚有需求" in clarification_feedback(runtime, [])


@pytest.mark.parametrize(
    "message",
    [
        "请申请质量退货。替换商品暂时不买，只处理退货这一件事。",
        "眼下商品和数量都还没定，请先问我想要哪种。",
    ],
)
async def test_explicit_scope_keeps_exploration_off_cards_and_thread(message, monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from test_v215_recommendations import product, runtime_for

    from agentmall.agents import memory
    from agentmall.agents.context import SpecialistResult
    from agentmall.agents.graph import render
    from agentmall.agents.specialist_tools import ref

    item = product(411, "有线")
    runtime = runtime_for(message, [item])
    original = ref("product", item.id, "original")
    runtime.references[("product", str(item.id), "original")] = original
    runtime.completed["read"] = SpecialistResult(
        subtask_id="read",
        target="shopping",
        status="done",
        summary="读取目录",
        entity_refs=list(runtime.references.values()),
    )
    runtime.facts[("retrieval_candidates", "read")] = {"items": [{"id": str(item.id)}]}
    if "先问我" in message:
        runtime.errors.append("PURCHASE_DETAILS_REQUIRED")
    result = render(runtime, "finish")
    assert result.entity_refs == result.results[0].entity_refs == [original]
    assert not result.facts
    assert item.name not in result.answer
    if "先问我" in message:
        assert "哪种商品" in result.answer and "地址" not in result.answer
    assert len(runtime.facts) == 2 and len(runtime.references) == 2
    runtime.candidate_lists = {str(uuid4()): {"items": [{}]}}
    runtime.thread_snapshot = {"version": 1, "preferences": {}}
    context = SimpleNamespace(version=1, provenance={})
    monkeypatch.setattr(memory, "locked_context", AsyncMock(return_value=context))
    session = Mock()
    await memory.publish_candidates(
        session, SimpleNamespace(context_snapshot=True, thread_id=uuid4()), runtime
    )
    session.add.assert_not_called()
    assert context.version == 1
