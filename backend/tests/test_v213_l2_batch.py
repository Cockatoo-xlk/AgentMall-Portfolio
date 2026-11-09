"""Synthetic batch shapes; never reconstructed historical Tool Arguments."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from multiagent_helpers import ai, call

from agentmall.agents.budgets import GraphBudget, RunStopped
from agentmall.agents.context import Constraints
from agentmall.agents.model_control import SpecialistGuard
from agentmall.agents.specialist_tools import ALLOWLISTS


def guard(*, read_only=False, role="aftersales", goal="prepare_return"):
    events = []
    runtime = SimpleNamespace(
        single=False,
        errors=[],
        constraints=Constraints(return_requested=True, reason_code="QUALITY_ISSUE"),
        tool_ids=set(),
        tool_repeats={},
        tool_allowlist=lambda target: ALLOWLISTS[target],
        budget=GraphBudget(),
        event=lambda kind, **payload: events.append({"kind": kind, **payload}),
    )
    context = SimpleNamespace(
        envelope=SimpleNamespace(target=role, goal=goal, read_only=read_only, subtask_id="step"),
        records=[],
        bound_tools={},
    )
    return SpecialistGuard(runtime, context), runtime, events


def wire(arguments, name="get_order", ident="synthetic_1"):
    return AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "id": ident,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ]
        },
    )


@pytest.mark.parametrize(
    "message,detail,repairable,fields",
    [
        (wire('{"order_id":'), "TOOL_ARGUMENT_JSON_INVALID", True, []),
        (wire('{"order_id":"a","order_id":"b"}'), "TOOL_ARGUMENT_DUPLICATE_KEY", False, []),
        (ai(call("get_order", {})), "TOOL_ARGUMENT_SCHEMA_INVALID", True, ["order_id"]),
        (
            ai(call("get_order", {"order_id": str(uuid4()), "PRIVATE-KEY": "PRIVATE-VALUE"})),
            "TOOL_ARGUMENT_SCHEMA_INVALID",
            True,
            [],
        ),
        (wire('{"store_id":', name="publish_product"), "TOOL_NOT_ALLOWLISTED", False, []),
        (
            ai(call("get_order", {"order_id": str(uuid4())}, ident="bad identity")),
            "TOOL_ID_INVALID_OR_REUSED",
            False,
            [],
        ),
        (
            ai(call("get_order", {"order_id": str(uuid4()), "store_id": str(uuid4())})),
            "TOOL_AUTHORITY_ARGUMENT_FORBIDDEN",
            False,
            ["store_id"],
        ),
        (
            ai(*[call("get_order", {"order_id": str(uuid4())}) for _ in range(5)]),
            "TOOL_BATCH_TOO_LARGE",
            True,
            [],
        ),
    ],
)
async def test_batch_failure_has_fixed_safe_subcode_without_executing(
    message, detail, repairable, fields
):
    middleware, runtime, events = guard()
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.code == "INVALID_TOOL_BATCH"
    assert caught.value.diagnostic_code == detail
    assert caught.value.repairable is repairable
    assert caught.value.fields == fields
    assert runtime.budget.used["tools"] == 0
    assert not runtime.tool_ids and not runtime.tool_repeats
    event = next(e for e in events if e["kind"] == "tool_batch_rejected")
    assert event["tools_executed"] is False
    assert event["phase"] == "MODEL_OUTPUT_VALIDATION"
    assert event["subtask_id"] == "step" and event["role"] == "aftersales"
    assert "PRIVATE" not in str(event)


async def test_valid_batch_and_reused_identity_are_not_retried():
    middleware, runtime, events = guard()
    message = ai(call("get_order", {"order_id": str(uuid4())}, ident="known"))
    await middleware.aafter_model({"messages": [message]}, None)
    assert runtime.budget.used["tools"] == 1
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "TOOL_ID_INVALID_OR_REUSED"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 1


async def test_read_only_policy_precedes_malformed_write_arguments():
    middleware, runtime, events = guard(read_only=True, goal="assess_return")
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [wire("{", name="prepare_return")]}, None)
    assert caught.value.diagnostic_code == "READ_ONLY_TOOL_VIOLATION"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_unauthorized_sibling_precedes_repairable_json_error():
    message = wire("{")
    message.additional_kwargs["tool_calls"].append(
        {
            "id": "unauthorized",
            "type": "function",
            "function": {"name": "execute_confirmed_action", "arguments": "{}"},
        }
    )
    middleware, runtime, events = guard()
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "TOOL_NOT_ALLOWLISTED"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_unordered_write_batch_is_wholly_rejected():
    middleware, runtime, events = guard()
    ident = str(uuid4())
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model(
            {
                "messages": [
                    ai(
                        call("get_order", {"order_id": ident}),
                        call(
                            "prepare_return",
                            {
                                "order_id": ident,
                                "reason_code": "QUALITY_ISSUE",
                                "description": "synthetic",
                            },
                        ),
                    )
                ]
            },
            None,
        )
    assert caught.value.code == "UNORDERED_WRITE_BATCH"
    assert caught.value.diagnostic_code == "TOOL_BATCH_UNORDERED_WRITE"
    assert caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_later_policy_violation_cannot_hide_behind_first_schema_error():
    middleware, runtime, events = guard()
    message = ai(
        call("get_order", {}),
        call("get_order", {"order_id": str(uuid4()), "store_id": str(uuid4())}),
    )
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "TOOL_AUTHORITY_ARGUMENT_FORBIDDEN"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_wire_and_sdk_arguments_must_match():
    middleware, runtime, events = guard()
    message = wire('{"order_id":"' + str(uuid4()) + '"}')
    message.tool_calls[0]["args"] = {"order_id": str(uuid4())}
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "MODEL_INVALID_TOOL_CALL"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


@pytest.mark.parametrize("malformed", [None, {}, [{"id": "shape", "function": None}]])
async def test_malformed_wire_structure_is_a_fixed_diagnostic(malformed):
    middleware, runtime, events = guard()
    message = AIMessage(content="")
    message.additional_kwargs["tool_calls"] = malformed
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "MODEL_INVALID_TOOL_CALL"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_repair_never_replays_previously_claimed_identical_tool():
    middleware, runtime, events = guard()
    args = {"order_id": str(uuid4())}
    await middleware.aafter_model({"messages": [ai(call("get_order", args))]}, None)
    middleware.context.repairing = True
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [ai(call("get_order", args))]}, None)
    assert caught.value.diagnostic_code == "TOOL_REPEATED_CALL"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 1


def test_diagnostic_projection_accepts_only_known_codes_and_field_names():
    from agentmall.infra.observability import public_summary

    value = public_summary(
        "tool_batch_rejected",
        {
            "diagnostic_code": "TOOL_ARGUMENT_SCHEMA_INVALID",
            "failure_class": "TOOL_SCHEMA_REJECTED",
            "violation_fields": ["order_id", "PRIVATE-ARBITRARY"],
            "repairable": True,
            "tools_executed": False,
            "repair_consumed": False,
            "phase": "MODEL_OUTPUT_VALIDATION",
            "arguments": "PRIVATE-ARGUMENTS",
            "budget": {"models": 4},
        },
    )
    assert value["diagnostic_code"] == "TOOL_ARGUMENT_SCHEMA_INVALID"
    assert value["violation_fields"] == ["order_id"]
    assert value["phase"] == "MODEL_OUTPUT_VALIDATION"
    assert "PRIVATE" not in str(value)
    assert "diagnostic_code" not in public_summary(
        "tool_batch_rejected", {"diagnostic_code": "PRIVATE-CODE"}
    )


@pytest.mark.parametrize("flags", [None, [{}], ["PRIVATE-CODE"]])
async def test_malformed_sdk_flags_are_rejected_without_echo(flags):
    middleware, runtime, events = guard()
    message = ai(call("get_order", {"order_id": str(uuid4())}))
    message.response_metadata["agentmall_tool_wire_failures"] = flags
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "MODEL_INVALID_TOOL_CALL"
    assert not caught.value.repairable
    assert "PRIVATE" not in str(events)


async def test_durable_claim_identity_collision_is_not_misclassified_or_repaired():
    middleware, runtime, events = guard()

    async def collision(identifiers, signatures):
        raise RunStopped("INVALID_TOOL_BATCH")

    runtime.budget.claim_tools = collision
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model(
            {"messages": [ai(call("get_order", {"order_id": str(uuid4())}))]}, None
        )
    assert caught.value.diagnostic_code == "TOOL_ID_INVALID_OR_REUSED"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


@pytest.mark.parametrize("representation", ["parsed", "invalid"])
async def test_raw_format_error_cannot_hide_sdk_only_unauthorized_call(representation):
    middleware, runtime, events = guard()
    message = wire("{")
    if representation == "parsed":
        message.tool_calls.append(call("execute_confirmed_action", {}, ident="forged"))
    else:
        message.invalid_tool_calls.append(
            {
                "name": "execute_confirmed_action",
                "args": "{",
                "id": "forged",
                "error": "ignored",
                "type": "invalid_tool_call",
            }
        )
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "TOOL_NOT_ALLOWLISTED"
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_raw_format_error_cannot_hide_inconsistent_sdk_identity():
    middleware, runtime, events = guard()
    message = wire("{")
    message.tool_calls.append(call("get_order", {"order_id": str(uuid4())}, ident="different"))
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert caught.value.diagnostic_code == "MODEL_INVALID_TOOL_CALL"
    assert not caught.value.repairable


@pytest.mark.parametrize("sdk_form", ["valid", "invalid"])
async def test_raw_invalid_json_cannot_hide_different_sdk_arguments(sdk_form):
    middleware, runtime, events = guard()
    message = wire("{")
    if sdk_form == "valid":
        message.invalid_tool_calls = []
        message.tool_calls = [
            call(
                "get_order",
                {"order_id": str(uuid4()), "store_id": str(uuid4())},
                ident="synthetic_1",
            )
        ]
    else:
        message.invalid_tool_calls[0]["args"] = '{"DIFFERENT":'
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [message]}, None)
    assert not caught.value.repairable
    assert runtime.budget.used["tools"] == 0


async def test_legacy_mixed_batch_public_code_does_not_authorize_policy_repair():
    middleware, runtime, events = guard(read_only=True, goal="assess_return")
    ident = str(uuid4())
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model(
            {
                "messages": [
                    ai(
                        call("get_order", {"order_id": ident}),
                        call(
                            "prepare_return",
                            {
                                "order_id": ident,
                                "reason_code": "QUALITY_ISSUE",
                                "description": "synthetic",
                            },
                        ),
                    )
                ]
            },
            None,
        )
    assert caught.value.code == "UNORDERED_WRITE_BATCH"
    assert caught.value.diagnostic_code == "READ_ONLY_TOOL_VIOLATION"
    assert not caught.value.repairable
    assert runtime.budget.orchestration_repair is None
    assert runtime.budget.used["tools"] == 0


@pytest.mark.parametrize("name", ["prepare_checkout", "prepare_return"])
async def test_single_unrequested_write_is_not_eligible_for_format_repair(name):
    middleware, runtime, events = guard(role="order", goal="inspect_orders")
    runtime.single = True
    runtime.constraints = Constraints()
    runtime.tool_allowlist = lambda role: tuple({n for names in ALLOWLISTS.values() for n in names})
    with pytest.raises(RunStopped) as caught:
        await middleware.aafter_model({"messages": [ai(call(name, {}))]}, None)
    assert caught.value.failure_class == "POLICY_DENIED"
    assert not caught.value.repairable
    assert runtime.budget.orchestration_repair is None
    assert runtime.budget.used["tools"] == 0
