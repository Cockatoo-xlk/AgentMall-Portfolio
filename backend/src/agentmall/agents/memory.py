"""Authenticated structured preferences; model text is never a memory mutation source."""

import re
from copy import deepcopy
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from agentmall.actions.service import database_now, payload_hash
from agentmall.agents.context import Constraints, MultiRequest, user_constraints
from agentmall.agents.models import CandidateSet, ContextMutation, ThreadContext
from agentmall.agents.purchase_intent import ORDINAL, purchase_intent
from agentmall.catalog import service as catalog
from agentmall.catalog.categories import categories_in_text
from agentmall.infra.errors import DomainError

FIELDS = {
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
    amounts = {int(Decimal(v) * 100) for v in re.findall(r"(\d+(?:\.\d{1,2})?)\s*元", text)}
    connection_text = re.sub(
        r"(?:不接受|排除|拒绝)(?:双模|三模)(?:[／/、和或]*(?:双模|三模))*", "", text
    )
    connections = {v for v in ("有线", "无线", "双模", "三模") if v in connection_text}
    if len(categories_in_text(text)) > 1:
        raise conflict()
    for choices in (
        ("机械", "薄膜"),
        ("61键", "68键", "75键", "84键", "87键", "98键", "104键", "108键"),
    ):
        if sum(word in text for word in choices) > 1:
            raise conflict()
    clears = set()
    if re.search(r"(?:忘记|清除|取消|删除|不要).{0,6}预算", text):
        clears.add("max_price_cents")
    if re.search(r"(?:不要|取消|清除|删除)(?:有线|无线|双模|三模|连接方式).{0,2}", text):
        clears.add("connection")
        positive = re.sub(
            r"(?:不要|取消|清除|删除)(?:有线|无线|双模|三模|连接方式).{0,2}", "", text
        )
        if any(word in positive for word in ("有线", "无线", "双模", "三模")):
            raise conflict()
        connections = set()
    if re.search(r"(?:不要|取消|清除|删除)静音", text):
        clears.add("noise_preference")
    if len(amounts) > 1 or len(connections) > 1 or (amounts and "max_price_cents" in clears):
        raise conflict()
    raw = user_constraints(
        MultiRequest(
            request_id=payload.request_id,
            thread_id=UUID(int=0),
            message=re.sub(r"(?:送|地址[：:]?)演示(?:宿舍|家庭)", "", text),
        )
    )
    fresh = raw.model_dump(mode="json")
    changes = {k: fresh[k] for k in FIELDS - NEEDS if fresh.get(k) is not None}
    changes.update({k: v for k, v in fresh["product_needs"].items() if v is not None and v != []})
    if amounts:
        changes["max_price_cents"] = next(iter(amounts))
    for field in clears:
        changes.pop(field, None)
    typed = payload.constraints.model_dump(exclude_unset=True) if payload.constraints else {}
    specified = {k: v for k, v in typed.items() if k in FIELDS - NEEDS and v is not None}
    specified.update({k: v for k, v in typed.get("product_needs", {}).items() if v is not None})
    for field, value in specified.items():
        if field in clears or (field in changes and changes[field] != value):
            raise conflict()
        changes[field] = value
    prefs = deepcopy(previous)
    if changes.get("category") and changes["category"] != prefs.get("category"):
        # A new category invalidates old category-specific requirements, not budgets.
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
    effective["product_needs"] = prefs.get("product_needs", {})
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
    if not run.context_snapshot:
        return
    context = await locked_context(session, run.thread_id)
    offered = []
    binding = runtime.thread_snapshot
    for ident, candidate in runtime.candidate_lists.items():
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
        offered.append(ident)
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
            # Validate every value through the existing strict domain constraints.
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
    prefs, constraints = resolve_preferences(
        context.preferences, RunCreate(request_id=run.request_id, message=message)
    )
    bindings = [
        e["payload"]["context_binding"]
        for e in run.resume_journal.values()
        if e["payload"].get("context_binding")
    ]
    prior = max(bindings, key=lambda b: b["version"]) if bindings else run.context_snapshot
    active = prior["constraints"]
    # This is the SAME unfinished Run, not a new shopping turn. Missing details
    # supplement its current intent; an explicit negation revokes it immediately.
    for field in ("quantity", "address_label", "reason_code"):
        if constraints[field] is None:
            constraints[field] = active[field]
    revoked_purchase = False
    for field, pattern in (
        ("purchase_requested", r"(?:准备)?(?:购买|下单|买)"),
        ("return_requested", r"(?:申请|准备)?退(?:货|掉)"),
        ("support_requested", r"(?:转|联系|找)人工"),
    ):
        revoked = (
            intent.requested is False
            if field == "purchase_requested"
            else re.search(r"(?:不要|不想|不需要|别|暂不|不)\s*" + pattern, message)
        )
        if not constraints[field] and not revoked:
            constraints[field] = active[field]
        if field == "purchase_requested" and revoked:
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
