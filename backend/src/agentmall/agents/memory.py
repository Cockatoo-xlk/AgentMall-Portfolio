"""Authenticated structured preferences; model text is never a memory mutation source."""

import re
from copy import deepcopy
from uuid import UUID, uuid5

from sqlalchemy import select

from agentmall.actions.service import database_now, payload_hash
from agentmall.agents.context import (
    Constraints,
    MultiRequest,
    user_constraints,
    validate_unit_prices,
)
from agentmall.agents.models import CandidateSet, ContextMutation, ThreadContext
from agentmall.agents.product_preferences import (
    comparison_revoked,
    connection_choice,
    product_requirement_text,
    recommendation_revoked,
)
from agentmall.agents.purchase_intent import (
    ORDINAL,
    current_checkout_text,
    purchase_intent,
    purchase_subjects,
)
from agentmall.agents.request_intents import SHIPPING_ADDRESS
from agentmall.catalog import service as catalog
from agentmall.catalog.categories import categories_in_text
from agentmall.infra.errors import DomainError

FIELDS = {
    "unit_price_cents",
    "max_unit_price_cents",
    "category",
    "max_price_cents",
    "noise_preference",
    "layout",
    "connection",
    "excluded_connections",
    "keyboard_type",
    "usage",
    "screen_inches",
    "activity",
    "product_kind",
}
NEEDS = {
    "unit_price_cents",
    "max_unit_price_cents",
    "layout",
    "connection",
    "excluded_connections",
    "keyboard_type",
    "usage",
    "screen_inches",
    "activity",
    "product_kind",
}


def conflict(code="CONTEXT_CLARIFICATION_REQUIRED"):
    return DomainError(409, code, "上下文或候选已变化，请核对当前偏好和名单后明确选择")


def normalize_preferences(prefs):
    if "product_needs" in prefs:
        prefs["product_needs"] = {k: v for k, v in prefs["product_needs"].items() if v != []}
        if not prefs["product_needs"]:
            prefs.pop("product_needs")
    return prefs


