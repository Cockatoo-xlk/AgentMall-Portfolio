from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from agentmall.agents import run_service
from agentmall.agents.context import GraphResult, MultiRequest
from agentmall.agents.graph import run_graph
from agentmall.agents.run_schemas import RecoverRequest, ResumeRequest, RunCreate, ThreadCreate
from agentmall.agents.schemas import AgentRequest, AgentResponse
from agentmall.agents.single_agent import run_single_agent
from agentmall.identity.routes import Actor
from agentmall.infra.observability import export_optional

router = APIRouter()


@router.get("/agent/runtime")
async def workflow_runtime(request: Request, actor: Actor, run_id: UUID | None = None):
    from agentmall.playground.runtime import runtime_status

    return await runtime_status(request.app, actor, run_id)


@router.post("/agent/threads", status_code=201)
async def create_thread(request: Request, actor: Actor, payload: ThreadCreate):
    return await run_service.create_thread(request.app, actor, payload.mode)


@router.get("/agent/threads/{thread_id}")
async def get_thread(request: Request, actor: Actor, thread_id: UUID):
    return await run_service.get_thread(request.app, actor, thread_id)


@router.post("/agent/threads/{thread_id}/runs")
async def start_run(
    request: Request, response: Response, actor: Actor, thread_id: UUID, payload: RunCreate
):
    result, created = await run_service.start_run(request.app, actor, thread_id, payload)
    await export_optional(request.app, actor, UUID(result["id"]))
    response.status_code = 201 if created else 200
    return result


@router.post("/agent/threads/{thread_id}/resume")
async def resume_thread(request: Request, actor: Actor, thread_id: UUID, payload: ResumeRequest):
    result = await run_service.resume_thread(request.app, actor, thread_id, payload)
    await export_optional(request.app, actor, UUID(result["id"]))
    return result


@router.get("/agent/runs/{run_id}/events")
async def run_events(
    request: Request,
    actor: Actor,
    run_id: UUID,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return await run_service.events(request.app, actor, run_id, after_seq, limit)


@router.post("/agent/messages", response_model=AgentResponse)
async def message(request: Request, actor: Actor, payload: AgentRequest):
    return await run_single_agent(
        actor,
        payload.request_id,
        payload.message,
        sessions=request.app.state.sessions,
        model=request.app.state.agent_model,
        budget=request.app.state.agent_budget_factory(),
        trace=request.app.state.agent_trace_factory(),
    )


@router.post("/agent/multi/messages", response_model=GraphResult)
async def multi_message(request: Request, actor: Actor, payload: MultiRequest):
    return await run_graph(
        actor,
        payload.thread_id,
        payload,
        sessions=request.app.state.sessions,
        settings=request.app.state.settings,
        models=request.app.state.multi_models,
        encoder=request.app.state.retrieval_encoder,
        budget=request.app.state.multi_budget_factory(),
        trace=request.app.state.multi_trace_factory(),
    )


@router.get("/agent/runs/{run_id}/trace")
async def trace(
    request: Request,
    actor: Actor,
    run_id: UUID,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return await run_service.trace_page(request.app, actor, run_id, after_seq, limit)


@router.post("/agent/threads/{thread_id}/runs/{run_id}/recover")
async def recover_run(
    request: Request, actor: Actor, thread_id: UUID, run_id: UUID, payload: RecoverRequest
):
    result = await run_service.recover_run(
        request.app, actor, thread_id, run_id, payload.request_id
    )
    await export_optional(request.app, actor, run_id)
    return result
