"""End only fulfilled readonly tasks; never select a tool, SKU or business action."""

from pydantic import ValidationError

from agentmall.agents.return_handoff import assessment_receipt
from agentmall.agents.specialist_tools import product_allowed
from agentmall.catalog.schemas import ProductDTO


def supports_read_completion(runtime, envelope):
    return (
        not runtime.single
        and envelope.read_only
        and (
            envelope.goal == "assess_return"
            or (envelope.goal == "find_products" and not runtime.constraints.bundle)
        )
    )


def read_goal_signature(runtime, envelope):
    from agentmall.agents.runtime import fingerprint

    if not supports_read_completion(runtime, envelope):
        return None
    return "completed_read:" + fingerprint(
        {
            "target": envelope.target,
            "goal": envelope.goal,
            "constraints": runtime.handoff_constraints().model_dump(mode="json"),
        }
    )


def verified_candidates(runtime, envelope):
    """Role-scoped, bounded snapshots. Fresh quote checks remain in the domain tools."""
    permitted = {
        str(e.id)
        for e in envelope.entity_refs
        if e.kind == "product" and e.relation == "replacement"
    }
    metadata = {}
    for (kind, _), fact in runtime.facts.items():
        if kind == "retrieval_candidates":
            for hit in fact["items"]:
                metadata[hit["id"]] = hit
    result = []
    for ident in sorted(permitted):
        fact = runtime.facts.get(("product", ident))
        if fact is None:
            continue
        try:
            product = ProductDTO.model_validate(fact)
        except ValidationError:
            continue
        c = runtime.constraints
        qty = c.quantity or 1
        if (
            not product_allowed(runtime, product)
            or product.available < qty
            or (c.max_price_cents is not None and product.price_cents * qty > c.max_price_cents)
        ):
            continue
        hit = metadata.get(ident, {})
        # Old checkpoints may lack retrieval metadata. UNKNOWN must not become 0.
        matches = hit.get("product") == fact
        result.append(
            {
                "product": product.model_dump(mode="json"),
                "is_current_quote": False,
                "rank": hit.get("rank") if matches else None,
                "score": hit.get("score") if matches else None,
                "source_uri": hit.get("source_uri") if matches else None,
                "source_version": hit.get("source_version") if matches else None,
            }
        )
    return sorted(
        result,
        key=lambda value: (value["rank"] is None, value["rank"] or 0, value["product"]["id"]),
    )[:3]


def completed_read_reason(runtime, context):
    if not supports_read_completion(runtime, context.envelope) or not context.records:
        return None
    if any(row.get("error_code") for row in context.records):
        return None
    if context.envelope.goal == "assess_return":
        return "ASSESSMENT_RECEIPTS" if assessment_receipt(context)["reads_complete"] else None
    # Only a complete, committed nonempty retrieval may end a simple read goal.
    rows = [row for row in context.records if row["name"] == "retrieve_products"]
    if not rows:
        return None
    hits = rows[-1]["data"]["items"]
    if not hits:
        return None
    from types import SimpleNamespace

    envelope = SimpleNamespace(entity_refs=[runtime.references[key] for key in context.observed])
    verified = {v["product"]["id"]: v["product"] for v in verified_candidates(runtime, envelope)}
    return (
        "PRODUCT_RECEIPTS"
        if all(verified.get(hit["id"]) == hit["product"] for hit in hits)
        else None
    )


def finish_read_batch(runtime, context):
    """Use the SDK's existing tools-to-model edge after the WHOLE batch settled.

    Tools are fresh per Handoff. No new graph node/recursion allowance, synthetic
    model response, tool selection or business write is introduced here.
    """
    if not supports_read_completion(runtime, context.envelope):
        return
    reason = completed_read_reason(runtime, context)
    if reason is None:
        return
    for tool in context.bound_tools.values():
        tool.return_direct = True
    context.read_goal_completed = True
    runtime.event(
        "read_goal_completed",
        role=context.envelope.target,
        goal=context.envelope.goal,
        subtask_id=context.envelope.subtask_id,
        completion_basis=reason,
        model_round_skipped=True,
        tool_names=sorted({row["name"] for row in context.records}),
    )
