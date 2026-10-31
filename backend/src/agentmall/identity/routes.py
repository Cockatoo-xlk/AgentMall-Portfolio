from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agentmall.identity.schemas import LoginRequest, TokenDTO, UserDTO
from agentmall.identity.service import ActorContext, authenticate, login, unauthorized

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


async def current_actor(
    request: Request,
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> ActorContext:
    if credential is None:
        raise unauthorized()
    async with request.app.state.sessions.begin() as session:
        return await authenticate(session, request.app.state.settings, credential.credentials)


Actor = Annotated[ActorContext, Depends(current_actor)]


@router.post("/auth/login", response_model=TokenDTO)
async def login_route(payload: LoginRequest, request: Request):
    async with request.app.state.sessions.begin() as session:
        return await login(session, request.app.state.settings, payload.login, payload.password)


@router.get("/me", response_model=UserDTO)
async def me(actor: Actor):
    return UserDTO(user_id=actor.user_id, role=actor.role, store_id=actor.store_id)
