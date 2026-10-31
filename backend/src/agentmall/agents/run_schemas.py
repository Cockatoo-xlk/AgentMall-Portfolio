from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from agentmall.agents.context import Constraints, Strict


class ThreadCreate(Strict):
    mode: Literal["single", "multi"] = "multi"


class RunCreate(Strict):
    request_id: UUID
    message: str = Field(min_length=1, max_length=2000, strict=True)
    constraints: Constraints | None = None


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
