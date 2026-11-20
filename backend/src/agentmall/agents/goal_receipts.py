"""Minimal observations of server-verified proposals; not an authorization decision."""

import re
import unicodedata
from uuid import UUID

from agentmall.agents.purchase_intent import (
    ACTION,
    matches_purchase_object,
    purchase_intent,
    purchase_object_text,
    purchase_tokens,
)
from agentmall.agents.request_intents import CLAUSES, COUNT, SHIPPING_PREFIX, purchase_quantity
from agentmall.catalog.categories import category_names
from agentmall.catalog.schemas import ProductDTO

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


def _verified_read_clause(text, records, product, order_id, facts):
    """Recognize only supported follow-up reads with a result from this model turn."""
    if not records:
        return False
    request = re.sub(r"^(?:(?:另(?:外)?|并|再|也|请|帮我|给我|顺便))*", "", text)
    read = r"(?:查询|查看|查(?:一?下)?|看(?:一?下)?)"
    owner = r"(?:(?:本人|自己|我)的?)?"
    if re.fullmatch(read + owner + r"(?:全部|所有)?订单(?:列表)?", request):
        return any(
            r["name"] == "list_orders" and r["data"].get("complete") is True for r in records
        )
    if re.fullmatch(read + owner + r"(?:之前|原来|原|旧)的?订单的?(?:售后)?状态", request):
        return any(
            r["name"] == "get_order"
            and any(item["id"] != order_id and item["status"] for item in r["data"]["items"])
            for r in records
        )
    if not re.match(r"(?:比较|对比|对照)", request):
        return False
    nouns = "|".join(re.escape(n) for n in category_names(product.category))
    if not re.fullmatch(
        rf"(?:比较|对比|对照)(?:{nouns}|有线|无线|双模|三模|和|与|及|不同|两种|连接方式|的|差异|区别)+",
        request,
    ):
        return False
    from agentmall.catalog.capabilities import connection_matches

    products = {}
    for record in records:
        if record["name"] == "get_product":
            rows = [record["data"]]
        elif record["name"] == "retrieve_products":
            rows = [hit["product"] for hit in record["data"]["items"]]
        else:
            continue
        products.update(
            (p["id"], p["attributes"]) for p in rows if p["category"] == product.category
        )
    if not products:
        return False
    products.update(
        (pid, data["attributes"])
        for (kind, pid), data in facts.items()
        if kind == "product" and data["category"] == product.category
    )
    return len(products) >= 2 and all(
        any(connection_matches(attrs, mode) for attrs in products.values())
        for mode in ("有线", "无线")
    )


