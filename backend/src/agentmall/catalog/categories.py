"""Deterministic catalogue vocabulary, never model-generated product facts."""

import re
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
    matches.update(KIND_ATTRIBUTES[KIND_BY_NAME[m[0]]][0] for m in KIND_MENTION.finditer(text))
    if not matches and "电脑" in text:
        matches.add("laptop")
    if not matches and "屏幕" in text:
        matches.add("monitor")
    return matches


def infer_category(value):
    matches = categories_in_text(value)
    return next(iter(matches)) if len(matches) == 1 else None


_GENERIC_ALIASES = {
    "smartphone": ("智能手机",),
    "laptop": ("笔记本", "电脑"),
    "tablet": ("平板",),
    "monitor": ("屏幕", "显示屏", "电脑显示器"),
    "camera": ("相机", "摄影"),
    "cycling": ("骑行",),
    "fitness": ("健身",),
    "home_appliance": ("家电", "生活电器"),
}


def category_names(category):
    """Whole-category names, excluding both activity hints and concrete product types."""
    if category not in CATEGORY_LABELS:
        return ()
    return (category, CATEGORY_LABELS[category], *_GENERIC_ALIASES.get(category, ()))


def bare_category(value):
    """Only whole category names widen a substring search, never subtype phrases."""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    return next((c for c in CATEGORIES if text in category_names(c)), None)


ProductKind = Literal[
    "helmet",
    "cycling_gloves",
    "bike_light",
    "bottle_cage",
    "bike_bag",
    "bike_tools",
    "cycling_jersey",
    "dumbbell",
    "resistance_band",
    "yoga_mat",
    "yoga_block",
    "jump_rope",
    "kettlebell",
    "coffee_machine",
    "kettle",
    "fan",
    "humidifier",
    "vacuum_cleaner",
    "cooking_pot",
    "air_fryer",
]
KIND_ATTRIBUTES = {
    "helmet": ("cycling", "equipment_type", "头盔"),
    "cycling_gloves": ("cycling", "equipment_type", "手套"),
    "bike_light": ("cycling", "equipment_type", "车灯"),
    "bottle_cage": ("cycling", "equipment_type", "水壶架"),
    "bike_bag": ("cycling", "equipment_type", "车包"),
    "bike_tools": ("cycling", "equipment_type", "工具组"),
    "cycling_jersey": ("cycling", "equipment_type", "骑行服"),
    "dumbbell": ("fitness", "equipment_type", "哑铃"),
    "resistance_band": ("fitness", "equipment_type", "阻力带"),
    "yoga_mat": ("fitness", "equipment_type", "训练垫"),
    "yoga_block": ("fitness", "equipment_type", "支撑砖"),
    "jump_rope": ("fitness", "equipment_type", "跳绳"),
    "kettlebell": ("fitness", "equipment_type", "壶铃"),
    "coffee_machine": ("home_appliance", "appliance_type", "咖啡机"),
    "kettle": ("home_appliance", "appliance_type", "电水壶"),
    "fan": ("home_appliance", "appliance_type", "风扇"),
    "humidifier": ("home_appliance", "appliance_type", "加湿器"),
    "vacuum_cleaner": ("home_appliance", "appliance_type", "吸尘器"),
    "cooking_pot": ("home_appliance", "appliance_type", "电煮锅"),
    "air_fryer": ("home_appliance", "appliance_type", "空气炸锅"),
}
# A catalogue name can be more specific than its structured attribute label.
KIND_NAMES = {kind: term for kind, (_, _, term) in KIND_ATTRIBUTES.items()} | {
    "cycling_gloves": "骑行手套",
    "bike_tools": "骑行工具组",
    "yoga_mat": "瑜伽垫",
    "yoga_block": "瑜伽砖",
}
KIND_BY_NAME = {name: kind for kind, name in KIND_NAMES.items()}
KIND_MENTION = re.compile("|".join(sorted(KIND_BY_NAME, key=len, reverse=True)))
MODEL_CODE = r"[A-Za-z][0-9]{1,4}[A-Za-z]{0,3}"


def model_code_pattern(code):
    """Match the whole catalogue model token in both Python and PostgreSQL."""
    return rf"(?<![A-Za-z0-9-]){re.escape(code)}(?![A-Za-z0-9-])"


MODEL_MENTION = re.compile(rf"(?<![A-Za-z0-9-]){MODEL_CODE}(?![A-Za-z0-9-])")


def matches_product_kind(kind, category, attributes):
    if kind is None:
        return True
    expected_category, field, term = KIND_ATTRIBUTES[kind]
    value = attributes.get(field)
    return category == expected_category and isinstance(value, str) and term in value


def infer_product_kind(value):
    matches = {KIND_BY_NAME[m[0]] for m in KIND_MENTION.finditer(value)}
    return next(iter(matches)) if len(matches) == 1 else None


def purchase_identity(value):
    """Resolve affirmative catalogue references; an unrepresentable choice needs input."""
    text = unicodedata.normalize("NFKC", value)

    def choice(pattern):
        positive, rejected = set(), set()
        previous_end = 0
        for match in pattern.finditer(text):
            before = re.split(r"[,，。;；\n]", text[previous_end : match.start()])[-1]
            previous_end = match.end()
            denied = re.search(
                r"(?:不要|不想|不买|不选|不是|不需要|不接受|并非|排除|拒绝|非)", before
            )
            target = rejected if denied else positive
            target.add(match[0].upper())
        if len(positive) > 1 or rejected and (not positive or positive & rejected):
            raise ValueError("A unique affirmative purchase target is required")
        return next(iter(positive), None)

    name = choice(KIND_MENTION)
    return KIND_BY_NAME.get(name), choice(MODEL_MENTION)
