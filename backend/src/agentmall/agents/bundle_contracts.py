"""Current-user bundle requirements, not model-authored business state."""

import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from agentmall.catalog.categories import (
    CATEGORY_ALIASES,
    CATEGORY_LABELS,
    Category,
    categories_in_text,
)
from agentmall.infra.errors import DomainError
from agentmall.retrieval.schemas import ProductQuery


class BundlePart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    quantity: int | None = Field(None, strict=True, ge=1, le=10)
    requirements: ProductQuery
    prefer_quiet: bool = Field(False, strict=True)

    @model_validator(mode="after")
    def scoped(self):
        if self.requirements.category != self.category or not self.requirements.in_stock:
            raise ValueError("Each part must use its own category and in-stock filter")
        if self.requirements.mode != "hybrid":
            raise ValueError("Bundle retrieval uses the existing hybrid contract")
        return self

    @model_serializer(mode="wrap")
    def compact(self, handler):
        data = handler(self)
        data["requirements"] = self.requirements.model_dump(
            mode="json", exclude_none=True, exclude_defaults=True
        )
        if self.quantity is None:
            data.pop("quantity", None)
        return data


class BundleRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_cents: int = Field(strict=True, gt=0, le=100_000_000)
    parts: list[BundlePart] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def unique(self):
        if len({p.category for p in self.parts}) != len(self.parts):
            raise ValueError("One distinct SKU category per required part")
        return self


def clarify(code="BUNDLE_CLARIFICATION_REQUIRED"):
    return DomainError(
        409, code, "请明确2–5个不同品类、各自规格、总预算；购买还需明确方案、数量和演示地址"
    )


def budget_in_text(message):
    values = {
        int(Decimal(v) * 100)
        for v in re.findall(
            r"(?:总预算|预算|总额|总价)\s*(?:不超过|上限为|为|是|改为|提高到|降低到)?\s*(\d+(?:\.\d{1,2})?)\s*元",
            message,
        )
    }
    if len(values) > 1 or (not values and re.search(r"预算|总额|总价", message)):
        raise clarify()
    return next(iter(values)) if values else None


NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def quantity_word(value):
    number = int(value) if value.isdigit() else NUMBERS.get(value)
    if number is None or not 1 <= number <= 10:
        raise clarify()
    return number


def each_quantity(message):
    values = {
        quantity_word(v)
        for v in re.findall(
            r"(?:每样|每类|各|每件)\s*([一二两三四五六七八九十]|\d+)\s*(?:件|个|台|把|副|只)",
            message,
        )
    }
    if len(values) > 1:
        raise clarify()
    return next(iter(values)) if values else None


def parse_bundle(message):
    if not re.search(r"搭配|组合|一套|一组|包括|包含", message):
        return None
    # Referring to a displayed bundle is not a request to replace its requirements.
    if not categories_in_text(message) and re.search(r"这套|那套|这组|那个", message):
        return None
    if len(categories_in_text(message)) < 2 and not re.search(r"包括|包含|组合", message):
        return None
    budget = budget_in_text(message)
    if budget is None:
        raise clarify()
    sections = re.split(r"包括|包含", message, maxsplit=1)
    if len(sections) == 2:
        prefix = re.sub(
            r"(?:总预算|预算|总额|总价)\s*(?:不超过|上限为|为|是|改为|提高到|降低到)?"
            r"\s*\d+(?:\.\d{1,2})?\s*元",
            "",
            sections[0],
        )
        for word in ("帮我", "搭配", "组合", "一套", "一组", "居家办公设备", "设备"):
            prefix = prefix.replace(word, "")
        if prefix.strip(" ：:、，,；;。"):
            raise clarify()
    body = sections[-1]
    segments = re.split(r"[、，,；;。\n]|和|与|及", body)
    parts = []
    each = each_quantity(message)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        categories = categories_in_text(segment)
        if not categories:
            if re.fullmatch(
                r"(?:(?:总预算|预算|总额|总价)\s*\d+(?:\.\d{1,2})?\s*元|"
                r"先推荐|先看看|不要购买|不要下单|不购买|不下单|暂不购买|"
                r"(?:每样|每类|各|每件)\s*(?:[一二两三四五六七八九十]|\d+)\s*(?:件|个|台|把|副|只)|"
                r"送演示宿舍|送演示家庭|搭配一套|组合一套)+",
                segment,
            ):
                continue
            raise clarify()
        if len(categories) != 1:
            raise clarify()
        category = next(iter(categories))
        quantities = {
            quantity_word(v)
            for v in re.findall(r"([一二两三四五六七八九十]|\d+)\s*(?:件|个|台|把|副|只)", segment)
        }
        if len(quantities) > 1 or (quantities and each and next(iter(quantities)) != each):
            raise clarify()
        quantity = next(iter(quantities)) if quantities else each
        connections = [w for w in ("有线", "无线", "双模", "三模") if w in segment]
        if len(connections) > 1:
            raise clarify()
        prefer = "优先" in segment and any(w in segment for w in ("静音", "安静"))
        quiet = any(w in segment for w in ("静音", "安静", "低噪声")) and not prefer
        maxima = {
            int(Decimal(v) * 100)
            for v in re.findall(r"(\d+(?:\.\d{1,2})?)\s*元(?:以内|以下)", segment)
        }
        screens = set(re.findall(r"(\d+(?:\.\d+)?)\s*(?:英寸|寸)", segment))
        usages = {u for u in ("办公", "游戏", "宿舍") if u in segment}
        if any(len(v) > 1 for v in (maxima, screens, usages)):
            raise clarify()
        usage = next(iter(usages), None)
        query = ProductQuery(
            query=segment,
            category=category,
            noise_preference="quiet" if quiet else None,
            connection=connections[0] if connections else None,
            screen_inches=next(iter(screens), None),
            max_price_cents=next(iter(maxima), None),
            usage=usage,
        )
        # Unsupported hard specifications must not disappear into a general category.
        residual = segment
        words = [
            *CATEGORY_ALIASES[category],
            CATEGORY_LABELS[category],
            category,
            "帮我搭配",
            "搭配",
            "组合",
            "一套",
            "一组",
            "推荐",
            "适合",
            "用于",
            "用途",
            "使用",
            "的",
            "有线",
            "无线",
            "双模",
            "三模",
            "静音",
            "安静",
            "低噪声",
            "优先",
            "办公",
            "游戏",
            "宿舍",
            "公路车",
            "骑行",
            "头盔",
            "哑铃",
            "咖啡机",
        ]
        residual = re.sub(r"\d+(?:\.\d{1,2})?\s*(?:英寸|寸|元以内|元以下)", "", residual)
        residual = re.sub(r"([一二两三四五六七八九十]|\d+)\s*(?:件|个|台|把|副|只)", "", residual)
        for word in sorted(words, key=len, reverse=True):
            residual = residual.replace(word, "")
        if residual.strip(" ：:、，,；;。!！?？"):
            raise clarify()
        parts.append(
            BundlePart(
                category=category, quantity=quantity, requirements=query, prefer_quiet=prefer
            )
        )
    try:
        return BundleRequirements(budget_cents=budget, parts=parts)
    except ValueError as error:
        raise clarify() from error