def _checkout_only_clauses(message, runtime, item, product, selected, reads, order_id):
    """Prove one bounded purchase while leaving any unexplained work to continuation."""
    constraints = runtime.constraints
    address = {"demo_dorm": "演示宿舍", "demo_home": "演示家庭"}.get(constraints.address_label)
    if address is None:
        return False
    address_pattern = SHIPPING_PREFIX + address
    tokens = purchase_tokens(constraints, item["name_snapshot"], product_id=item["product_id"])
    purchase_seen = False
    selection = None
    clauses = [(clause, False) for clause in CLAUSES.split(message)]
    if runtime.input.message != message:
        clauses.extend((clause, True) for clause in CLAUSES.split(runtime.input.message))
    for clause, is_answer in clauses:
        text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", clause)).lower().strip("！？!?")
        if not text:
            continue
        if selection is not None:
            # An adjacent quantity-only checkout refers to the product selection.
            # A named checkout or another imperative is a separate clause.
            action = ACTION.match(text)
            if not action or not COUNT.fullmatch(text[action.end() :]):
                return False
        if _verified_read_clause(text, reads, product, order_id, runtime.facts):
            continue
        if not purchase_seen and text.startswith("推荐"):
            subject = text.removeprefix("推荐")
            if not COUNT.search(subject) and matches_purchase_object(
                subject, tokens, category=product.category, selected=False
            ):
                selection = subject
                continue
        if re.fullmatch(
            r"(?:我|本人)(?:先|再|会)?(?:核对|审查|确认|检查)"
            r"(?:(?:商品|数量|金额|总价|价格|库存|提案|内容)|[、和及与])+后再?(?:决定|确认|批准)",
            text,
        ) or re.fullmatch(r"(?:让|等|待)?我(?:独立)?确认后再?(?:下单|购买)", text):
            continue  # The owner reviews this purchase.
        if re.fullmatch(r"(?:暂时|暂|先)?(?:不需要|不要|无需|不)(?:付款|支付)", text):
            continue
        if re.fullmatch(r"(?:请|帮我|给我|先|准备|生成|创建|一份|的)*(?:购买|采购|下单)提案", text):
            continue
        count_text = re.sub(r"^数量(?:是|为|[:：])?", "", text)
        if is_answer and purchase_seen and purchase_intent(message).requested is not True:
            # Answering an unconfirmed purchase topic with quantity only can
            # describe its first purchase. An additional item or action cannot.
            count_text = re.sub(r"^(?:请|准备|我想)?(?:购买|采购|买)", "", count_text)
        if (
            COUNT.fullmatch(count_text)
            and purchase_quantity("请购买" + count_text) == item["quantity"]
        ) or (is_answer and count_text == "一款" and item["quantity"] == 1):
            continue
        if re.fullmatch(address_pattern, text):
            continue
        if re.fullmatch(
            r"(?:总预算|预算|总价|总金额|总额|单价|单件|每[件个只副台把款])(?:价格|售价)?(?:为|是)?"
            r"(?:(?:最多|至多|最高|不超过|不高于|不大于|不多于|上限)(?:为|是)?)?"
            r"\d+(?:\.\d+)?元(?:以内|以下|内)?",
            text,
        ) or re.fullmatch(r"\d+(?:\.\d+)?元(?:以内|以下|内)", text):
            from agentmall.agents.context import price_scopes

            total, unit, maximum = price_scopes(text, purchasing=True)
            if (
                total is not None
                and total < product.price_cents * item["quantity"]
                or unit is not None
                and unit != product.price_cents
                or maximum is not None
                and maximum < product.price_cents
            ):
                return False
            continue
        actions = list(ACTION.finditer(text))
        if purchase_seen or len(actions) != 1:
            return False
        action = actions[0]
        if action["negative"] or not re.fullmatch(
            r"(?:请|帮我|给我|先|再|准备|想|生成|创建|一份|的)*", text[: action.start()]
        ):
            return False
        if action["ordinal"] and not selected:
            return False
        if action["product_id"] and action["product_id"] != item.get("product_id"):
            return False
        subject = re.sub(address_pattern + "$", "", text[action.end() :])
        subject = purchase_object_text(action, subject)
        if selection is not None:
            subject += selection
            selection = None
        if not matches_purchase_object(
            subject, tokens, category=product.category, selected=selected or action["product_id"]
        ):
            return False
        purchase_seen = True
    return purchase_seen


def completed_single_checkout(runtime, user_goal, handled, *, reads=()):
    """Return only this Run's handled, persisted successful checkout identity."""
    c = runtime.constraints
    if (
        not c.purchase_requested
        or c.return_requested
        or c.support_requested
        or (c.recommendation is not None and not reads)
        or c.bundle is not None
        or runtime.errors
        or getattr(runtime, "pending", {})
        or any(r.status in {"error", "blocked"} for r in runtime.completed.values())
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
    questions = [result for result in runtime.completed.values() if result.status == "needs_input"]
    if questions:
        # The durable Single graph assigns one subtask per round. A question is
        # answered only if the following round used the clarification to propose
        # this exact checkout. Leave its original journal entry intact.
        if len(questions) != 1 or user_goal == runtime.input.message or questions[0].error_code:
            return None
        turn = re.fullmatch(r"single_(\d+)", questions[0].subtask_id)
        following = runtime.completed.get(f"single_{int(turn[1]) + 1}") if turn else None
        if not following or pid not in {str(value) for value in following.proposal_ids}:
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
        snapshot = value["snapshot"]
        (item,) = snapshot["items"]
        product_id = str(UUID(item["product_id"]))
        product = ProductDTO.model_validate(runtime.facts[("product", product_id)])
        selected = getattr(runtime, "thread_snapshot", {}).get("selected", [])
        if selected and [p["id"] for p in selected] != [product_id]:
            return None
        if (
            str(product.id) != product_id
            or product.name != item["name_snapshot"]
            or product.attributes != item["attributes_snapshot"]
            or product.catalog_version != item["catalog_version"]
            or product.price_cents != item["unit_price_cents"]
            or type(item["quantity"]) is not int
            or item["quantity"] != c.quantity
            or snapshot["address_label"] != c.address_label
            or snapshot["currency"] != product.currency
            or snapshot["total_cents"] != product.price_cents * item["quantity"]
            or c.max_price_cents is not None
            and snapshot["total_cents"] > c.max_price_cents
            or not c.matches_product(product, exclusions=getattr(runtime, "exclusions", ()))
        ):
            return None
        # A clarification can supply price or address for the original purchase.
        # Count requested purchases across both messages; one receipt covers one.
        if not _checkout_only_clauses(
            user_goal, runtime, item, product, selected, reads, result["resource_id"]
        ):
            return None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return pid
