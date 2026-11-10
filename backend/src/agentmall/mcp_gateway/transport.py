"""Local transport guard, not a remote OAuth implementation or JSON-RPC server."""

import asyncio
import re

from sqlalchemy.exc import DBAPIError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from agentmall.identity.service import authenticate
from agentmall.infra.errors import DomainError


class LocalGuard:
    def __init__(self, asgi, domain_app):
        self.asgi = asgi
        self.domain_app = domain_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.asgi(scope, receive, send)
        headers = Headers(scope=scope)

        async def reject(status, code):
            await JSONResponse(
                {
                    "code": code,
                    "auth": "LOCAL_BEARER_ONLY",
                    "remote_auth": "REMOTE_AUTH_NOT_IMPLEMENTED",
                },
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)

        peer = (scope.get("client") or ("", 0))[0]
        host = headers.get("host", "")
        match = re.fullmatch(r"(127\.0\.0\.1|localhost)(?::([0-9]{1,5}))?", host)
        if (
            peer not in ["127.0.0.1", "::1"]
            or not match
            or (match[2] and not 1 <= int(match[2]) <= 65535)
        ):
            return await reject(403, "LOCAL_ONLY")
        if any(
            k in headers
            for k in ["forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"]
        ):
            return await reject(403, "PROXY_NOT_SUPPORTED")
        origin = headers.get("origin")
        if origin is not None and origin != f"http://{host}":
            return await reject(403, "ORIGIN_REJECTED")
        if scope.get("query_string"):
            return await reject(400, "QUERY_PARAMETERS_FORBIDDEN")
        try:
            from agentmall.mcp_gateway.server import credential

            token = credential(headers.get("authorization"))
            if token is not None:
                async with asyncio.timeout(5):
                    async with self.domain_app.state.sessions.begin() as session:
                        await authenticate(session, self.domain_app.state.settings, token)
        except DomainError:
            return await reject(401, "UNAUTHORIZED")
        except (TimeoutError, DBAPIError):
            return await reject(503, "AUTH_UNAVAILABLE")
        length = headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > 65536):
            return await reject(413, "REQUEST_TOO_LARGE")
        # Legacy HTTP is intentionally out of scope. Its session-era path does not
        # interpret modern body metadata. Never silently select it via a header.
        if scope["method"] == "POST" and headers.get("mcp-protocol-version") != "2026-07-28":
            return await reject(426, "PROTOCOL_VERSION_UNSUPPORTED")
        # SDK owns framing, size enforcement, metadata negotiation and cancellation.
        await self.asgi(scope, receive, send)
