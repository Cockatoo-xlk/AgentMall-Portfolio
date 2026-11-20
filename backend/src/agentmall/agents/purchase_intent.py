"""Current user clauses grant intent, never model output or remembered preferences."""

import re
import unicodedata
from dataclasses import dataclass

from agentmall.infra.errors import DomainError

ORDINAL = r"第([一二三四五六七八九十]|\d+)(?:款|个)"
PRODUCT_ID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
MULTIPLE_IDS = re.compile(
    PRODUCT_ID + r"\s*[，,]?\s*(?:或(?:者)?|还是|和|、|也买|/|／|or|and)\s*" + PRODUCT_ID,
    re.IGNORECASE,
)
MODIFIERS = r"(?:(?:再|要|继续|直接|立即|马上)\s*)*"
# 改买 is a purchase action; the suffix of 修改/更改 is not a standalone 改.
# Keep 买家电 legal: a blanket exclusion of 买家 would hide an actual purchase.
ACTION = re.compile(
    r"(?P<negative>先别|不要|不想|不需要|不打算|不准备|不用|暂不|别|取消|撤销|放弃|不)?\s*"
    + MODIFIERS
    + r"(?P<prefix>请(?:帮我)?|准备|帮我|我要|我想|就|(?<![修更])改)?"
    + MODIFIERS
    + r"(?P<action>采购|购买|下单|买)\s*"
    r"(?:(?:最新|刚才)(?:推荐的|那款)?)?"
    r"(?:(?P<ordinal>第(?:[一二三四五六七八九十]|\d+)(?:款|个))|(?P<product_id>"
    + PRODUCT_ID
    + r"))?"
)


@dataclass(frozen=True)
class PurchaseIntent:
    requested: bool | None
    reference_text: str
    product_id: str | None = None


def purchase_intent(message):
    from agentmall.agents.request_intents import CLAUSES, NEGATIVE, action_decision, action_scope

    positive, negative = set(), set()
    buying = denying = global_denial = False
    reference = list(message)
    previous_end = 0
    for match in ACTION.finditer(message):
        if match["action"] == "买" and re.search(
            r"(?:修改|更改)\s*$", message[: match.start("action")]
        ):
            continue
        prefix = CLAUSES.split(message[previous_end : match.start()])[-1]
        clause = (
            CLAUSES.split(message[: match.start()])[-1] + CLAUSES.split(message[match.start() :])[0]
        )
        previous_end = match.end()
        ordinal = match["ordinal"]
        target = None
        if ordinal:
            value = re.search(ORDINAL, ordinal)[1]
            target = (
                "ordinal",
                int(value) if value.isdigit() else "一二三四五六七八九十".index(value) + 1,
            )
        elif match["product_id"]:
            target = ("product", match["product_id"].lower())
        decision = None
        if match["negative"]:
            decision = False
        elif match["prefix"] or target or match["action"] == "采购" or NEGATIVE.search(prefix):
            actor_scope = CLAUSES.split(message[: match.start("action")])[-1]
            decision = action_decision(
                clause, actor_scope, scope=action_scope(message, match.start())
            )
        if decision is False:
            denying = True
            global_denial |= target is None
            if target:
                negative.add(target)
            reference[match.start() : match.end()] = " " * (match.end() - match.start())
        elif decision is True:
            if re.search(r"不(?!超过|高于|大于|多于)|别|没|取消|撤销|放弃|是否|考虑|犹豫", prefix):
                raise DomainError(
                    409, "CONTEXT_CLARIFICATION_REQUIRED", "购买意图作用域不明确，请单独说明决定"
                )
            buying = True
            if target:
                positive.add(target)
    positive_ordinals = re.findall(ORDINAL, message) if buying else []
    if buying and (
        global_denial
        or len(positive) > 1
        or positive & negative
        or (negative and not positive)
        or MULTIPLE_IDS.search(message)
        # Mixed UUID revocation has no displayed-list binding: ask rather than expose a choice.
        or any(kind == "product" for kind, _ in negative)
        or (len(set(positive_ordinals)) > 1 and re.search(r"和|或|、", message))
    ):
        raise DomainError(
            409, "CONTEXT_CLARIFICATION_REQUIRED", "购买对象或意图冲突，请明确唯一商品"
        )
    return PurchaseIntent(
        True if buying else False if denying else None,
        "".join(reference),
        next((value for kind, value in positive if kind == "product"), None),
    )


