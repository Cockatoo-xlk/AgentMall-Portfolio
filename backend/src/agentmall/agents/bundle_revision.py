"""Deterministic, current-request bundle deltas. Never accepts model-authored grants."""

import re
from copy import deepcopy
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmall.agents.bundle_contracts import BundlePart, BundleRequirements, clarify, quantity_word
from agentmall.catalog.categories import (
    CATEGORY_ALIASES,
    CATEGORY_LABELS,
    Category,
    ProductKind,
    categories_in_text,
)
from agentmall.retrieval.schemas import ProductQuery


class ConstraintPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: Literal["有线", "无线", "双模", "三模"] | None = None
    noise_preference: Literal["quiet"] | None = None
    screen_inches: str | None = Field(None, pattern=r"^\d{1,2}(?:\.\d)?$")
    usage: Literal["办公", "游戏", "宿舍"] | None = None
    max_price_cents: int | None = Field(None, strict=True, ge=0, le=100_000_000)
    layout: str | None = Field(None, max_length=20)
    keyboard_type: Literal["mechanical", "membrane"] | None = None
    activity: Literal["road_cycling"] | None = None
    product_kind: ProductKind | None = None
    excluded_connections: list[Literal["双模", "三模"]] | None = Field(None, max_length=2)

    @model_validator(mode="after")
    def no_implicit_clear(self):
        if any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("Only explicit non-null constraints; clearing is not an implicit edit")
        return self


class BundleOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_type: Literal[
        "KEEP", "REPLACE", "SET_CONSTRAINT", "ADD", "REMOVE", "UPDATE_BUDGET", "UPDATE_QUANTITY"
    ]
    target_category: Category | None = None
    new_constraints: ConstraintPatch | None = None
    requested_quantity: int | None = Field(None, strict=True, ge=1, le=10)
    budget_cents: int | None = Field(None, strict=True, gt=0, le=100_000_000)
    cheaper: bool = Field(False, strict=True)

    @model_validator(mode="after")
    def exact_fields(self):
        op = self.operation_type
        allowed = {"operation_type", "target_category"}
        if op == "UPDATE_BUDGET":
            allowed = {"operation_type", "budget_cents"}
            if self.budget_cents is None:
                raise ValueError("Budget required")
        elif op == "UPDATE_QUANTITY":
            allowed.add("requested_quantity")
            if self.requested_quantity is None:
                raise ValueError("Quantity required")
        else:
            if self.target_category is None:
                raise ValueError("Category required")
            if op in {"ADD", "SET_CONSTRAINT"}:
                allowed.add("new_constraints")
            if op == "ADD":
                allowed.add("requested_quantity")
            if op == "REPLACE":
                allowed.add("cheaper")
            if op == "SET_CONSTRAINT" and not (
                self.new_constraints and self.new_constraints.model_fields_set
            ):
                raise ValueError("Nonempty constraints required")
        if self.model_fields_set - allowed:
            raise ValueError("Fields do not apply to operation")
        return self


class BundleRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_bundle_id: UUID
    expected_context_version: int = Field(strict=True, ge=0)
    operations: list[BundleOperation] = Field(min_length=1, max_length=15)


def parse_operations(message):
    try:
        return _parse_operations(message)
    except ValueError as error:
        raise clarify() from error


