"""Minimal observations of server-verified proposals; not an authorization decision."""

from uuid import UUID

STATUSES = {"PENDING", "APPROVED", "EXECUTED", "REJECTED", "EXPIRED"}
ACTIONS = {"CHECKOUT", "RETURN_REQUEST"}


def action_outcomes(facts):
    """The caller must supply runtime.facts, never model-produced claims or summaries."""
    outcomes = []
    for (kind, identifier), value in facts.items():
        if kind != "proposal" or not isinstance(value, dict):
            continue
        try:
            proposal_id = str(UUID(str(identifier)))
            if str(UUID(str(value.get("proposal_id")))) != proposal_id:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        action, status = value.get("action_type"), value.get("status")
        if action not in ACTIONS or status not in STATUSES:
            continue
        outcomes.append({"proposal_id": proposal_id, "action_type": action, "status": status})
    return sorted(outcomes, key=lambda outcome: outcome["proposal_id"])


def _checkout_only_clauses(message, constraints, items):
    """Prove a small checkout-only scope; any unexplained text keeps continuation.

    Consume validated product needs and existing quantity/price/address vocabulary,
    never discard unknown clauses based on a blacklist of other task keywords.
    This is a completion proof, not a price parser or an authorization grant.
    """
    import re
    import unicodedata

    from agentmall.agents.purchase_intent import ACTION
    from agentmall.agents.request_intents import CLAUSES, COUNT
    from agentmall.catalog.categories import CATEGORY_ALIASES

    def normalize(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).lower()

    # Free-text catalog labels are data, never a vocabulary of removable goals.
    # Only bounded ASCII model identifiers are read from them, and only inside
    # a purchase clause. Descriptors come from validated structured constraints.
    models = {
        normalize(word)
        for item in items
        for word in item["name_snapshot"].split()
        if re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9-]{2,40}", word)
    }
    names = set(CATEGORY_ALIASES.get(constraints.category, ()))
    names.update(normalize(word) for word in constraints.product_needs.terms().split())
    if constraints.noise_preference == "quiet":
        names.update({"静音", "安静", "比较安静"})
    address = {"demo_dorm": "演示宿舍", "demo_home": "演示家庭"}.get(constraints.address_label)
    if address is None:
        return False
    purchase_seen = False
    for clause in CLAUSES.split(message):
        text = normalize(clause).strip("！？!?")
        if not text:
            continue
        if re.fullmatch(
            r"(?:我|本人)(?:先|再|会)?(?:核对|审查|确认|检查)"
            r"(?:(?:商品|数量|金额|总价|价格|库存|提案|内容)|[、和及与])+后再?(?:决定|确认|批准)",
            text,
        ) or re.fullmatch(r"(?:让|等|待)?我(?:独立)?确认后再?(?:下单|购买)", text):
            continue  # Owner's review of this checkout, not a separate Agent query.
        if re.fullmatch(r"(?:暂时|暂|先)?(?:不需要|不要|无需|不)(?:付款|支付)", text):
            continue
        if re.fullmatch(
            r"(?:请|帮我|给我|先|准备|生成|创建|一份|的)*(?:购买|采购|下单)提案",
            text,
        ):
            continue  # A proposal for this checkout is not another purchase.
        address_pattern = r"(?:送到?|寄到?|配送到|地址(?:是|为)?[:：]?)" + address
        if not ACTION.search(text):
            # Only whole address/budget qualifiers are known checkout scope.
            # An independent operation must never lose category/attribute words.
            if re.fullmatch(address_pattern, text) or re.fullmatch(
                r"(?:总预算|预算|总价)(?:最多|不超过|不高于)?\d+(?:\.\d+)?元(?:以内|以下)?",
                text,
            ):
                continue
            return False
        # One receipt proves one checkout, never a second requested purchase.
        # Keep additional or ambiguous actions on the existing guarded path.
        if purchase_seen or len(list(ACTION.finditer(text))) != 1:
            return False
        purchase_seen = True
        text = re.sub(address_pattern, "", text)
        vocabulary = names | models
        for name in sorted(vocabulary, key=len, reverse=True):
            text = text.replace(name, "")
        text = COUNT.sub("", text)
        text = re.sub(
            r"(?:总预算|预算|总价|单价|每件|单件)?(?:最多|不超过|不高于)?"
            r"\d+(?:\.\d+)?元(?:以内|以下)?",
            "",
            text,
        )
        text = ACTION.sub("", text)
        if not re.fullmatch(r"(?:请|帮我|给我|先|再|准备|生成|创建|一份|提案|的)*", text):
            return False
    return purchase_seen


def completed_single_checkout(runtime, user_goal, handled):
    """Return only this Run's handled, persisted successful checkout identity."""
    c = runtime.constraints
    if (
        not c.purchase_requested
        or c.return_requested
        or c.support_requested
        or c.recommendation is not None
        or c.bundle is not None
        or runtime.errors
        or getattr(runtime, "pending", {})
        or any(r.status in {"error", "blocked", "needs_input"} for r in runtime.completed.values())
    ):
        return None
    outcomes = action_outcomes(runtime.facts)
    if len(outcomes) != 1:
        return None
    outcome = outcomes[0]
    if (outcome["action_type"], outcome["status"]) != ("CHECKOUT", "EXECUTED"):
        return None
    pid = outcome["proposal_id"]
    if pid not in handled:
        return None
    value = runtime.facts[("proposal", pid)]
    result = value.get("result")
    if (
        not isinstance(result, dict)
        or result.get("action_id") != pid
        or result.get("status") != "PENDING_PAYMENT"
    ):
        return None
    try:
        UUID(result["resource_id"])
        items = value["snapshot"]["items"]
        if not items or any(
            not isinstance(i["name_snapshot"], str) or not i["name_snapshot"] for i in items
        ):
            return None
        if not all(
            _checkout_only_clauses(text, c, items) for text in {user_goal, runtime.input.message}
        ):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return pid
