"""Current-user recommendation semantics; no model decisions or business actions."""

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from agentmall.infra.errors import DomainError

CONNECTIONS = ("有线", "无线", "双模", "三模")
EXCLUDED_MODES = r"(?:不接受|排除|拒绝)(?:双模|三模)(?:[／/、和或]*(?:双模|三模))*"


def clarify():
    return DomainError(409, "CONTEXT_CLARIFICATION_REQUIRED", "请明确连接要求或推荐数量")


def affirmative(text, start):
    before = re.split(r"[，。；！？,;\n]", text[:start])[-1]
    return not re.search(
        r"(?:不要|不需要|不想|不用|无需|不必|取消|别|暂不|不)(?:再|先|帮我|给我|只)*\s*$",
        before,
    )


def recommendation_revoked(text):
    actions = list(re.finditer(r"推荐|比较|对比|对照", text))
    return bool(actions) and all(not affirmative(text, action.start()) for action in actions)


def comparison_revoked(text):
    """Explicitly cancelled comparison, independent of a continuing recommendation."""
    actions = list(re.finditer(r"比较|对比|对照", text))
    return bool(actions) and all(not affirmative(text, action.start()) for action in actions)


@dataclass(frozen=True)
class ConnectionChoice:
    connection: str | None = None
    broadened: bool = False
    compare: bool = False
    explicit: bool = False


def product_requirement_text(message):
    """Separate an explicitly returned item from a separately requested new item.

    This projection only scopes product preferences; action authorization always
    consumes the complete original request. Ambiguous or conflicting target
    descriptions remain in scope and must still be clarified.
    """
    from agentmall.agents.purchase_intent import PRODUCT_ID, purchase_intent
    from agentmall.agents.request_intents import return_intent
    from agentmall.catalog.categories import categories_in_text

    if return_intent(message) is not True:
        return message
    clauses = re.split(r"([，。；！？,;\n])", message)

    def new_item(clause):
        return bool(categories_in_text(clause)) and (
            purchase_intent(clause).requested is True
            or any(
                affirmative(clause, match.start())
                for match in re.finditer(r"推荐|比较|对比|对照", clause)
            )
        )

    if not any(new_item(clause) for clause in clauses):
        return message
    for index, clause in enumerate(clauses):
        categories = categories_in_text(clause)
        if (
            categories
            and not new_item(clause)
            and re.search(
                r"(?<!新)订单\s*(?:" + PRODUCT_ID + r"|\d+)|原订单|旧订单|原商品|原来的|退货|退掉",
                clause,
            )
        ):
            # A conflict within the original description is not permission to ignore it.
            if len(categories) > 1:
                raise clarify()
            connection_choice(clause)
            clauses[index] = ""
    return "".join(clauses)


def connection_choice(message):
    text = re.sub(EXCLUDED_MODES, "", message)
    mentions = {word for word in CONNECTIONS if word in text}
    cleared = set(
        re.findall(
            r"(?:^|[，。；,;\n])\s*(?:不要|取消|清除|删除)(有线|无线|双模|三模|连接方式)"
            r"(?:了|偏好|要求)?\s*(?=$|[，。；,;\n])",
            text,
        )
    )
    if cleared and mentions <= cleared:
        return ConnectionChoice(broadened=True)
    pair = re.search(r"(有线|无线)\s*(和|与|及|或(?:者)?|/|／|、)\s*(有线|无线)", text)
    comparison = any(affirmative(text, m.start()) for m in re.finditer(r"比较|对比|对照", text))
    alternatives = bool(
        pair
        and (
            pair[2] in {"或", "或者", "/", "／"}
            or re.search(r"都(?:可以|可|行|接受)|均可|皆可|任选", text)
        )
    )
    forced = {
        match[1]
        for match in re.finditer(
            r"(?:只(?:要|选|接受|考虑|推荐)|仅(?:限|要|接受)|必须(?:是|要|使用)?|要求)"
            r"\s*(有线|无线|双模|三模)",
            text,
        )
        if not (alternatives and match.start(1) == pair.start())
    }
    rejected = set(re.findall(r"(?:不要|不接受|排除|拒绝)\s*(有线|无线)", text))
    if forced:
        if len(forced) == 1 and mentions - forced <= rejected and not forced & rejected:
            return ConnectionChoice(next(iter(forced)), explicit=True)
        raise clarify()
    if rejected:
        remaining = mentions - rejected
        if len(remaining) == 1 and not comparison and not alternatives:
            return ConnectionChoice(next(iter(remaining)), explicit=True)
        # A negative-only requirement cannot be represented as a positive mode.
        raise clarify()
    if len(mentions) <= 1:
        return ConnectionChoice(next(iter(mentions), None))
    if mentions == {"有线", "无线"} and pair and (comparison or alternatives):
        if rejected:
            raise clarify()
        return ConnectionChoice(broadened=True, compare=comparison)
    raise clarify()


class RecommendationRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int | None = Field(None, strict=True, ge=1, le=100)
    compare_connections: bool = Field(False, strict=True)


def recommendation_requirements(message, choice):
    numbers = dict(zip("一二两三四五六七八九十", (1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10), strict=True))
    matches = re.finditer(
        r"(?:推荐|找|看看|比较|对比|对照)[^，。；！？\n]{0,30}?"
        r"(?<![第\d一二两三四五六七八九十])(\d+|[一二两三四五六七八九十])\s*款",
        message,
    )
    values = [match[1] for match in matches if affirmative(message, match.start())]
    counts = {int(v) if v.isdigit() else numbers[v] for v in values}
    if len(counts) > 1 or any(not 1 <= value <= 100 for value in counts):
        raise clarify()
    if not counts and not choice.compare:
        return None
    return RecommendationRequirements(
        count=next(iter(counts), None), compare_connections=choice.compare
    )


def recommendation_products(runtime, entity_refs=None):
    """Bound final read-only recommendations, retaining exploration in the runtime."""
    c = runtime.constraints
    requirement = getattr(c, "recommendation", None)
    if requirement is None or c.bundle or c.purchase_requested or c.return_requested:
        return None
    from agentmall.agents.specialist_tools import product_allowed
    from agentmall.catalog.capabilities import connection_matches
    from agentmall.catalog.schemas import ProductDTO

    refs = runtime.references.values() if entity_refs is None else entity_refs
    identifiers = {str(e.id) for e in refs if e.kind == "product" and e.relation == "replacement"}
    products = []
    for (kind, ident), fact in runtime.facts.items():
        if kind == "product" and ident in identifiers:
            product = ProductDTO.model_validate(fact)
            if product_allowed(runtime, product):
                products.append(product)
    limit = requirement.count or len(products)
    selected = products[:limit]
    if requirement.compare_connections:
        modes = ("有线", "无线")
        if not all(any(connection_matches(p.attributes, m) for p in selected) for m in modes):
            # Preserve ranked/insertion order when the first N already cover the
            # comparison. Otherwise use the smallest verified covering subset.
            covering = [
                next((p for p in products if connection_matches(p.attributes, m)), None)
                for m in modes
            ]
            covering = list({p.id: p for p in covering if p is not None}.values())
            if len(covering) <= limit:
                chosen = {p.id for p in covering}
                for product in products:
                    if len(chosen) >= limit:
                        break
                    chosen.add(product.id)
                selected = [p for p in products if p.id in chosen]
    return selected


def recommendation_shortage(runtime, entity_refs=None):
    """Assess the final subset, not the union of explored product quotes."""
    from agentmall.catalog.capabilities import connection_matches

    products = recommendation_products(runtime, entity_refs)
    if products is None:
        return None
    requirement = runtime.constraints.recommendation
    count_missing = requirement.count is not None and len(products) < requirement.count
    comparison_missing = requirement.compare_connections and not all(
        any(connection_matches(p.attributes, connection) for p in products)
        for connection in ("有线", "无线")
    )
    if not count_missing and not comparison_missing:
        return None
    return {
        "observed": len(products),
        "requested": requirement.count,
        "count_missing": count_missing,
        "comparison_missing": comparison_missing,
    }
