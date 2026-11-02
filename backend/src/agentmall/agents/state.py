"""JSON-only recovery state. Authentication and dependency objects never cross this boundary."""

from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import Field

from agentmall.agents.context import (
    Constraints,
    EntityRef,
    HandoffEnvelope,
    MultiRequest,
    SpecialistResult,
    Strict,
)


class RuntimeState(Strict):
    version: Literal[1] = 1
    input: MultiRequest
    constraints: Constraints
    references: dict[str, EntityRef] = Field(default_factory=dict)
    facts: dict[str, dict] = Field(default_factory=dict)
    candidate_lists: dict[str, dict] = Field(default_factory=dict)
    citations: dict[str, dict] = Field(default_factory=dict)
    completed: dict[str, SpecialistResult] = Field(default_factory=dict)
    pending: dict[str, HandoffEnvelope] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    seen_tasks: list[str] = Field(default_factory=list)
    signatures: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    tool_repeats: dict[str, int] = Field(default_factory=dict)
    schema_repairs: int = 0
    explicit_order_ids: list[UUID] = Field(default_factory=list)
    budget: dict = Field(default_factory=dict)


def snapshot(runtime):
    return RuntimeState(
        input=runtime.input,
        constraints=runtime.constraints,
        references={"|".join(k): v for k, v in runtime.references.items()},
        facts={"|".join(k): v for k, v in runtime.facts.items()},
        citations=runtime.citations,
        candidate_lists=runtime.candidate_lists,
        completed=runtime.completed,
        pending={k: v for k, v in runtime.pending.items() if k not in runtime.completed},
        errors=runtime.errors,
        seen_tasks=sorted(runtime.seen_tasks),
        signatures=sorted(runtime.signatures),
        tool_ids=sorted(runtime.tool_ids),
        tool_repeats=runtime.tool_repeats,
        schema_repairs=runtime.schema_repairs,
        explicit_order_ids=sorted(runtime.explicit_order_ids, key=str),
        budget=runtime.budget.snapshot(),
    ).model_dump(mode="json")


def restore(runtime, data):
    state = RuntimeState.model_validate(data)
    runtime.input = state.input
    runtime.constraints = state.constraints
    runtime.references = {tuple(k.split("|")): v for k, v in state.references.items()}
    runtime.facts = {tuple(k.split("|")): v for k, v in state.facts.items()}
    for name in (
        "candidate_lists",
        "citations",
        "completed",
        "pending",
        "errors",
        "tool_repeats",
        "schema_repairs",
    ):
        setattr(runtime, name, getattr(state, name))
    for name in ("seen_tasks", "signatures", "tool_ids", "explicit_order_ids"):
        setattr(runtime, name, set(getattr(state, name)))
    runtime.pending = {k: v for k, v in runtime.pending.items() if k not in runtime.completed}
    return runtime


MAPS = {
    "candidate_lists",
    "references",
    "facts",
    "citations",
    "completed",
    "pending",
    "tool_repeats",
}
SETS = {"errors", "seen_tasks", "signatures", "tool_ids", "explicit_order_ids"}


def delta(before, after):
    result = {}
    for key, value in after.items():
        if key in MAPS:
            result[key] = {k: v for k, v in value.items() if before.get(key, {}).get(k) != v}
        elif key in SETS:
            result[key] = [v for v in value if v not in before.get(key, [])]
        elif before.get(key) != value:
            result[key] = value
    return result


def merge_state(left, right):
    result = deepcopy(left)
    for key, value in right.items():
        if key in MAPS:
            result[key] = {**result.get(key, {}), **value}
        elif key in SETS:
            result[key] = sorted(set(result.get(key, [])) | set(value))
        elif key == "schema_repairs":
            result[key] = max(result.get(key, 0), value)
        else:
            result[key] = deepcopy(value)
    result["pending"] = {
        k: v for k, v in result.get("pending", {}).items() if k not in result.get("completed", {})
    }
    return result
