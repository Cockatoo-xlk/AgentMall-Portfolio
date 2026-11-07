"""Versioned, validated, insert-only synthetic catalogue resource."""

import json
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentmall.catalog.categories import Category

CatalogProfile = Literal["legacy", "expanded"]
LEGACY_DATASET = "legacy-12-v1"
EXPANDED_DATASET = "expanded-120-v1"


class SeedProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    sku: str = Field(pattern=r"^[a-z_]+-[0-9]{2}$")
    name: str = Field(min_length=1, max_length=200)
    category: Category
    description: str = Field(min_length=20, max_length=1200)
    attributes: dict[str, str] = Field(min_length=3)
    price_cents: int = Field(gt=0, le=100_000_000)
    on_hand: int = Field(ge=1, le=500)


def expanded_products():
    data = json.loads(files("agentmall.catalog").joinpath("data/expanded-v1.json").read_text())
    if data["dataset"] != EXPANDED_DATASET:
        raise ValueError("Unknown expanded catalogue identity")
    products = tuple(SeedProduct.model_validate(p) for p in data["products"])
    if (
        len(products) != 108
        or len({p.sku for p in products}) != 108
        or len({p.name for p in products}) != 108
    ):
        raise ValueError("Expanded catalogue must contain 108 unique additions")
    return products