def _parse_operations(message):
    """Finite grammar with residual rejection. Unsupported edit prose never disappears."""
    from agentmall.agents.purchase_intent import purchase_intent

    if message.strip() in {"应用组合修改", "按结构化参数修改组合"}:
        return None
    if purchase_intent(message).requested:
        if re.search(r"不要换|保持|保留|换个|换成|改成|改为|再加|增加|删除|总预算", message):
            raise clarify("BUNDLE_EDIT_PURCHASE_CONFLICT")
        return None
    if not re.search(
        r"必须|支持|不要|保持|保留|换|改|加|删除|移除|不要.+了|预算|[一二两三四五六七八九十\d]+\s*(?:台|副|件|只|把|个)",
        message,
    ):
        return None
    ops = []
    for raw in re.split(r"[，,。；;\n]|并且|然后|并|再", message):
        clause = raw.strip(" ：:!！?？")
        clause = re.sub(r"^(?:请|帮我|我改主意了)", "", clause)
        if not clause or clause in {
            "先推荐",
            "不要购买",
            "不要下单",
            "只推荐",
            "先看看",
            "重新推荐",
        }:
            continue
        budget = re.fullmatch(
            r"(?:总预算|预算)(?:提高到|降低到|改为|改成|是|为)?(\d+(?:\.\d{1,2})?)元", clause
        )
        if budget:
            ops.append(
                BundleOperation(
                    operation_type="UPDATE_BUDGET", budget_cents=int(Decimal(budget[1]) * 100)
                )
            )
            continue
        cats = categories_in_text(clause)
        if len(cats) != 1:
            raise clarify()
        category = next(iter(cats))
        rest = clause
        for alias in sorted(
            [category, CATEGORY_LABELS[category], *CATEGORY_ALIASES[category]],
            key=len,
            reverse=True,
        ):
            rest = rest.replace(alias, "")
        if rest in {"不要换", "保持", "保留", "保持不变", "不换"}:
            op = BundleOperation(operation_type="KEEP", target_category=category)
        elif rest in {"换个便宜的", "换便宜的", "换便宜一点", "换个更便宜的", "换便宜点"}:
            op = BundleOperation(operation_type="REPLACE", target_category=category, cheaper=True)
        elif rest in {"换一个", "换个", "重新选择", "换掉"}:
            op = BundleOperation(operation_type="REPLACE", target_category=category)
        elif rest in {"不要了", "删除", "移除", "去掉"}:
            op = BundleOperation(operation_type="REMOVE", target_category=category)
        elif re.fullmatch(r"(?:加|增加)(?:一个|一台|一副)?", rest):
            op = BundleOperation(operation_type="ADD", target_category=category)
        elif quantity := re.fullmatch(r"([一二两三四五六七八九十]|\d+)(?:台|副|件|只|把|个)", rest):
            op = BundleOperation(
                operation_type="UPDATE_QUANTITY",
                target_category=category,
                requested_quantity=quantity_word(quantity[1]),
            )
        else:
            match = re.fullmatch(
                r"(?:必须|改|改成|改为|要)?(?:支持)?(无线|有线|双模|三模)(?:连接|的)?", rest
            )
            if match:
                patch = {"connection": match[1]}
            elif re.fullmatch(r"(?:必须|改成|要)?(?:静音|安静)", rest):
                patch = {"noise_preference": "quiet"}
            elif screen := re.fullmatch(
                r"(?:必须|改成|改为|要)?(\d{1,2}(?:\.\d)?)(?:英寸|寸)", rest
            ):
                patch = {"screen_inches": screen[1]}
            else:
                raise clarify()
            op = BundleOperation(
                operation_type="SET_CONSTRAINT",
                target_category=category,
                new_constraints=ConstraintPatch(**patch),
            )
        ops.append(op)
    if not ops:
        raise clarify()
    return ops


