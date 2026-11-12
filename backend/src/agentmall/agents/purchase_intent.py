"""Current user clauses grant intent, never model output or remembered preferences."""

import re
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
    + r"(?P<prefix>准备|帮我|我要|我想|就|(?<![修更])改)?"
    + MODIFIERS
    + r"(?:购买|下单|买)\s*"
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
    positive, negative = set(), set()
    buying = denying = global_denial = False
    reference = list(message)
    previous_end = 0
    for match in ACTION.finditer(message):
        prefix = re.split(r"[，。；,;\n]", message[previous_end : match.start()])[-1]
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
        if match["negative"]:
            denying = True
            global_denial |= target is None
            if target:
                negative.add(target)
            reference[match.start() : match.end()] = " " * (match.end() - match.start())
        elif match["prefix"] or target:
            if re.search(r"不(?!超过|高于|大于|多于)|别|没|取消|撤销|放弃|是否|考虑|犹豫", prefix):
                raise DomainError(
                    409, "CONTEXT_CLARIFICATION_REQUIRED", "购买意图作用域不明确，请单独说明决定"
                )
            buying = True
            if target:
                positive.add(target)
    if buying and (
        global_denial
        or len(positive) > 1
        or positive & negative
        or (negative and not positive)
        or MULTIPLE_IDS.search(message)
        # Mixed UUID revocation has no displayed-list binding: ask rather than expose a choice.
        or any(kind == "product" for kind, _ in negative)
    ):
        raise DomainError(
            409, "CONTEXT_CLARIFICATION_REQUIRED", "购买对象或意图冲突，请明确唯一商品"
        )
    return PurchaseIntent(
        True if buying else False if denying else None,
        "".join(reference),
        next((value for kind, value in positive if kind == "product"), None),
    )
