from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class TokenDTO(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserDTO(BaseModel):
    user_id: UUID
    role: Literal["buyer", "merchant"]
    store_id: UUID
