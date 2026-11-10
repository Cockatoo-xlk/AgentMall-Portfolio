from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentmall.catalog.categories import Category

ATTRIBUTES = {
    "keyboard": "switch size noise connection connection_capabilities usage",
    "mouse": "switch size noise connection connection_capabilities usage sensitivity weight",
    "headphones": "switch size form noise connection connection_capabilities usage driver weight",
    "smartphone": (
        "memory storage screen_inches screen_size battery_grade imaging usage processor_tier"
    ),
    "laptop": "processor_tier memory storage weight screen_inches screen_size usage",
    "tablet": "memory storage screen_inches screen_size battery_grade usage weight",
    "monitor": "screen_inches screen_size resolution refresh_rate panel ports usage",
    "camera": "camera_type sensor_class video weight usage",
    "smartwatch": "screen_inches screen_size battery_grade features usage weight",
    "speaker": "speaker_type power connection connection_capabilities usage weight",
    "cycling": "equipment_type usage size material weight",
    "fitness": "equipment_type resistance weight usage material",
    "home_appliance": "appliance_type capacity power features usage",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductData(Strict):
    name: str = Field(min_length=1, max_length=200, strict=True)
    category: Category | None = None
    description: str = Field("", max_length=4000, strict=True)
    attributes: dict[str, str | list[Literal["wired", "wireless"]]] = Field(
        default_factory=dict, max_length=24
    )
    price_cents: int = Field(ge=0, le=100_000_000, strict=True)
    on_hand: int = Field(ge=0, le=1_000_000, strict=True)

    @model_validator(mode="after")
    def safe_fields(self):
        import re

        for value in [
            self.name,
            self.description,
            *self.attributes.keys(),
            *[
                v
                for attr_value in self.attributes.values()
                for v in (attr_value if isinstance(attr_value, list) else [attr_value])
            ],
        ]:
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\u202a-\u202e\u2066-\u2069]", value):
                raise ValueError("Control characters forbidden")
        if self.name.startswith(("=", "+", "@")) or not self.name.strip():
            raise ValueError("Invalid product name")
        allowed = (
            set(ATTRIBUTES[self.category].split())
            if self.category
            else set(" ".join(ATTRIBUTES.values()).split())
        )
        if any(
            k not in allowed
            or (
                isinstance(v, list)
                and (
                    k != "connection_capabilities" or not 1 <= len(v) <= 2 or len(set(v)) != len(v)
                )
            )
            or (isinstance(v, str) and (k == "connection_capabilities" or not 1 <= len(v) <= 200))
            for k, v in self.attributes.items()
        ):
            raise ValueError("Unsupported category attribute or value")
        return self


class Command(Strict):
    request_id: UUID


class VersionCommand(Command):
    expected_version: int = Field(ge=1, strict=True)


class DraftCreate(Command):
    data: ProductData


class DraftEdit(VersionCommand):
    data: ProductData


class Approve(VersionCommand):
    reviewed: Literal[True]


class Reject(VersionCommand):
    reason: str = Field(min_length=1, max_length=500, strict=True)


class ImportRequest(Command):
    format: Literal["csv", "json"]
    content: str = Field(max_length=131072, strict=True)
    assist: bool = False


class Filters(Strict):
    cursor: UUID | None = None
    limit: int = Field(20, ge=1, le=100)
    status: str | None = Field(None, max_length=32)
    category: Category | None = None
