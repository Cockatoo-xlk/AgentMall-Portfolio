import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select

from agentmall.identity.models import User
from agentmall.identity.schemas import TokenDTO
from agentmall.infra.config import Settings
from agentmall.infra.errors import DomainError

PASSWORD_HASHER = PasswordHasher()
# A valid Argon2 hash makes unknown-account password checks follow the same verification path.
DUMMY_HASH = PASSWORD_HASHER.hash("not-a-login-password")


@dataclass(frozen=True)
class ActorContext:
    user_id: UUID | None
    role: Literal["public", "buyer", "merchant"]
    store_id: UUID


def actor_for(user: User, settings: Settings) -> ActorContext:
    return ActorContext(
        user.id, user.role, user.store_id if user.role == "merchant" else settings.storefront_id
    )


def unauthorized():
    return DomainError(401, "UNAUTHORIZED", "认证失败或凭证已失效")


def verify_password(stored: str, supplied: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(stored, supplied)
    except VerificationError:
        return False


async def login(session, settings: Settings, username: str, password: str) -> TokenDTO:
    user = await session.scalar(select(User).where(User.login == username))
    verified = await asyncio.to_thread(
        verify_password, user.password_hash if user else DUMMY_HASH, password
    )
    if not verified or user is None or user.disabled:
        raise unauthorized()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_minutes),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return TokenDTO(access_token=token, expires_in=settings.jwt_minutes * 60)


async def authenticate(session, settings: Settings, token: str) -> ActorContext:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        user_id = UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise unauthorized() from exc
    user = await session.scalar(select(User).where(User.id == user_id, User.disabled.is_(False)))
    if user is None:
        raise unauthorized()
    return actor_for(user, settings)


def require_buyer(actor: ActorContext):
    if actor.role != "buyer" or actor.user_id is None:
        raise DomainError(403, "FORBIDDEN", "此接口仅供买家使用")


def require_merchant(actor: ActorContext):
    if actor.role != "merchant" or actor.user_id is None:
        raise DomainError(403, "FORBIDDEN", "此接口仅供所属店铺商家使用")
