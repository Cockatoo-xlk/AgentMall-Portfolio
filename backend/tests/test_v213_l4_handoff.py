"""Task-scoped authorization; synthetic decisions, never historical model output."""

from types import SimpleNamespace

import pytest

from agentmall.agents.specialist_tools import ALLOWLISTS, build_specialist_tools


@pytest.mark.parametrize(
    "role,goal,read_only,expected",
    [
        (
            "aftersales",
            "assess_return",
            True,
            {"get_order", "check_eligibility", "retrieve_policies"},
        ),
        (
            "aftersales",
            "assess_return",
            False,
            {"get_order", "check_eligibility", "retrieve_policies"},
        ),
        (
            "aftersales",
            "prepare_return",
            False,
            {"get_order", "check_eligibility", "retrieve_policies", "prepare_return"},
        ),
        (
            "aftersales",
            "human_support",
            False,
            {"get_order", "check_eligibility", "retrieve_policies", "create_support_ticket"},
        ),
        ("order", "inspect_orders", True, {"list_orders", "get_order", "get_product", "get_cart"}),
        (
            "order",
            "prepare_checkout",
            True,
            {"list_orders", "get_order", "get_product", "get_cart"},
        ),
        ("order", "prepare_checkout", False, set(ALLOWLISTS["order"])),
        ("shopping", "find_products", True, set(ALLOWLISTS["shopping"])),
    ],
)
def test_model_sees_only_current_task_tools(role, goal, read_only, expected):
    runtime = SimpleNamespace(
        single=False,
        constraints=SimpleNamespace(bundle=None),
        tool_allowlist=lambda role: ALLOWLISTS[role],
    )
    context = SimpleNamespace(
        runtime=runtime, envelope=SimpleNamespace(target=role, goal=goal, read_only=read_only)
    )
    assert {tool.name for tool in build_specialist_tools(context)} == expected


def test_single_keeps_legal_union():
    union = tuple(dict.fromkeys(name for tools in ALLOWLISTS.values() for name in tools))
    runtime = SimpleNamespace(
        single=True, constraints=SimpleNamespace(bundle=None), tool_allowlist=lambda role: union
    )
    context = SimpleNamespace(
        runtime=runtime,
        envelope=SimpleNamespace(target="order", goal="inspect_orders", read_only=False),
    )
    assert {tool.name for tool in build_specialist_tools(context)} == set(union)


@pytest.mark.parametrize(
    "read_only,detail", [(True, "READ_ONLY_TOOL_VIOLATION"), (False, "TOOL_WRITE_SCOPE_VIOLATION")]
)
async def test_hidden_write_forgery_still_rejected(read_only, detail):
    from uuid import uuid4

    from multiagent_helpers import ai, call
    from test_v213_l2_batch import guard

    from agentmall.agents.budgets import RunStopped

    middleware, runtime, _ = guard(read_only=read_only, goal="assess_return")
    with pytest.raises(RunStopped) as exc:
        await middleware.aafter_model(
            {
                "messages": [
                    ai(
                        call(
                            "prepare_return",
                            {
                                "order_id": str(uuid4()),
                                "reason_code": "QUALITY_ISSUE",
                                "description": "synthetic",
                            },
                        )
                    )
                ]
            },
            None,
        )
    assert exc.value.diagnostic_code == detail
    assert runtime.budget.used["tools"] == 0


def test_assessment_summary_without_receipts_is_not_evidence():
    from agentmall.agents.context import SpecialistResult
    from agentmall.agents.return_handoff import record_assessment

    runtime = SimpleNamespace(single=False, facts={}, event=lambda *args, **kwargs: None)
    context = SimpleNamespace(
        envelope=SimpleNamespace(goal="assess_return", read_only=True, subtask_id="assess"),
        records=[],
    )
    result = SpecialistResult(
        subtask_id="assess", target="aftersales", status="done", summary="eligible"
    )
    record_assessment(runtime, context, result)
    assert runtime.facts[("return_assessment", "assess")]["ready"] is False


def test_new_multi_write_cannot_skip_assessment():
    from agentmall.agents.budgets import RunStopped
    from agentmall.agents.return_handoff import assessment_for

    with pytest.raises(RunStopped, match="RETURN_ASSESSMENT_REQUIRED"):
        assessment_for(SimpleNamespace(facts={}, pending={}), SimpleNamespace(depends_on=[]))


def test_task_visibility_diagnostic_omits_private_input():
    from agentmall.infra.observability import public_summary

    value = public_summary(
        "task_tools_visible",
        {
            "role": "aftersales",
            "goal": "assess_return",
            "read_only": True,
            "tool_names": ["get_order", "unknown_private_tool"],
            "prompt": "PRIVATE",
            "arguments": {"secret": "PRIVATE"},
        },
    )
    assert value == {
        "role": "aftersales",
        "goal": "assess_return",
        "read_only": True,
        "tool_names": ["get_order"],
    }
