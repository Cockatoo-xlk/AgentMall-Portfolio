"""Thread-scoped bundle selection, with fresh server-side facts and no inherited grants."""

import re
from copy import deepcopy
from uuid import UUID

from agentmall.actions.service import database_now, payload_hash
from agentmall.agents.bundle_contracts import (
    BundleRequirements,
    budget_in_text,
    clarify,
    each_quantity,
    parse_bundle,
)
from agentmall.agents.bundle_planner import verify_bundle
from agentmall.agents.models import CandidateSet
from agentmall.agents.purchase_intent import purchase_intent


async def accept_bundle_context(session, actor, context, payload, run_id):
    parsed = parse_bundle(payload.message)
    typed = payload.constraints.bundle if payload.constraints else None
    previous = context.preferences.get("bundle")
    if not (parsed or typed or previous):
        if payload.bundle_id is not None or payload.bundle_quantities is not None:
            raise clarify("STALE_BUNDLE")
        return None
    if parsed and typed and parsed != typed:
        raise clarify()
    spec = parsed or typed or BundleRequirements.model_validate(previous)
    maximum = budget_in_text(payload.message)
    if maximum is not None and maximum != spec.budget_cents:
        if parsed or typed:
            raise clarify()
        try:
            spec = BundleRequirements.model_validate(
                {**spec.model_dump(mode="json"), "budget_cents": maximum}
            )
        except ValueError as error:
            raise clarify() from error
    preferences = {"bundle": spec.model_dump(mode="json")}
    changed = preferences != context.preferences
    intent = purchase_intent(payload.message)
    selected = None
    source = None
    # Always derive permissions from this request, never from the stored plan.
    from agentmall.agents.context import MultiRequest, user_constraints

    current = user_constraints(
        MultiRequest(
            request_id=payload.request_id,
            thread_id=context.thread_id,
            message=payload.message,
            constraints=payload.constraints,
        )
    )
    if intent.requested is None and re.search(r"买|购买|下单", payload.message):
        raise clarify("BUNDLE_SELECTION_REQUIRED")
    if not parsed:
        # Address labels are destinations, not product usage constraints.
        audit_text = re.sub(r"(?:送|地址[：:]?)演示(?:宿舍|家庭)", "", payload.message)
        audit = user_constraints(
            MultiRequest(
                request_id=payload.request_id,
                thread_id=context.thread_id,
                message=audit_text,
                constraints=payload.constraints,
            )
        )
        needs = audit.product_needs.model_dump(exclude_none=True)
        if (
            audit.category
            or audit.noise_preference
            or any(v for v in needs.values())
            or (audit.max_price_cents is not None and audit.max_price_cents != spec.budget_cents)
            or re.search(r"改成|换成|清除|忘记|删除|取消预算", payload.message)
        ):
            raise clarify()
        if current.purchase_requested:
            # Limited MVP grammar: never silently discard an unrepresented hard requirement.
            residual = re.sub(
                r"(?:每样|每类|各|每件)\s*(?:[一二两三四五六七八九十]|\d+)\s*(?:件|个|台|把|副|只)",
                "",
                audit_text,
            )
            for word in sorted(
                (
                    "刚才推荐的组合",
                    "刚才那套",
                    "这套",
                    "那套",
                    "这组",
                    "整套方案",
                    "整套",
                    "刚才的组合",
                    "我要",
                    "我想",
                    "帮我",
                    "购买",
                    "下单",
                    "就",
                    "买",
                    "请",
                ),
                key=len,
                reverse=True,
            ):
                residual = residual.replace(word, "")
            if residual.strip(" ：:、，,；;。!！?？"):
                raise clarify()
    if payload.constraints:
        explicit = user_constraints(
            MultiRequest(
                request_id=payload.request_id, thread_id=context.thread_id, message=payload.message
            )
        )
        if payload.constraints.quantity is not None or (
            payload.constraints.address_label is not None
            and explicit.address_label is not None
            and payload.constraints.address_label != explicit.address_label
        ):
            raise clarify()
        typed_needs = payload.constraints.product_needs.model_dump(exclude_none=True)
        if (
            payload.constraints.category
            or payload.constraints.noise_preference
            or any(v for v in typed_needs.values())
            or payload.constraints.max_price_cents is not None
        ):
            raise clarify()
    if current.return_requested or current.support_requested:
        raise clarify()
    if current.purchase_requested:
        if changed:
            raise clarify("STALE_BUNDLE")
        requested = payload.bundle_id
        if requested is None:
            if not any(
                word in intent.reference_text
                for word in ("这套", "那套", "这组", "整套", "刚才的组合")
            ):
                raise clarify("BUNDLE_SELECTION_REQUIRED")
            available = []
            for identifier in context.offered_ids:
                row = await session.get(CandidateSet, UUID(identifier))
                if row is not None and row.kind == "bundle" and row.thread_id == context.thread_id:
                    available.append(row)
            if len(available) != 1:
                raise clarify("BUNDLE_SELECTION_REQUIRED")
            source = available[0]
        else:
            if str(requested) not in context.offered_ids:
                raise clarify("STALE_BUNDLE")
            source = await session.get(CandidateSet, requested)
        if (
            not source
            or source.kind != "bundle"
            or source.thread_id != context.thread_id
            or source.preferences_digest != payload_hash(preferences)
        ):
            raise clarify("STALE_BUNDLE")
        quantity = each_quantity(payload.message)
        supplied = payload.bundle_quantities
        quantities = {}
        if supplied is not None and set(supplied) != {p.category for p in spec.parts}:
            raise clarify("BUNDLE_QUANTITIES_REQUIRED")
        for part in spec.parts:
            amount = (
                supplied.get(part.category)
                if supplied is not None
                else quantity
                if quantity is not None
                else None
            )
            if quantity is not None and supplied is not None and amount != quantity:
                raise clarify("BUNDLE_QUANTITIES_REQUIRED")
            if amount is None:
                raise clarify("BUNDLE_QUANTITIES_REQUIRED")
            quantities[part.category] = amount
        if current.address_label is None:
            raise clarify("BUNDLE_ADDRESS_REQUIRED")
        total = await verify_bundle(
            session, actor, source.items, source.details, quantities=quantities
        )
        selected = {
            "bundle_id": str(source.id),
            "items": deepcopy(source.items),
            "details": deepcopy(source.details),
            "quantities": quantities,
            "total_cents": total,
            "source_run_id": str(source.run_id),
        }
    elif payload.bundle_id is not None or payload.bundle_quantities is not None:
        # Navigation is not a purchase grant; callers must express the action separately.
        raise clarify("BUNDLE_PURCHASE_NOT_REQUESTED")
    context.preferences = preferences
    if changed:
        context.offered_ids = []
        context.focus = {}
    context.version += 1
    context.updated_at = await database_now(session)
    context.provenance = {
        "type": "RUN",
        "run_id": str(run_id),
        "request_id": str(payload.request_id),
    }
    constraints = current.model_copy(
        update={
            "bundle": spec,
            "category": None,
            "max_price_cents": None,
            "noise_preference": None,
            "product_needs": type(current.product_needs)(),
        }
    )
    return {
        "version": context.version,
        "preferences": preferences,
        "constraints": constraints.model_dump(mode="json"),
        "selected": deepcopy(source.items) if source else [],
        "selected_bundle": selected,
        "candidate_set_id": None,
        "source_run_id": str(source.run_id) if source else None,
    }


async def bundle_view(session, actor, record):
    valid = True
    reason = None
    try:
        await verify_bundle(session, actor, record.items, record.details)
    except Exception as error:
        from agentmall.infra.errors import DomainError

        if not isinstance(error, (DomainError, ValueError, KeyError, TypeError)):
            raise
        valid = False
        reason = error.code if isinstance(error, DomainError) else "INVALID_BUNDLE"
    details = record.details
    return {
        "bundle_id": str(record.id),
        "thread_id": str(record.thread_id),
        "source_run_id": str(record.run_id),
        "context_version": details.get("context_version"),
        "name": "多品类合成组合",
        "items": record.items,
        "requirements": details.get("requirements"),
        "budget_cents": details.get("budget_cents"),
        "total_cents": details.get("total_cents"),
        "remaining_cents": details.get("budget_cents", 0) - details.get("total_cents", 0),
        "expires_at": details.get("expires_at"),
        "valid": valid,
        "invalid_reason": reason,
        "ranking": details.get("ranking"),
        "created_at": record.created_at,
    }