def resolve_preferences(previous, payload):
    """Only current authenticated user input can replace a persisted preference."""
    text = payload.message
    product_text = product_requirement_text(text)
    choice = connection_choice(product_text)
    purchase_text = (
        purchase_subjects(product_text)[1] if purchase_intent(text).requested is True else ""
    )
    if len(categories_in_text(purchase_text or product_text)) > 1:
        raise conflict()
    for choices in (
        ("机械", "薄膜"),
        ("61键", "68键", "75键", "84键", "87键", "98键", "104键", "108键"),
    ):
        if sum(word in product_text for word in choices) > 1:
            raise conflict()
    clears = set()
    if choice.broadened:
        clears.add("connection")
    if re.search(r"(?:忘记|清除|取消|删除|不要).{0,6}预算", text):
        clears.add("max_price_cents")
    if re.search(r"(?:忘记|清除|取消|删除|不要).{0,6}单价(?:要求|限制)", text):
        clears.update({"unit_price_cents", "max_unit_price_cents"})
    if not choice.explicit and re.search(
        r"(?:不要|取消|清除|删除)(?:有线|无线|双模|三模|连接方式).{0,2}", product_text
    ):
        clears.add("connection")
        positive = re.sub(
            r"(?:不要|取消|清除|删除)(?:有线|无线|双模|三模|连接方式).{0,2}", "", product_text
        )
        if any(word in positive for word in ("有线", "无线", "双模", "三模")):
            raise conflict()
    if re.search(r"(?:不要|取消|清除|删除)静音", product_text):
        clears.add("noise_preference")
    raw = user_constraints(
        MultiRequest(
            request_id=payload.request_id,
            thread_id=UUID(int=0),
            message=SHIPPING_ADDRESS.sub("", current_checkout_text(text)),
            constraints=(
                Constraints(purchase_requested=payload.constraints.purchase_requested)
                if payload.constraints
                and "purchase_requested" in payload.constraints.model_fields_set
                else None
            ),
        )
    )
    if raw.max_price_cents is not None and "max_price_cents" in clears:
        raise conflict()
    if any(
        field in clears and getattr(raw.product_needs, field) is not None
        for field in ("unit_price_cents", "max_unit_price_cents")
    ):
        raise conflict()
    fresh = raw.model_dump(mode="json")
    changes = {k: fresh[k] for k in FIELDS - NEEDS if fresh.get(k) is not None}
    changes.update(
        {
            k: v
            for k, v in fresh["product_needs"].items()
            if k in NEEDS and v is not None and v != []
        }
    )
    for field in clears:
        changes.pop(field, None)
    typed = payload.constraints.model_dump(exclude_unset=True) if payload.constraints else {}
    specified = {k: v for k, v in typed.items() if k in FIELDS - NEEDS and v is not None}
    specified.update(
        {k: v for k, v in typed.get("product_needs", {}).items() if k in NEEDS and v is not None}
    )
    for field, value in specified.items():
        if field in clears or (field in changes and changes[field] != value):
            raise conflict()
        changes[field] = value
    prefs = deepcopy(previous)
    if changes.get("category") and changes["category"] != prefs.get("category"):
        # A new category invalidates old category-specific requirements, not budgets.
        if prefs.get("category") is None:
            # Merely identifying the product category cannot erase an unscoped price requirement.
            prefs["product_needs"] = {
                k: v
                for k, v in prefs.get("product_needs", {}).items()
                if k in {"unit_price_cents", "max_unit_price_cents"}
            }
        else:
            prefs.pop("product_needs", None)
        prefs.pop("noise_preference", None)
    for field in clears:
        if field in NEEDS:
            prefs.get("product_needs", {}).pop(field, None)
        else:
            prefs.pop(field, None)
    for field, value in changes.items():
        if field in NEEDS:
            prefs.setdefault("product_needs", {})[field] = value
        else:
            prefs[field] = value
    normalize_preferences(prefs)
    validate_unit_prices(prefs.get("product_needs", {}))
    # Non-preference capabilities are derived afresh for this Run, never from old memory.
    effective = user_constraints(
        MultiRequest(
            request_id=payload.request_id,
            thread_id=UUID(int=0),
            message=text,
            constraints=payload.constraints,
        )
    ).model_dump(mode="json")
    for field in FIELDS - NEEDS:
        effective[field] = prefs.get(field)
    # A model chosen for this purchase never becomes a preference for the next Run.
    model_code = effective["product_needs"].get("model_code")
    effective["product_needs"] = dict(prefs.get("product_needs", {}))
    if model_code:
        effective["product_needs"]["model_code"] = model_code
    return prefs, Constraints.model_validate(effective).model_dump(mode="json")


async def locked_context(session, thread_id):
    context = await session.scalar(
        select(ThreadContext).where(ThreadContext.thread_id == thread_id).with_for_update()
    )
    if context is None:
        context = ThreadContext(
            thread_id=thread_id, version=0, preferences={}, offered_ids=[], focus={}, provenance={}
        )
        session.add(context)
        await session.flush()
    return context


async def verify_items(session, actor, items):
    for item in items:
        try:
            product = await catalog.get_product(session, actor, UUID(item["id"]))
        except DomainError as error:
            raise conflict("STALE_CANDIDATES") from error
        if (
            product.catalog_version != item["catalog_version"]
            or product.price_cents != item["price_cents"]
            or product.available < 1
        ):
            raise conflict("STALE_CANDIDATES")


