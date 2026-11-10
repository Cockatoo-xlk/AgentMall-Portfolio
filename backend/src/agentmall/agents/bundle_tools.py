"""Scoped factual bundle tools; reuse the existing proposal and atomic checkout service."""

from datetime import timedelta
from uuid import uuid5

from agentmall.actions import service as actions
from agentmall.actions.schemas import ItemRequest
from agentmall.agents.bundle_contracts import clarify
from agentmall.agents.bundle_planner import choose_bundle, matches, verify_bundle
from agentmall.catalog.categories import CATEGORY_LABELS
from agentmall.retrieval.search import retrieve_products


async def retrieve(context, args):
    from agentmall.agents.specialist_tools import authenticate, ref

    r = context.runtime
    if not r.thread_snapshot:
        raise clarify("BUNDLE_THREAD_REQUIRED")
    invalidate_changed_requirements(r)
    spec = r.constraints.bundle
    part = next((p for p in spec.parts if p.category == args.category), None) if spec else None
    if part is None or r.thread_snapshot.get("selected_bundle"):
        raise clarify("BUNDLE_CATEGORY_NOT_REQUESTED")
    async with r.sessions.begin() as session:
        actor = await authenticate(r, session)
        revision = r.thread_snapshot.get("bundle_revision")
        if revision and ("bundle_revision", "started") not in r.facts:
            r.event("bundle_revision_requested", item_count=len(spec.parts))
            r.event("bundle_constraints_updated", budget_cents=spec.budget_cents)
            r.facts[("bundle_revision", "started")] = {
                "source_bundle_id": revision["source_bundle_id"]
            }
        if revision and part.category not in revision["refresh_categories"]:
            from uuid import UUID

            from agentmall.catalog import service as catalog
            from agentmall.infra.errors import DomainError

            snapshot = next((i for i in revision["items"] if i["category"] == part.category), None)
            products = []
            try:
                if snapshot is None:
                    raise clarify("INVALID_BUNDLE")
                current = await catalog.get_product(session, actor, UUID(snapshot["id"]))
                if not matches(part, current) or current.id in r.exclusions:
                    raise clarify("BUNDLE_REUSED_SKU_INVALID")
                products = [current]
            except DomainError as error:
                r.event(
                    "bundle_revision_rejected", category=part.category, reason="CURRENT_SKU_INVALID"
                )
                r.facts[("bundle_invalid", part.category)] = {"reason": error.code}
            r.event("bundle_retrieval_reused", category=part.category, item_count=len(products))
        else:
            query = part.requirements.model_copy(
                update={
                    "exclude_product_ids": sorted(
                        set(part.requirements.exclude_product_ids) | r.exclusions, key=str
                    )
                }
            )
            hits = await retrieve_products(session, actor, query.query, query, r.encoder)
            products = [
                h.product for h in hits if matches(part, h.product) and h.id not in r.exclusions
            ]
            if revision:
                r.event(
                    "bundle_retrieval_refreshed", category=part.category, item_count=len(products)
                )
    # Only committed facts enter the bounded composer and checkpoint.
    r.facts[("bundle_candidates", part.category)] = {
        "requirements_digest": actions.payload_hash(spec.model_dump(mode="json")),
        "items": [p.model_dump(mode="json") for p in products],
    }
    entities = []
    for p in products:
        r.facts[("product", str(p.id))] = p.model_dump(mode="json")
        entity = ref("product", p.id, "replacement")
        r.references[(entity.kind, str(entity.id), entity.relation)] = entity
        context.observed.add((entity.kind, str(entity.id), entity.relation))
        entities.append(entity)
    async with r.bundle_lock:
        ready = all(("bundle_candidates", p.category) in r.facts for p in spec.parts)
        if ready and ("bundle_status", "current") not in r.facts:
            pools = {
                p.category: r.facts[("bundle_candidates", p.category)]["items"] for p in spec.parts
            }
            result = choose_bundle(spec, pools)
            revision = r.thread_snapshot.get("bundle_revision")
            diff = None
            if revision:
                from agentmall.agents.bundle_revision import revision_diff

                rev = {
                    **revision,
                    "invalid_categories": [
                        key for (kind, key) in r.facts if kind == "bundle_invalid"
                    ],
                }
                result["budget_cents"] = spec.budget_cents
                diff = revision_diff(rev, result)
                result["revision"] = diff
                r.event(
                    "bundle_replanned",
                    status=result["status"],
                    total_cents=result.get("total_cents"),
                    budget_cents=spec.budget_cents,
                    item_count=len(result.get("items", [])),
                )
            if result["status"] == "READY":
                async with r.sessions.begin() as session:
                    actor = await authenticate(r, session)
                    now = await actions.database_now(session)
                    details = {
                        "buyer_id": str(actor.user_id),
                        "store_id": str(actor.store_id),
                        "thread_id": str(r.input.thread_id),
                        "context_version": r.thread_snapshot["version"],
                        "requirements": spec.model_dump(mode="json"),
                        "budget_cents": spec.budget_cents,
                        "total_cents": result["total_cents"],
                        "expires_at": (now + timedelta(minutes=15)).isoformat(),
                        "items_hash": actions.payload_hash(result["items"]),
                        "ranking": result["ranking"],
                        **({"revision": diff} if diff else {}),
                    }
                    await verify_bundle(session, actor, result["items"], details)
                ident = str(
                    uuid5(
                        r.input.request_id,
                        "bundle:"
                        + actions.payload_hash([details["requirements"], result["items"]]),
                    )
                )
                r.candidate_lists[ident] = {
                    "kind": "bundle",
                    "items": result["items"],
                    "details": details,
                    "preferences_digest": actions.payload_hash(r.thread_snapshot["preferences"]),
                }
                result = {**result, "bundle_id": ident, "expires_at": details["expires_at"]}
            result["requirements_digest"] = actions.payload_hash(spec.model_dump(mode="json"))
            r.facts[("bundle_status", "current")] = result
            r.event(
                "bundle_computed",
                status=result["status"],
                item_count=len(result.get("items", [])),
                total_cents=result.get("total_cents"),
                budget_cents=spec.budget_cents,
            )
    data = {
        "category": part.category,
        "category_label": CATEGORY_LABELS[part.category],
        "items": [p.model_dump(mode="json") for p in products],
        "composition": r.facts.get(("bundle_status", "current")),
    }
    context.records.append(
        {"name": "retrieve_bundle_candidates", "data": data, "entities": entities, "citations": []}
    )
    return {"ok": True, "data": data, "error_code": None, "retryable": False, "evidence_refs": []}


