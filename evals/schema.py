"""Executable Episode contracts; expected answers are never a provider input."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["A1", "A2", "A3", "B1", "B2", "S1", "R1", "E1"]
DEV_COUNTS = dict(
    zip(
        ("A1", "A2", "A3", "B1", "B2", "S1", "R1", "E1"),
        (3, 3, 2, 3, 3, 2, 2, 2),
        strict=True,
    )
)
TEST_COUNTS = dict.fromkeys(DEV_COUNTS, 5)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InitialState(Strict):
    dataset: Literal["agentmall-synthetic-v1"] = "agentmall-synthetic-v1"
    order_state: Literal["NONE", "PENDING_PAYMENT", "DELIVERED"] = "NONE"
    order_owner: Literal["buyer1", "buyer2"] = "buyer1"
    order_count: int = Field(1, ge=1, le=2)
    original_sku: int = Field(1, ge=1, le=12)
    delivered_days_ago: int = Field(1, ge=0, le=30)
    catalog_variant: Literal[
        "normal", "no_stock", "delisted", "stale_index", "injection"
    ] = "normal"
    payment_result: Literal["SUCCEEDED", "DECLINED"] = "SUCCEEDED"


class Decision(Strict):
    action_type: Literal["CHECKOUT", "RETURN_REQUEST"]
    decision: Literal["approve", "reject", "wait"]
    quantity: int | None = Field(None, ge=1, le=10)
    max_total_cents: int | None = Field(None, ge=0)


class UserScript(Strict):
    clarifications: list[str] = Field(default_factory=list, max_length=2)
    decisions: list[Decision] = Field(default_factory=list, max_length=2)
    product_choice: Literal["first_matching_observed", "none"] = (
        "first_matching_observed"
    )


class Expected(Strict):
    delta: dict[str, int]
    original_order_status: str | None = None
    order_states: list[str] = Field(default_factory=list)
    case_states: list[str] = Field(default_factory=list)
    ticket_states: list[str] = Field(default_factory=list)
    output_statuses: list[str]
    run_statuses: list[str]
    max_total_cents: int | None = None
    quantity: int | None = None
    category: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    exclude_original: bool = False
    min_candidates: int = Field(0, ge=0, le=3)
    max_candidates: int = Field(3, ge=0, le=3)
    required_sources: list[str] = Field(default_factory=list)
    allowed_error_codes: list[str] = Field(default_factory=list)
    policy_version: str = "demo-v1"
    forbidden_effects: list[str]


class Fault(Strict):
    kind: Literal[
        "none",
        "price_change",
        "stock_loss",
        "start_reply_loss",
        "resume_reply_loss",
        "resume_replay",
        "before_execute",
        "after_commit",
        "final_answer",
        "provider_error",
        "invalid_schema",
        "unknown_tool",
        "forged_approval",
        "forged_actor",
        "forged_store",
        "forged_refund",
        "budget_exhaustion",
        "replacement_failure",
        "unknown_usage",
    ] = "none"
    once: bool = True


class Episode(Strict):
    task_id: str = Field(pattern=r"^eval_(dev|test)_[A-Z][0-9]_[0-9]{2}$")
    split: Literal["dev", "test"]
    category: Category
    user_goal: str = Field(min_length=1, max_length=2000)
    logical_time: datetime
    initial_state: InitialState
    actor: Literal["buyer1"] = "buyer1"
    resource_refs: dict[str, str]
    user_script: UserScript
    scripted_actions: list[
        Literal[
            "payment",
            "cancel",
            "expire",
            "replay_payment",
            "replay_cancel",
            "refund",
            "withdraw",
            "resolve_ticket",
        ]
    ] = Field(default_factory=list, max_length=4)
    fixture_program: list[
        Literal[
            "clarify",
            "products",
            "orders",
            "eligibility",
            "policies",
            "return",
            "checkout",
            "ticket",
        ]
    ] = Field(max_length=6)
    fault: Fault
    expected: Expected
    capability_notes: str
    annotation_source: Literal["single_codex_author_not_independent_annotation"]

    @model_validator(mode="after")
    def consistent(self):
        if self.logical_time.tzinfo is None or not self.task_id.startswith(
            f"eval_{self.split}_{self.category}_"
        ):
            raise ValueError("Task identity and aware logical clock required")
        if not self.expected.output_statuses or not self.expected.run_statuses:
            raise ValueError("Explicit acceptable terminal states required")
        if set(self.expected.delta) != {
            "orders",
            "aftersales_cases",
            "payments",
            "refunds",
            "support_tickets",
        }:
            raise ValueError("All business effect counts must be declared")
        if not self.expected.forbidden_effects:
            raise ValueError("Explicit forbidden effects required")
        return self


def load_tasks(path: Path, *, complete=True):
    tasks = [
        Episode.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError("Duplicate task identity")
    if not tasks or len({t.split for t in tasks}) != 1:
        raise ValueError("One nonempty split required")
    if complete and Counter(t.category for t in tasks) != (
        DEV_COUNTS if tasks[0].split == "dev" else TEST_COUNTS
    ):
        raise ValueError("Frozen category counts required")
    return tasks


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
    )
