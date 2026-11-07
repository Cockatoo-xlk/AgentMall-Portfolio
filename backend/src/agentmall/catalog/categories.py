"""Deterministic catalogue vocabulary, never model-generated product facts."""

import unicodedata
from typing import Literal, get_args

Category = Literal[
    "keyboard",
    "mouse",
    "headphones",
    "smartphone",
    "laptop",
    "tablet",
    "monitor",
    "camera",
    "smartwatch",
    "speaker",
    "cycling",
    "fitness",
    "home_appliance",
]
CATEGORIES = get_args(Category)
CATEGORY_LABELS = dict(
    zip(
        CATEGORIES,
        (
            "键盘",
            "鼠标",
            "耳机",
            "手机",
            "笔记本电脑",
            "平板电脑",
            "显示器",
            "摄影器材",
            "智能手表",
            "音箱",
            "骑行装备",
            "健身器材",
            "生活家电",
        ),
        strict=True,
    )
)
CATEGORY_ALIASES = {
    "keyboard": ("键盘",),
    "mouse": ("鼠标",),
    "headphones": ("耳机",),
    "smartphone": ("智能手机", "手机"),
    "laptop": ("笔记本",),
    "tablet": ("平板",),
    "monitor": ("显示器", "显示屏"),
    "camera": ("相机", "摄影", "摄像", "vlog"),
    "smartwatch": ("智能手表", "手表"),
    "speaker": ("音箱", "音响"),
    "cycling": ("骑行", "头盔", "公路车", "自行车"),
    "fitness": ("健身", "哑铃", "阻力带", "瑜伽"),
    "home_appliance": (
        "生活家电",
        "生活电器",
        "家电",
        "咖啡机",
        "电水壶",
        "风扇",
        "加湿器",
        "吸尘器",
    ),
}


def categories_in_text(value):
    text = unicodedata.normalize("NFKC", value).lower().replace("平板电脑", "平板")
    matches = {
        c for c, words in CATEGORY_ALIASES.items() if c in text or any(w in text for w in words)
    }
    if not matches and "电脑" in text:
        matches.add("laptop")
    if not matches and "屏幕" in text:
        matches.add("monitor")
    return matches


def infer_category(value):
    matches = categories_in_text(value)
    return next(iter(matches)) if len(matches) == 1 else None


def bare_category(value):
    """Only whole category names widen a substring search, never subtype phrases."""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    generic = {
        "smartphone": ("智能手机",),
        "laptop": ("笔记本", "电脑"),
        "tablet": ("平板",),
        "monitor": ("屏幕", "显示屏", "电脑显示器"),
        "camera": ("相机", "摄影"),
        "cycling": ("骑行",),
        "fitness": ("健身",),
        "home_appliance": ("家电", "生活电器"),
    }
    return next(
        (c for c in CATEGORIES if text in (c, CATEGORY_LABELS[c], *generic.get(c, ()))), None
    )


ProductKind = Literal["helmet", "dumbbell", "coffee_machine"]
KIND_ATTRIBUTES = {
    "helmet": ("cycling", "equipment_type", "头盔"),
    "dumbbell": ("fitness", "equipment_type", "哑铃"),
    "coffee_machine": ("home_appliance", "appliance_type", "咖啡机"),
}


def infer_product_kind(value):
    matches = {kind for kind, (_, _, term) in KIND_ATTRIBUTES.items() if term in value}
    # Alternative usage (home OR office) cannot revoke an explicit product type.
    # Multiple distinct subtypes remain ambiguous instead of choosing one.
    return next(iter(matches)) if len(matches) == 1 else None