async def accept_context(session, actor, thread_id, run_id, payload):
    existing = await session.get(ThreadContext, thread_id)
    if payload.expected_context_version is None:
        if (
            existing is not None
            or payload.candidate_set_id is not None
            or payload.bundle_revision is not None
            or re.search(
                r"第(?:[一二三四五六七八九十]|\d+)(?:款|个)|刚才那款|上一款", payload.message
            )
        ):
            raise conflict("CONTEXT_VERSION_REQUIRED")
        return {}  # Compatibility for old, stateless API consumers only.
    context = await locked_context(session, thread_id)
    if context.version != payload.expected_context_version:
        raise conflict("STALE_CONTEXT")
    from agentmall.agents.bundle_memory import accept_bundle_context

    bundle_binding = await accept_bundle_context(session, actor, context, payload, run_id)
    if bundle_binding is not None:
        return bundle_binding
    preferences, constraints = resolve_preferences(context.preferences, payload)
    changed = preferences != context.preferences
    selected = []
    source = None
    intent = purchase_intent(payload.message)
    ordinal = re.findall(ORDINAL, intent.reference_text)
    previous = "刚才那款" in payload.message or "上一款" in payload.message
    if ordinal or previous:
        if (
            changed
            or not payload.candidate_set_id
            or str(payload.candidate_set_id) not in context.offered_ids
        ):
            raise conflict("STALE_CANDIDATES")
        source = await session.get(CandidateSet, payload.candidate_set_id)
        if (
            not source
            or source.thread_id != thread_id
            or source.preferences_digest != payload_hash(preferences)
        ):
            raise conflict("STALE_CANDIDATES")
        await verify_items(session, actor, source.items)
        indices = [int(v) if v.isdigit() else "一二三四五六七八九十".index(v) + 1 for v in ordinal]
        if previous:
            focus = context.focus
            if (
                focus.get("source_set_id") != str(source.id)
                or len(focus.get("product_ids", [])) != 1
            ):
                raise conflict()
            indices += [next(i["rank"] for i in source.items if i["id"] == focus["product_ids"][0])]
        if not indices or any(i < 1 or i > len(source.items) for i in indices):
            raise conflict()
        selected = [source.items[i - 1] for i in dict.fromkeys(indices)]
        if constraints["purchase_requested"] and len(selected) != 1:
            raise conflict()
    elif payload.candidate_set_id is not None:
        # A navigation reference alone grants neither selection nor purchase intent.
        if str(payload.candidate_set_id) not in context.offered_ids:
            raise conflict("STALE_CANDIDATES")
    context.preferences = preferences
    if changed:
        context.offered_ids = []
        context.focus = {}
    if selected:
        context.focus = {
            "source_set_id": str(source.id),
            "product_ids": [i["id"] for i in selected],
        }
    context.version += 1
    context.updated_at = await database_now(session)
    context.provenance = {
        "type": "RUN",
        "run_id": str(run_id),
        "request_id": str(payload.request_id),
    }
    return {
        "version": context.version,
        "preferences": preferences,
        "constraints": constraints,
        "selected": selected,
        "candidate_set_id": str(source.id) if source else None,
        "source_run_id": str(source.run_id) if source else None,
    }


async def publish_candidates(session, run, runtime):
    from agentmall.agents.product_preferences import (
        omit_unsolicited_candidates,
        recommendation_products,
    )

    if not run.context_snapshot or omit_unsolicited_candidates(runtime):
        return
    context = await locked_context(session, run.thread_id)

    selected = recommendation_products(runtime)
    offered = []
    binding = runtime.thread_snapshot
    candidates = runtime.candidate_lists
    if selected:
        # Publish the actual visible list, including verified get_product reads,
        # rather than fragments of each exploratory retrieval batch.
        items = [
            dict(
                rank=i + 1,
                **p.model_dump(
                    mode="json",
                    include={"id", "name", "price_cents", "currency", "catalog_version"},
                ),
            )
            for i, p in enumerate(selected)
        ]
        ident = str(
            uuid5(run.id, "recommendation:" + payload_hash([binding["preferences"], items]))
        )
        candidates = {
            ident: {"items": items, "preferences_digest": payload_hash(binding["preferences"])}
        }
    elif selected is not None:
        candidates = {}
    for ident, candidate in candidates.items():
        if candidate["preferences_digest"] != payload_hash(binding["preferences"]):
            continue
        items = candidate["items"]
        candidate_id = UUID(ident)
        record = await session.get(CandidateSet, candidate_id)
        if record is None:
            session.add(
                CandidateSet(
                    id=candidate_id,
                    thread_id=run.thread_id,
                    run_id=run.id,
                    preferences_digest=candidate["preferences_digest"],
                    items=items,
                    kind=candidate.get("kind", "product"),
                    details=candidate.get("details", {}),
                )
            )
        offered.append(str(candidate_id))
    bundle_status = runtime.facts.get(("bundle_status", "current"))
    if bundle_status and context.version == binding["version"]:
        context.provenance = {**context.provenance, "bundle_status": bundle_status}
    # Recovery/repeated Resume cannot republish an old list over a newer accepted context.
    if offered and context.version == binding["version"]:
        context.offered_ids = offered
        context.focus = {}
        context.version += 1
        context.updated_at = await database_now(session)
        context.provenance = {
            "type": "CANDIDATES",
            "run_id": str(run.id),
            **({"bundle_status": bundle_status} if bundle_status else {}),
        }


