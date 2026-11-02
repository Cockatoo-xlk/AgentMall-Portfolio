from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt, StrictStr, model_validator

from agentmall.agents.context import Constraints, Strict


class ThreadCreate(Strict):
    mode: Literal["single", "multi"] = "multi"


class RunCreate(Strict):
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000, strict=True)
    constraints: Constraints | None = None
    expected_context_version: int | None = Field(None, ge=0, strict=True)
    candidate_set_id: UUID | None = None


class ResumeRequest(Strict):
    request_id: UUID
    run_id: UUID
    interrupt_id: str = Field(min_length=1, max_length=100, strict=True)
    proposal_id: UUID | None = None
    confirmation_id: UUID | None = None
    clarification: str | None = Field(None, min_length=1, max_length=1500, strict=True)

    @model_validator(mode="after")
    def one_decision(self):
        confirmation = self.proposal_id is not None and self.confirmation_id is not None
        if self.clarification is not None:
            if self.proposal_id is not None or self.confirmation_id is not None:
                raise ValueError("Choose clarification OR confirmation")
        elif not confirmation:
            raise ValueError("Both proposal_id and confirmation_id are required")
        return self


class RecoverRequest(Strict):
    request_id: UUID


class ContextOperation(Strict):
    op: Literal["SET", "REPLACE", "CLEAR"]
    field: Literal[
        "category",
        "max_price_cents",
        "noise_preference",
        "layout",
        "connection",
        "excluded_connections",
        "keyboard_type",
        "usage",
    ]
    value: StrictStr | StrictInt | list[Literal["双模", "三模"]] | None = None

    @model_validator(mode="after")
    def valid_value(self):
        from agentmall.agents.memory import NEEDS

        if self.op == "CLEAR":
            if self.value is not None:
                raise ValueError("CLEAR has no value")
        else:
            if self.value is None:
                raise ValueError("SET/REPLACE require a value")
            data = (
                {"product_needs": {self.field: self.value}}
                if self.field in NEEDS
                else {self.field: self.value}
            )
            Constraints.model_validate(data)
        return self


class ContextPatch(Strict):
    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    operations: list[ContextOperation] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def unique_fields(self):
        if len({op.field for op in self.operations}) != len(self.operations):
            raise ValueError("One operation per field")
        return self