async def prepare(context, args):
    from agentmall.agents.specialist_tools import authenticate, ref

    r = context.runtime
    selected = r.thread_snapshot.get("selected_bundle")
    if r.checkout_blocker() or not selected or str(args.bundle_id) != selected["bundle_id"]:
        raise clarify("BUNDLE_SELECTION_REQUIRED")
    async with r.sessions.begin() as session:
        actor = await authenticate(r, session)
        items, details, quantities = selected["items"], selected["details"], selected["quantities"]
        total = await verify_bundle(session, actor, items, details, quantities=quantities)
        result, _ = await actions.prepare_checkout(
            session,
            actor,
            r.input.request_id,
            "t08_purchase",
            [ItemRequest(product_id=i["id"], quantity=quantities[i["category"]]) for i in items],
            r.constraints.address_label,
            f"t08:checkout:{r.input.request_id}",
        )
        snapshot = result.canonical_payload
        expected = {
            i["id"]: (
                quantities[i["category"]],
                i["price_cents"],
                i["catalog_version"],
                i["name"],
                actions.payload_hash(i["attributes"]),
            )
            for i in items
        }
        actual = {
            i["product_id"]: (
                i["quantity"],
                i["unit_price_cents"],
                i["catalog_version"],
                i["name_snapshot"],
                actions.payload_hash(i["attributes_snapshot"]),
            )
            for i in snapshot["items"]
        }
        if (
            len(snapshot["items"]) != len(items)
            or actual != expected
            or snapshot["total_cents"] != total
        ):
            raise clarify("PRODUCT_CHANGED_REQUOTE")  # Roll back the whole proposal transaction.
        data = context.proposal_data(result)
    entity = ref("proposal", result.proposal_id, "purchase")
    r.references[(entity.kind, str(entity.id), entity.relation)] = entity
    context.observed.add((entity.kind, str(entity.id), entity.relation))
    r.facts[("proposal", str(result.proposal_id))] = data
    context.records.append(
        {"name": "prepare_bundle_checkout", "data": data, "entities": [entity], "citations": []}
    )
    return {"ok": True, "data": data, "error_code": None, "retryable": False, "evidence_refs": []}


def invalidate_changed_requirements(runtime):
    """Clarification cannot recycle an old pool/composition as completion of new constraints."""
    spec = runtime.constraints.bundle
    if spec is None:
        return
    digest = actions.payload_hash(spec.model_dump(mode="json"))
    if not any(
        kind in {"bundle_candidates", "bundle_status"}
        and value.get("requirements_digest") != digest
        for (kind, _), value in runtime.facts.items()
    ):
        return
    runtime.facts = {
        key: value
        for key, value in runtime.facts.items()
        if key[0] not in {"bundle_candidates", "bundle_status", "product"}
    }
    runtime.references = {
        key: value
        for key, value in runtime.references.items()
        if value.kind != "product" or value.relation != "replacement"
    }
    runtime.candidate_lists = {
        key: value
        for key, value in runtime.candidate_lists.items()
        if value.get("kind") != "bundle"
    }