async def context_view(session, actor, thread_id):
    context = await session.get(ThreadContext, thread_id)
    if context is None:
        return {
            "version": 0,
            "preferences": {},
            "candidate_sets": [],
            "provenance": {},
            "updated_at": None,
        }
    sets = []
    bundles = []
    for ident in context.offered_ids:
        record = await session.get(CandidateSet, UUID(ident))
        if record is None or record.thread_id != thread_id:
            continue
        if record.kind == "bundle":
            from agentmall.agents.bundle_memory import bundle_view

            bundles.append(await bundle_view(session, actor, record))
            continue
        valid = True
        try:
            await verify_items(session, actor, record.items)
        except DomainError:
            valid = False
        sets.append(
            {
                "id": str(record.id),
                "run_id": str(record.run_id),
                "items": record.items,
                "valid": valid,
                "created_at": record.created_at,
            }
        )
    history = []
    if context.preferences.get("bundle"):
        from agentmall.agents.bundle_memory import bundle_view

        records = (
            await session.scalars(
                select(CandidateSet)
                .where(CandidateSet.thread_id == thread_id, CandidateSet.kind == "bundle")
                .order_by(CandidateSet.created_at.desc(), CandidateSet.id.desc())
                .limit(21)
            )
        ).all()
        for record in records:
            if str(record.id) not in context.offered_ids:
                history.append(await bundle_view(session, actor, record, historical=True))
        history = history[:20]
    return {
        **(
            {
                "bundles": bundles,
                "bundle_history": history,
                "bundle_status": context.provenance.get("bundle_status"),
            }
            if context.preferences.get("bundle")
            else {}
        ),
        "version": context.version,
        "preferences": context.preferences,
        "candidate_sets": sets,
        "provenance": context.provenance,
        "updated_at": context.updated_at,
    }


async def patch_context(app, actor, thread_id, payload):
    from agentmall.agents.locking import thread_lock
    from agentmall.agents.run_service import owned_thread, thread_busy

    digest = payload_hash(payload.model_dump(mode="json"))
    async with app.state.sessions.begin() as session:
        await owned_thread(session, actor, thread_id)
    async with thread_lock(app.state.settings, thread_id):
        async with app.state.sessions.begin() as session:
            await owned_thread(session, actor, thread_id)
            prior = await session.scalar(
                select(ContextMutation).where(
                    ContextMutation.thread_id == thread_id,
                    ContextMutation.request_id == payload.request_id,
                )
            )
            if prior:
                if prior.digest != digest:
                    raise conflict("IDEMPOTENCY_CONFLICT")
                return prior.receipt
            await thread_busy(session, thread_id)
            context = await locked_context(session, thread_id)
            if context.version != payload.expected_version:
                raise conflict("STALE_CONTEXT")
            prefs = deepcopy(context.preferences)
            if prefs.get("bundle") and any(o.field != "bundle" for o in payload.operations):
                raise conflict("BUNDLE_CLARIFICATION_REQUIRED")
            for operation in payload.operations:
                field = operation.field
                target = prefs.setdefault("product_needs", {}) if field in NEEDS else prefs
                old = target.get(field)
                if operation.op == "CLEAR":
                    target.pop(field, None)
                else:
                    if operation.op == "SET" and old is not None and old != operation.value:
                        raise conflict()
                    target[field] = operation.value
            normalize_preferences(prefs)
            validate_unit_prices(prefs.get("product_needs", {}))
            validated = Constraints.model_validate(prefs).model_dump(mode="json", exclude_none=True)
            context.preferences = {k: validated[k] for k in prefs}
            context.version += 1
            context.offered_ids, context.focus = [], {}
            context.provenance = {"type": "PATCH", "request_id": str(payload.request_id)}
            context.updated_at = await database_now(session)
            receipt = {"applied_version": context.version, "preferences": context.preferences}
            session.add(
                ContextMutation(
                    thread_id=thread_id,
                    request_id=payload.request_id,
                    digest=digest,
                    receipt=receipt,
                )
            )
            return receipt


