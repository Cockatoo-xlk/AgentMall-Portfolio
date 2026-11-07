"""Bounded factual composition. Prices are integer cents, never model output."""

from datetime import datetime
from itertools import product as cartesian
from uuid import UUID

from agentmall.actions.service import database_now, payload_hash
from agentmall.agents.bundle_contracts import BundleRequirements, clarify
from agentmall.catalog import service as catalog
from agentmall.catalog.capabilities import connection_matches
from agentmall.catalog.categories import CATEGORY_LABELS, KIND_ATTRIBUTES
from agentmall.catalog.schemas import ProductDTO

POOL_LIMIT = 5


def matches(part, item, quantity=None):
    q = part.requirements
    if item.category != part.category or item.available < (quantity or part.quantity or 1):
        return False
    a = item.attributes
    if q.max_price_cents is not None and item.price_cents > q.max_price_cents:
        return False
    if item.id in q.exclude_product_ids or (q.noise_preference and a.get("noise") != "较安静"):
        return False
    if q.screen_inches and a.get("screen_inches") != q.screen_inches:
        return False
    if q.layout and a.get("size") != q.layout:
        return False
    if q.usage and q.usage not in a.get("usage", ""):
        return False
    if q.activity and a.get("usage") != "公路车骑行":
        return False
    if not connection_matches(a, q.connection, q.excluded_connections):
        return False
    if q.keyboard_type:
        switches = {
            "membrane": {"薄膜"},
            "mechanical": {"静音轴", "线性轴", "段落轴", "青轴", "茶轴", "红轴"},
        }
        if a.get("switch") not in switches[q.keyboard_type]:
            return False
    if q.product_kind:
        category, key, term = KIND_ATTRIBUTES[q.product_kind]
        if item.category != category or term not in a.get(key, ""):
            return False
    return True


def choose_bundle(spec, pools):
    """Exact enumeration only within at most five retrieved facts per category."""
    candidates = []
    missing = []
    for part in spec.parts:
        values = []
        seen = set()
        for value in pools.get(part.category, [])[:POOL_LIMIT]:
            item = ProductDTO.model_validate(value)
            if item.id in seen:
                continue
            seen.add(item.id)
            if matches(part, item):
                values.append(item)
        if not values:
            missing.append(part.category)
        candidates.append(values)
    if missing:
        return {
            "status": "NO_FEASIBLE_BUNDLE",
            "missing_categories": missing,
            "reason": "EMPTY_REQUIRED_CATEGORY",
        }
    best = None
    minimum = None
    examined = 0
    for combination in cartesian(*candidates):
        examined += 1
        total = sum(
            item.price_cents * (part.quantity or 1)
            for part, item in zip(spec.parts, combination, strict=True)
        )
        minimum = total if minimum is None else min(minimum, total)
        if total > spec.budget_cents:
            continue
        penalty = sum(
            part.prefer_quiet and item.attributes.get("noise") != "较安静"
            for part, item in zip(spec.parts, combination, strict=True)
        )
        key = (penalty, total, tuple(str(item.id) for item in combination))
        if best is None or key < best[0]:
            best = (key, combination)
    if best is None:
        return {
            "status": "NO_FEASIBLE_BUNDLE",
            "missing_categories": [],
            "reason": "GLOBAL_BUDGET_INSUFFICIENT",
            "minimum_retrieved_total_cents": minimum,
            "examined": examined,
        }
    items = []
    for rank, (part, item) in enumerate(zip(spec.parts, best[1], strict=True), 1):
        quantity = part.quantity or 1
        reasons = [f"{CATEGORY_LABELS[part.category]}：来自当前店铺的已验证检索结果"]
        for key, label in [
            ("screen_inches", "英寸"),
            ("connection", "连接方式"),
            ("noise", "噪声标签"),
        ]:
            if value := item.attributes.get(key):
                reasons.append(f"{label}：{value}")
        items.append(
            {
                "id": str(item.id),
                "rank": rank,
                "name": item.name,
                "category": item.category,
                "attributes": item.attributes,
                "price_cents": item.price_cents,
                "currency": item.currency,
                "quantity": quantity,
                "quantity_source": "USER" if part.quantity is not None else "ESTIMATE",
                "subtotal_cents": item.price_cents * quantity,
                "catalog_version": item.catalog_version,
                "available_snapshot": item.available,
                "reasons": reasons,
            }
        )
    return {
        "status": "READY",
        "items": items,
        "total_cents": best[0][1],
        "budget_cents": spec.budget_cents,
        "remaining_cents": spec.budget_cents - best[0][1],
        "examined": examined,
        "ranking": (
            "quiet preference penalty, then total cents, "
            "then ordered Product UUIDs; retrieved pool only"
        ),
    }


async def verify_bundle(session, actor, items, details, *, quantities=None):
    """Re-read every fact. A single stale/foreign/insufficient item rejects all."""
    if details.get("buyer_id") != str(actor.user_id) or details.get("store_id") != str(
        actor.store_id
    ):
        raise clarify("BUNDLE_SCOPE_MISMATCH")
    if await database_now(session) >= datetime.fromisoformat(details["expires_at"]):
        raise clarify("STALE_BUNDLE")
    if details.get("items_hash") != payload_hash(items):
        raise clarify("INVALID_BUNDLE")
    spec = BundleRequirements.model_validate(details["requirements"])
    if details.get("budget_cents") != spec.budget_cents or details.get("total_cents") != sum(
        i["price_cents"] * i["quantity"] for i in items
    ):
        raise clarify("INVALID_BUNDLE")
    if len(items) != len(spec.parts) or len({i["id"] for i in items}) != len(items):
        raise clarify("INVALID_BUNDLE")
    if {i["category"] for i in items} != {p.category for p in spec.parts}:
        raise clarify("INVALID_BUNDLE")
    if quantities is not None and set(quantities) != {p.category for p in spec.parts}:
        raise clarify("BUNDLE_QUANTITIES_REQUIRED")
    total = 0
    for part in spec.parts:
        snapshot = next(i for i in items if i["category"] == part.category)
        quantity = (quantities or {}).get(part.category, snapshot["quantity"])
        if type(quantity) is not int or not 1 <= quantity <= 10:
            raise clarify("BUNDLE_QUANTITIES_REQUIRED")
        current = await catalog.get_product(session, actor, UUID(snapshot["id"]))
        if (
            current.price_cents != snapshot["price_cents"]
            or current.catalog_version != snapshot["catalog_version"]
            or current.name != snapshot["name"]
            or current.attributes != snapshot["attributes"]
            or not matches(part, current, quantity)
        ):
            raise clarify("STALE_BUNDLE")
        total += current.price_cents * quantity
    if total > spec.budget_cents:
        raise clarify("BUNDLE_BUDGET_EXCEEDED")
    return total