def purchase_tokens(constraints, item_name, *, preparing=False, product_id=None):
    from agentmall.agents.request_intents import COUNT
    from agentmall.catalog.categories import KIND_NAMES, category_names

    # Product descriptions are never executable vocabulary. Only a bounded model
    # identifier can enter the grammar from the actual purchased item's name.
    models = {
        word.lower()
        for word in unicodedata.normalize("NFKC", item_name).split()
        if re.fullmatch(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9-]{2,40}", word)
    }
    if product_id:
        models.add(product_id.lower())
    nouns = set(category_names(constraints.category))
    if kind := constraints.product_needs.product_kind:
        name = KIND_NAMES[kind]
        nouns.update({prefix + name for prefix in nouns})
        nouns.add(name)
    descriptors = set(constraints.product_needs.terms().split()) - nouns
    if product_id:
        descriptors.add("商品")
    if constraints.noise_preference == "quiet":
        descriptors.update({"静音", "安静", "比较安静"})

    def alternatives(values):
        return "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True)) or r"(?!)"

    # Generic selectors/fixture descriptors can defer to existing selection and
    # checkout guards. They never serve as proof of a completed receipt.
    prepare_only = (
        rf"(?:{PRODUCT_ID})|(?:商品|产品|合成|演示|另一款|这款|一款|提案)|" if preparing else ""
    )
    return re.compile(
        prepare_only + rf"(?P<noun>{alternatives(nouns)})|(?P<model>{alternatives(models)})|"
        rf"(?:{alternatives(descriptors)})|{COUNT.pattern}|"
        r"(?:总预算|预算|总价|总金额|总额|单价|单件|每[件个只副台把款])?(?:价格|售价)?(?:为|是)?"
        r"(?:(?:最多|至多|最高|不超过|不高于|不大于|不多于|上限)(?:为|是)?)?"
        r"\d+(?:\.\d+)?元(?:以内|以下|内)?|的"
    )


def matches_purchase_object(text, tokens, *, category, selected):
    # Consume only contiguous object/qualifier tokens. A second request never
    # gets to use purchase preambles or catalogue search aliases as filler.
    position = nouns = models = 0
    for match in tokens.finditer(text):
        if match.start() != position:
            return False
        position = match.end()
        nouns += match["noun"] is not None
        models += match["model"] is not None
    return (
        position == len(text)
        and nouns <= 1
        and models <= 1
        and bool(selected or models or (nouns and category))
    )


def purchase_object_text(action, subject):
    # The explicit catalogue ID already binds the object. A replacement label
    # describes its purpose, while additional clauses still require proof.
    if action["product_id"] and re.fullmatch(r"\s*作为(?:替代|替换)品\s*", subject):
        return ""
    return subject


def purchase_subjects(message):
    """Project purchase objects while retaining independent work in the original goal."""
    from agentmall.agents.request_intents import CLAUSES, SHIPPING_ADDRESS

    objects, qualifiers, recommendations = [], [], []
    for clause in CLAUSES.split(unicodedata.normalize("NFKC", message)):
        clause = clause.strip()
        action = ACTION.search(clause)
        if action and purchase_intent(clause).requested is True:
            # A new imperative can share punctuation with this purchase. It is
            # outside the object, and remains in the original Run for continuation.
            subject = re.split(
                r"(?:再|还|另|并)?(?:请|帮我|给我)|另外|接着|随后|(?:再|并)(?=查|比较|联系)",
                clause[action.end() :],
                maxsplit=1,
            )[0]
            subject = SHIPPING_ADDRESS.split(subject, maxsplit=1)[0]
            if subject != "提案":
                objects.append(purchase_object_text(action, subject))
        elif re.match(r"(?:型号|品类|类别|不(?:要|是|选|买)|排除|拒绝|非)", clause):
            qualifiers.append(clause)
        elif not objects and re.search(r"推荐|找一款", clause):
            recommendations.append(clause)
    # Replacement selection can precede an elliptical "准备购买一件".
    from agentmall.catalog.categories import KIND_MENTION, MODEL_MENTION, categories_in_text

    direct = "，".join(objects)
    if not (
        categories_in_text(direct) or KIND_MENTION.search(direct) or MODEL_MENTION.search(direct)
    ):
        qualifiers.extend(recommendations)
    return objects, "，".join([direct, *qualifiers])


def validate_purchase_objects(subjects, constraints):
    from agentmall.catalog.categories import KIND_MENTION, MODEL_CODE

    tokens = purchase_tokens(
        constraints, constraints.product_needs.model_code or "", preparing=True
    )
    for subject in subjects:
        text = re.sub(r"\s+", "", subject).lower().strip("！？!?")
        # A bundle reference has its own verified selection and quantity contract.
        if re.fullmatch(
            r"(?:修改后的|刚才推荐的|刚才的|刚才|已选(?:择)?的?)?(?:这套|那套|这组|整套(?:方案)?)",
            text,
        ):
            continue
        # A separately resolved negative qualifier cannot become the object.
        text = re.sub(
            rf"(?:不是|不要|不选|不买|排除|拒绝|非)(?:{KIND_MENTION.pattern}|{MODEL_CODE})",
            "",
            text,
            flags=re.I,
        )
        if not matches_purchase_object(text, tokens, category=constraints.category, selected=True):
            raise DomainError(
                409, "CONTEXT_CLARIFICATION_REQUIRED", "请明确目录中的购买商品或选择商品编号"
            )