async def accept_clarification(session, actor, run, message):
    """A new explicit user input is versioned before graph execution, never parsed as old prose."""
    from agentmall.agents.context import scoped_purchase_quantity
    from agentmall.agents.request_intents import return_intent, support_intent
    from agentmall.agents.run_schemas import RunCreate

    intent = purchase_intent(message)
    if intent.requested is not False and re.search(
        r"第(?:[一二三四五六七八九十]|\d+)(?:款|个)|刚才那款|上一款", message
    ):
        # Clarification has no displayed-list binding; require an explicit entity ID.
        raise conflict()
    context = await locked_context(session, run.thread_id)
    if context.preferences.get("bundle"):
        from agentmall.agents.bundle_memory import accept_bundle_context

        return await accept_bundle_context(
            session, actor, context, RunCreate(request_id=run.request_id, message=message), run.id
        )
    bindings = [
        e["payload"]["context_binding"]
        for e in run.resume_journal.values()
        if e["payload"].get("context_binding")
    ]
    prior = max(bindings, key=lambda b: b["version"]) if bindings else run.context_snapshot
    active = prior["constraints"]
    prefs, constraints = resolve_preferences(
        context.preferences,
        RunCreate(
            request_id=run.request_id,
            message=message,
            # Only this unfinished Run retains its authenticated purchase intent.
            # A unit-price supplement must not replace its existing total budget.
            constraints=(
                Constraints(purchase_requested=True)
                if intent.requested is None and active["purchase_requested"]
                else None
            ),
        ),
    )
    if recommendation_revoked(message):
        constraints.pop("recommendation", None)
    elif active.get("recommendation"):
        requirement = deepcopy(active["recommendation"])
        current = constraints.get("recommendation") or {}
        if current.get("count") is not None:
            requirement["count"] = current["count"]
        requirement["compare_connections"] = not comparison_revoked(message) and (
            requirement.get("compare_connections", False)
            or current.get("compare_connections", False)
        )
        constraints["recommendation"] = requirement
    if intent.requested is None and active["purchase_requested"]:
        quantity = scoped_purchase_quantity(message, supplemental=True)
        if quantity is not None:
            constraints["quantity"] = quantity
    # This is the SAME unfinished Run, not a new shopping turn. Missing details
    # supplement its current intent; an explicit negation revokes it immediately.
    for field in ("quantity", "address_label", "reason_code"):
        if constraints[field] is None:
            constraints[field] = active[field]
    revoked_purchase = False
    decisions = {
        "purchase_requested": intent.requested,
        "return_requested": return_intent(message),
        "support_requested": support_intent(message),
    }
    for field, decision in decisions.items():
        if decision is None:
            constraints[field] = active[field]
        else:
            constraints[field] = decision
        if field == "purchase_requested" and decision is False:
            revoked_purchase = True
            constraints["quantity"] = constraints["address_label"] = None
    constraints["support_declined"] = (
        False
        if constraints["support_requested"]
        else constraints["support_declined"] or active["support_declined"]
    )
    constraints["exclude_original"] |= active["exclude_original"]
    constraints["exclude_product_ids"] = active["exclude_product_ids"]
    selected = [] if revoked_purchase else prior.get("selected", [])
    if selected and prefs != context.preferences:
        raise conflict("STALE_CANDIDATES")
    if selected:
        await verify_items(session, actor, selected)
    constraints = Constraints.model_validate(constraints).model_dump(mode="json")
    context.preferences = prefs
    context.offered_ids, context.focus = [], {}
    context.version += 1
    context.updated_at = await database_now(session)
    context.provenance = {"type": "CLARIFICATION", "run_id": str(run.id)}
    return {
        "version": context.version,
        "preferences": prefs,
        "constraints": constraints,
        "selected": selected,
        "candidate_set_id": prior.get("candidate_set_id") if selected else None,
        "source_run_id": prior.get("source_run_id") if selected else None,
    }
