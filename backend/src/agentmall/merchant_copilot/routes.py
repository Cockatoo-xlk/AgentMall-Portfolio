import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from agentmall.identity.routes import Actor
from agentmall.identity.service import require_merchant
from agentmall.infra.errors import DomainError

from .contracts import CheckRequest, PolicyArgs, Question
from .runtime import analyze_events, model_for
from .tools import DomainReader

router = APIRouter(prefix="/merchant/copilot")


@router.get("/meta")
async def meta(request: Request, actor: Actor):
    require_merchant(actor)
    model = getattr(request.app.state, "merchant_copilot_model", None)
    return {
        "model_mode": model.mode if model else "MODEL_DISABLED",
        "read_only": True,
        "max_model_calls": 2,
        "max_read_tools": 6,
        "max_list_records": 200,
        "max_pages_per_tool": 5,
        "max_seconds": 15,
        "execution": "NO_BUSINESS_WRITE_TOOLS",
    }


@router.post("/analyze")
async def analyze(request: Request, actor: Actor, payload: Question):
    require_merchant(actor)
    events, result = [], None
    async for kind, value in analyze_events(request.app, actor, payload):
        if kind == "progress":
            events.append(value)
        else:
            result = value
    return result | {"events": events}


@router.post("/analyze/stream")
async def stream(request: Request, actor: Actor, payload: Question):
    require_merchant(actor)
    model_for(request.app)

    async def frames():
        try:
            async for kind, value in analyze_events(request.app, actor, payload):
                if await request.is_disconnected():
                    break
                data = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                yield f"event: {kind}\ndata: {data}\n\n"
        except DomainError as exc:
            yield f"event: analysis_error\ndata: {json.dumps({'code': exc.code})}\n\n"
        except Exception:
            # No raw model/DB exception, tool arguments or auth header enters the stream.
            yield 'event: analysis_error\ndata: {"code":"COPILOT_FAILED"}\n\n'

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/check")
async def check(request: Request, actor: Actor, payload: CheckRequest):
    require_merchant(actor)
    checked = []
    async with request.app.state.sessions.begin() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout=2000"))
        reader = DomainReader(request.app, session, actor)
        for ref in payload.references:
            if ref.kind == "policy":
                found = next(
                    (
                        e
                        for e in await reader.policy(PolicyArgs(case_id=ref.case_id))
                        if e["id"] == str(ref.id)
                    ),
                    None,
                )
                if found is None:
                    raise DomainError(404, "NOT_FOUND", "证据已不可访问")
            else:
                found = await reader.detail(ref.kind, ref.id)
            checked.append(
                {
                    "kind": ref.kind,
                    "id": str(ref.id),
                    "unchanged": found["fingerprint"] == ref.fingerprint,
                    "status": found["status"],
                    "version": found["version"],
                }
            )
    return {"unchanged": all(c["unchanged"] for c in checked), "items": checked}