def apply_revision(spec, items, operations):
    """Apply the entire delta, or reject it without persisting any partial changes."""
    parts = {p.category: deepcopy(p) for p in spec.parts}
    old = {i["category"]: i for i in items}
    refresh = set()
    reasons = {}
    seen = set()
    kinds = {}
    for op in operations:
        key = (op.target_category, op.operation_type)
        if key in seen:
            raise clarify("BUNDLE_CONFLICTING_OPERATIONS")
        seen.add(key)
        kinds.setdefault(op.target_category, set()).add(op.operation_type)
    for actions in kinds.values():
        if (
            ("REMOVE" in actions and len(actions) > 1)
            or ("ADD" in actions and len(actions) > 1)
            or ("KEEP" in actions and actions & {"REPLACE", "SET_CONSTRAINT"})
        ):
            raise clarify("BUNDLE_CONFLICTING_OPERATIONS")
    for op in operations:
        cat = op.target_category
        kind = op.operation_type
        if kind == "UPDATE_BUDGET":
            spec = spec.model_copy(update={"budget_cents": op.budget_cents})
            continue
        if kind == "UPDATE_QUANTITY" and cat is None:
            if any(o.operation_type == "UPDATE_QUANTITY" and o.target_category for o in operations):
                raise clarify("BUNDLE_CONFLICTING_OPERATIONS")
            parts = {
                c: p.model_copy(update={"quantity": op.requested_quantity})
                for c, p in parts.items()
            }
            continue
        if kind == "ADD":
            if cat in parts:
                raise clarify("BUNDLE_CATEGORY_ALREADY_PRESENT")
            parts[cat] = BundlePart(
                category=cat,
                quantity=op.requested_quantity,
                requirements=ProductQuery(
                    query=CATEGORY_LABELS[cat],
                    category=cat,
                    **(
                        op.new_constraints.model_dump(exclude_unset=True)
                        if op.new_constraints
                        else {}
                    ),
                ),
            )
            refresh.add(cat)
            reasons[cat] = "CATEGORY_ADDED"
            continue
        if cat not in parts:
            raise clarify("BUNDLE_CATEGORY_NOT_PRESENT")
        if kind == "REMOVE":
            del parts[cat]
            continue
        part = parts[cat]
        if kind == "UPDATE_QUANTITY":
            parts[cat] = part.model_copy(update={"quantity": op.requested_quantity})
        if kind in {"REPLACE", "SET_CONSTRAINT"}:
            values = part.requirements.model_dump(mode="json")
            if kind == "REPLACE":
                if cat not in old:
                    raise clarify("BUNDLE_SELECTION_REQUIRED")
                values["exclude_product_ids"] = list(
                    dict.fromkeys([*values["exclude_product_ids"], old[cat]["id"]])
                )
                if op.cheaper:
                    values["max_price_cents"] = min(
                        values["max_price_cents"]
                        if values["max_price_cents"] is not None
                        else 100_000_000,
                        old[cat]["price_cents"] - 1,
                    )
            else:
                values.update(op.new_constraints.model_dump(exclude_unset=True))
            # Query text must not silently reinfer an explicitly replaced old predicate.
            values["query"] = CATEGORY_LABELS[cat]
            try:
                parts[cat] = part.model_copy(
                    update={"requirements": ProductQuery.model_validate(values)}
                )
            except ValueError as error:
                raise clarify() from error
            refresh.add(cat)
            reasons[cat] = (
                "STRICTLY_CHEAPER_REPLACEMENT"
                if op.cheaper
                else "REPLACE_REQUESTED"
                if kind == "REPLACE"
                else "CONSTRAINT_CHANGED"
            )
    for op in operations:
        if op.operation_type == "REPLACE" and op.cheaper:
            part = parts[op.target_category]
            current = part.requirements.max_price_cents
            limit = min(
                current if current is not None else 100_000_000,
                old[op.target_category]["price_cents"] - 1,
            )
            parts[op.target_category] = part.model_copy(
                update={
                    "requirements": part.requirements.model_copy(update={"max_price_cents": limit})
                }
            )
    try:
        new = BundleRequirements(budget_cents=spec.budget_cents, parts=list(parts.values()))
    except ValueError as error:
        raise clarify("BUNDLE_CATEGORY_COUNT_REQUIRED") from error
    for part in new.parts:
        if part.category not in old:
            refresh.add(part.category)
            reasons.setdefault(part.category, "CATEGORY_ADDED")
    return new, sorted(refresh), reasons


def revision_diff(revision, result):
    before = {i["category"]: i for i in revision["items"]}
    after = {i["category"]: i for i in result.get("items", [])}
    changes = []
    for cat in dict.fromkeys([*before, *revision["current_categories"], *after]):
        a = before.get(cat)
        b = after.get(cat)
        changes.append(
            {
                "category": cat,
                "status": "REMOVED"
                if cat not in revision["current_categories"]
                else "UNRESOLVED"
                if b is None
                else "ADDED"
                if a is None
                else "KEPT"
                if a["id"] == b["id"]
                else "REPLACED",
                "old_item": a,
                "new_item": b,
                "delta_cents": (b["subtotal_cents"] if b else 0) - (a["subtotal_cents"] if a else 0)
                if result["status"] == "READY"
                else None,
                "retrieval": "REFRESHED" if cat in revision["refresh_categories"] else "REUSED",
                "reason": revision["reasons"].get(cat, "CURRENT_SKU_REVALIDATION"),
            }
        )
    return {
        "source_bundle_id": revision["source_bundle_id"],
        "operations": revision["operations"],
        "old_total_cents": revision["old_total_cents"],
        "new_total_cents": result.get("total_cents"),
        "old_budget_cents": revision["old_budget_cents"],
        "new_budget_cents": result.get("budget_cents"),
        "delta_cents": result["total_cents"] - revision["old_total_cents"]
        if result["status"] == "READY"
        else None,
        "changes": changes,
        "invalid_categories": revision.get("invalid_categories", []),
    }
