"""Public metadata projection of RunEvent, never an alternative event store."""

import asyncio
import re
from uuid import UUID

ROLES = {"supervisor", "shopping", "order", "aftersales", "single"}
GOALS = {
    "find_products",
    "inspect_orders",
    "prepare_checkout",
    "assess_return",
    "prepare_return",
    "human_support",
}
TOOLS = {
    "retrieve_bundle_candidates",
    "prepare_bundle_checkout",
    "retrieve_products",
    "retrieve_policies",
    "get_product",
    "get_cart",
    "get_order",
    "list_orders",
    "prepare_checkout",
    "check_eligibility",
    "prepare_return",
    "create_support_ticket",
    "get_case",
    "get_support_ticket",
}
CONSTRAINT_FIELDS = {
    "bundle",
    "max_price_cents",
    "category",
    "noise_preference",
    "exclude_product_ids",
    "exclude_original",
    "quantity",
    "address_label",
    "purchase_requested",
    "return_requested",
    "support_requested",
    "support_declined",
    "reason_code",
    "product_needs",
}


def identifier(value):
    if not isinstance(value, str) or re.search(
        r"(?i)sk-|eyJ|password|token|secret|api.?key", value
    ):
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) else None


def uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        return None


def public_summary(kind, event):
    """Allow types/known enums and resource IDs; discard all free-form prose."""
    result = {}
    nested = event.get("payload")
    data = {**event, **nested} if isinstance(nested, dict) else event
    for key in ("role", "target"):
        if data.get(key) in ROLES:
            result[key] = data[key]
    if data.get("goal") in GOALS:
        result["goal"] = data["goal"]
    if data.get("name") in TOOLS:
        result["name"] = data["name"]
        if data["name"] == "retrieve_bundle_candidates":
            from agentmall.catalog.categories import CATEGORY_LABELS

            category = data.get("validated_arguments", {}).get("category")
            if isinstance(category, str) and category in CATEGORY_LABELS:
                result["category"] = category
    for key in ("subtask_id", "tool_call_id", "interrupt_id"):
        if value := identifier(data.get(key)):
            result[key] = value
    for key in ("resource_id", "action_id", "proposal_id"):
        if value := uuid(data.get(key)):
            result[key] = value
    for key in ("attempt", "max_output_tokens", "duration_ms", "epoch"):
        value = data.get(key)
        if isinstance(value, (int, float)) and 0 <= value <= 1e9:
            result[key] = value
    if isinstance(data.get("ok"), bool):
        result["ok"] = data["ok"]
    for key in ("status", "error_code"):
        value = data.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z_]{1,64}", value) and identifier(value):
            result[key] = value
    if kind in {
        "bundle_computed",
        "bundle_revision_requested",
        "bundle_constraints_updated",
        "bundle_retrieval_reused",
        "bundle_retrieval_refreshed",
        "bundle_replanned",
        "bundle_revision_rejected",
    }:
        from agentmall.catalog.categories import CATEGORY_LABELS

        if isinstance(data.get("category"), str) and data["category"] in CATEGORY_LABELS:
            result["category"] = data["category"]
        if data.get("reason") == "CURRENT_SKU_INVALID":
            result["reason"] = "CURRENT_SKU_INVALID"
        for key in ("item_count", "total_cents", "budget_cents"):
            if type(data.get(key)) is int and 0 <= data[key] <= 100_000_000:
                result[key] = data[key]
    if kind == "orchestration_rejected" and isinstance(data.get("constraint_fields"), list):
        result["constraint_fields"] = sorted(
            {
                name
                for name in data["constraint_fields"]
                if isinstance(name, str) and name in CONSTRAINT_FIELDS
            }
        )
    if kind in {"model_start", "model_end"}:
        usage = data.get("usage")
        result["usage"] = (
            {k: usage[k] for k in ("input_tokens", "output_tokens", "total_tokens")}
            if isinstance(usage, dict)
            and all(
                type(usage.get(k)) is int and usage[k] >= 0
                for k in ("input_tokens", "output_tokens", "total_tokens")
            )
            else "UNKNOWN"
        )
        # Trusted configuration identity is supplied by the Run projection, not model prose.
    refs = data.get("entity_refs", [])
    result_refs = (
        [
            {"kind": r["kind"], "id": uuid(r.get("id"))}
            for r in refs[:40]
            if isinstance(r, dict)
            and r.get("kind") in {"product", "order", "proposal", "case", "ticket"}
            and uuid(r.get("id"))
        ]
        if isinstance(refs, list)
        else []
    )
    if result_refs:
        result["entity_refs"] = result_refs
    evidence = data.get("evidence_refs", [])
    if isinstance(evidence, list) and evidence:
        result["evidence_refs"] = [v for item in evidence[:20] if (v := uuid(item))]
    if kind == "route_decision":
        plan = data.get("validated_arguments", data)
        if isinstance(plan, dict):
            result["tasks"] = [
                public_summary("handoff", t)
                for t in plan.get("tasks", [])[:4]
                if isinstance(t, dict)
            ]
            if plan.get("terminal") in {"finish", "clarify"}:
                result["terminal"] = plan["terminal"]
    return result


async def export_optional(app, actor, run_id):
    """Best effort only, AFTER the authoritative execution/commit has returned."""
    exporter = getattr(app.state, "trace_exporter", None)
    if exporter is None:
        return
    try:
        from agentmall.agents.run_service import trace_page

        async with asyncio.timeout(1):
            await exporter(await trace_page(app, actor, run_id, 0, 100))
    except Exception:
        # No raw exporter exception (may contain credentials) enters public logs.
        return
