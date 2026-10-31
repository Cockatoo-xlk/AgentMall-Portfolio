"""Durable application execution: ownership, deduplication, fencing and receipt reconciliation."""

import asyncio
import re
from copy import deepcopy
from dataclasses import asdict
from uuid import UUID, uuid4, uuid5

from langgraph.types import Command
from langsmith import tracing_context
from psycopg import OperationalError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import DBAPIError

from agentmall.actions.service import database_now, get_proposal, payload_hash
from agentmall.agents.budgets import Limits, RunStopped
from agentmall.agents.context import Constraints, MultiRequest, user_constraints
from agentmall.agents.durable_budget import DurableBudget
from agentmall.agents.durable_graph import build_durable_graph
from agentmall.agents.graph import render
from agentmall.agents.locking import claim_execution, thread_lock
from agentmall.agents.models import AgentRun, AgentThread, RunEvent
from agentmall.agents.persistence import checkpoint_config, checkpoint_saver
from agentmall.agents.resume import validate_confirmation
from agentmall.agents.runtime import RunContext, fingerprint
from agentmall.agents.specialist_tools import recover_receipts
from agentmall.agents.specialists.runner import PROMPTS, SINGLE_PROMPT
from agentmall.agents.state import merge_state, restore, snapshot
from agentmall.agents.supervisor import SYSTEM_PROMPT
from agentmall.identity.service import require_buyer
from agentmall.infra.errors import DomainError, not_found
from agentmall.infra.observability import public_summary

RECOVERABLE_ERRORS = {"EXECUTION_INTERRUPTED", "EXECUTION_TIMEOUT", "DATABASE_UNAVAILABLE"}


def sanitized(message):
    message = re.sub(
        r"地址\s*[:：=]?\s*(演示宿舍|演示家庭)(?=[，。；;\n\s]|$)",
        lambda match: "送" + match[1],
        message,
    )
    message = re.sub(r"(?i)(?:bearer\s+)?eyJ[\w-]+\.[\w-]+\.[\w-]+", "[REDACTED]", message)
    message = re.sub(
        r"(?i)(?:密码|password|api[_ -]?key|token|jwt|地址)\s*[:：=]?\s*[^，。；;\n]+",
        "[REDACTED]",
        message,
    )
    return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", message)


def prompt_version():
    return fingerprint(
        {
            "supervisor": SYSTEM_PROMPT,
            "specialists": PROMPTS,
            "single": SINGLE_PROMPT,
            "shell": "t09-v1",
        }
    )


def model_identity(app, mode):
    models = app.state.multi_models or {}
    if mode == "single":
        models = {"single": app.state.durable_single_model}
    identities = {
        role: {
            "type": getattr(model, "_llm_type", "disabled"),
            "model": getattr(model, "model_name", getattr(model, "model", None)),
        }
        for role, model in models.items()
    }
    return "sha256:" + fingerprint(identities)


async def owned_thread(session, actor, thread_id):
    require_buyer(actor)
    thread = await session.scalar(
        select(AgentThread).where(
            AgentThread.id == thread_id,
            AgentThread.user_id == actor.user_id,
            AgentThread.store_id == actor.store_id,
        )
    )
    if thread is None:
        raise not_found()
    return thread


def view(run):
    # Public structured requirements only; never return persisted user prose.
    request = MultiRequest(thread_id=run.thread_id, **run.request_payload)
    constraints = user_constraints(request).model_dump(mode="json")
    for entry in sorted(run.node_journal.values(), key=lambda e: e["seq"]):
        value = entry["output"].get("runtime_state", {}).get("constraints")
        if value is not None:
            constraints = Constraints.model_validate(value).model_dump(mode="json")
    return {
        "constraints": constraints,
        "id": str(run.id),
        "thread_id": str(run.thread_id),
        "request_id": str(run.request_id),
        "status": run.status,
        "input_digest": run.input_digest,
        "prompt_version": run.prompt_version,
        "model_id": run.model_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "last_error": run.last_error,
        "pending_confirmation": run.pending_confirmation,
        "result": run.result,
        "budget": run.budget.get("used", {}),
        "epoch": run.epoch,
    }


async def create_thread(app, actor, mode):
    require_buyer(actor)
    if app.state.settings.checkpoint_schema is None:
        raise DomainError(
            503, "PERSISTENCE_UNCONFIGURED", "需显式配置并初始化独立Checkpoint schema"
        )
    async with app.state.sessions.begin() as session:
        thread = AgentThread(
            user_id=actor.user_id, store_id=actor.store_id, mode=mode, status="ACTIVE"
        )
        session.add(thread)
        await session.flush()
        return {"id": str(thread.id), "mode": thread.mode, "status": thread.status}


async def get_thread(app, actor, thread_id):
    async with app.state.sessions.begin() as session:
        thread = await owned_thread(session, actor, thread_id)
        runs = await session.scalars(
            select(AgentRun)
            .where(AgentRun.thread_id == thread_id)
            .order_by(AgentRun.created_at.desc())
            .limit(50)
        )
        return {
            "id": str(thread.id),
            "mode": thread.mode,
            "status": thread.status,
            "runs": [view(r) for r in runs],
        }


async def events(app, actor, run_id, after_seq, limit):
    async with app.state.sessions.begin() as session:
        run = await session.get(AgentRun, run_id)
        if run is None:
            raise not_found()
        await owned_thread(session, actor, run.thread_id)
        rows = list(
            await session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
                .limit(limit)
            )
        )
        return {
            "items": [
                {
                    "id": str(e.id),
                    "seq": e.seq,
                    "event_type": e.event_type,
                    "agent": e.agent,
                    "action_id": str(e.action_id) if e.action_id else None,
                    "payload_summary": public_summary(e.event_type, e.payload_summary),
                    "timestamp": e.timestamp,
                }
                for e in rows
            ],
            "next_seq": rows[-1].seq if rows else after_seq,
        }


def add_event(session, run, kind, payload=None, agent=None, action_id=None):
    run.event_seq += 1
    session.add(
        RunEvent(
            run_id=run.id,
            seq=run.event_seq,
            event_type=kind,
            agent=agent,
            action_id=UUID(action_id) if action_id else None,
            payload_summary=public_summary(kind, payload or {}),
        )
    )


class NodeStore:
    def __init__(self, fence):
        self.fence = fence
        self.failure = None  # Ephemeral exception identity; never serialized.

    async def cached(self, key):
        async with self.fence.sessions.begin() as session:
            run = await self.fence.check(session)
            entry = run.node_journal.get(key)
            return deepcopy(entry["output"]) if entry else None

    async def save(self, key, output, trace):
        async with self.fence.sessions.begin() as session:
            run = await self.fence.check(session, exclusive=True)
            run.node_journal = {**run.node_journal, key: {"seq": run.event_seq, "output": output}}
            for event in trace:
                if event["kind"] in {
                    "model_start",
                    "model_end",
                } and f"{event['kind']}:{event.get('attempt')}" in run.budget.get(
                    "model_events", []
                ):
                    continue
                summary = public_summary(event["kind"], event)
                add_event(
                    session, run, event["kind"], summary, event.get("role"), event.get("action_id")
                )
            add_event(session, run, "node_completed", {"node": key})


async def activate(app, actor, run_id, thread, connection, resume_payload=None):
    sessions = app.state.sessions
    async with sessions.begin() as session:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        fence = await claim_execution(session, run, connection, sessions)
        original = deepcopy(run.request_payload)
        external_request_id = run.request_id
        add_event(session, run, "run_activated", {"epoch": run.epoch})
    budget = DurableBudget(fence)
    await budget.reload()
    models = app.state.multi_models
    if thread.mode == "single":
        model = app.state.durable_single_model
        models = (
            {k: model for k in ("supervisor", "shopping", "order", "aftersales")} if model else None
        )
    payload = MultiRequest(
        request_id=uuid5(run_id, "business"),
        thread_id=thread.id,
        message=original["message"],
        constraints=original.get("constraints"),
    )
    runtime = RunContext(
        actor,
        app.state.settings,
        sessions,
        payload,
        models or {},
        app.state.retrieval_encoder,
        budget,
        {},
        guard=fence.check,
        single=thread.mode == "single",
    )
    config = checkpoint_config(thread.id, run_id)
    waiting = None
    state = None
    error = None
    node_store = NodeStore(fence)
    try:
        if not models:
            raise DomainError(503, "MODEL_DISABLED", "模型未启用")
        async with checkpoint_saver(app.state.settings, fence) as saver:
            graph = build_durable_graph(runtime, saver, node_store)
            previous = await graph.aget_state(config)
            resume_matches = bool(
                previous.interrupts
                and resume_payload
                and previous.interrupts[0].id == resume_payload["interrupt_id"]
            )
            if previous.values:
                state = previous.values
                restore(runtime, state["runtime_state"])
                value = Command(resume=resume_payload) if resume_matches else None
            else:
                value = {
                    "thread_id": str(thread.id),
                    "run_id": str(run_id),
                    "request_id": str(external_request_id),
                    "user_goal": original["message"],
                    "runtime_state": snapshot(runtime),
                    "round": 0,
                    "handled": [],
                }
            if previous.interrupts and not resume_matches:
                # A prior resume may already have reached another interrupt before
                # the Run row was finalized. Reconcile it; never consume the next one.
                state = previous.values
            elif previous.values and not previous.next:
                state = previous.values
            else:
                with tracing_context(enabled=False):
                    async with asyncio.timeout(budget.seconds_left):
                        state = await graph.ainvoke(value, config, durability="sync")
            saved = await graph.aget_state(config)
            state = saved.values
            restore(runtime, state["runtime_state"])
            if saved.interrupts:
                event = saved.interrupts[0]
                waiting = {"interrupt_id": event.id, **event.value}
    except Exception as exc:
        # The global deadline can cancel Pregel before a draining node rethrows.
        # Preserve a failure already observed by this execution, not a later timeout.
        if isinstance(exc, TimeoutError) and node_store.failure is not None:
            exc = node_store.failure
        if isinstance(exc, (DBAPIError, OperationalError)):
            error = "DATABASE_UNAVAILABLE"
        elif isinstance(exc, (DomainError, RunStopped)):
            error = exc.code
        else:
            error = (
                "EXECUTION_TIMEOUT" if isinstance(exc, TimeoutError) else "EXECUTION_INTERRUPTED"
            )
        runtime.errors.append(error)
        # Node journal may be newer than the last checkpoint; reconstruct committed outputs.
        async with sessions.begin() as session:
            current = await fence.check(session)
            recovered = (
                state.get("runtime_state", snapshot(runtime)) if state else snapshot(runtime)
            )
            for entry in sorted(current.node_journal.values(), key=lambda e: e["seq"]):
                recovered = merge_state(recovered, entry["output"].get("runtime_state", {}))
            restore(runtime, recovered)
            if error not in runtime.errors:
                runtime.errors.append(error)
    await budget.reload()
    async with asyncio.timeout(5):
        await recover_receipts(runtime)
    result = (
        render(runtime, "finish")
        .model_copy(update={"request_id": external_request_id})
        .model_dump(mode="json")
    )
    async with sessions.begin() as session:
        run = await fence.check(session, exclusive=True)
        run.result = result
        run.pending_confirmation = waiting
        run.last_error = error
        run.status = (
            "WAITING_INPUT"
            if waiting
            else "PARTIAL"
            if error or result["error_codes"]
            else "COMPLETED"
        )
        if not waiting:
            run.finished_at = await database_now(session)
        run.worker_token = None
        run.lock_pid = None
        if resume_payload and "request_id" in resume_payload:
            journal = deepcopy(run.resume_journal)
            entry = journal[resume_payload["request_id"]]
            entry["completed"] = error is None
            run.resume_journal = journal
        current_thread = await session.get(AgentThread, thread.id)
        current_thread.status = "HUMAN_HANDOFF" if waiting else "ACTIVE"
        add_event(session, run, "run_state", {"status": run.status, "error_code": error})
        await session.flush()
        return view(run)


async def refresh_expired(app, actor, thread, connection, run_id=None):
    """POST-side reconciliation only: expiry is a DB fact, never an approval."""
    async with app.state.sessions.begin() as session:
        query = select(AgentRun).where(
            AgentRun.thread_id == thread.id, AgentRun.status == "WAITING_INPUT"
        )
        if run_id is not None:
            query = query.where(AgentRun.id == run_id)
        run = await session.scalar(query)
        if run is None:
            return
        pending = run.pending_confirmation or {}
        if pending.get("type") != "confirmation":
            return
        if run.prompt_version != prompt_version() or run.model_id != model_identity(
            app, thread.mode
        ):
            return
        proposal = await get_proposal(session, actor, UUID(pending["proposal_id"]))
        if proposal.status != "EXPIRED" or proposal.result is not None:
            return
        value = {
            "interrupt_id": pending["interrupt_id"],
            "proposal_id": pending["proposal_id"],
            "expired": True,
        }
        target = run.id
    await activate(app, actor, target, thread, connection, value)


async def start_run(app, actor, thread_id, payload):
    digest = payload_hash(payload.model_dump(mode="json"))
    async with app.state.sessions.begin() as session:
        thread = await owned_thread(session, actor, thread_id)
    async with thread_lock(app.state.settings, thread_id) as connection:
        await refresh_expired(app, actor, thread, connection)
        async with app.state.sessions.begin() as session:
            await owned_thread(session, actor, thread_id)
            run = await session.scalar(
                select(AgentRun).where(
                    AgentRun.thread_id == thread_id, AgentRun.request_id == payload.request_id
                )
            )
            created = run is None
            if run:
                if run.input_digest != digest:
                    raise DomainError(409, "IDEMPOTENCY_CONFLICT", "相同请求ID对应不同输入")
                if run.prompt_version != prompt_version():
                    raise DomainError(409, "RUN_VERSION_MISMATCH", "运行提示版本已变化")
                if run.model_id != model_identity(app, thread.mode):
                    raise DomainError(409, "RUN_VERSION_MISMATCH", "运行模型已变化")
                if run.status in {"WAITING_INPUT", "COMPLETED", "FAILED"} or (
                    run.status == "PARTIAL" and run.last_error not in RECOVERABLE_ERRORS
                ):
                    return view(run), False
            else:
                busy = await session.scalar(
                    select(AgentRun.id).where(
                        AgentRun.thread_id == thread_id,
                        or_(
                            AgentRun.status.in_(["RUNNING", "WAITING_INPUT"]),
                            and_(
                                AgentRun.status == "PARTIAL",
                                AgentRun.last_error.in_(RECOVERABLE_ERRORS),
                            ),
                        ),
                    )
                )
                if busy:
                    raise DomainError(409, "THREAD_BUSY", "请先恢复此会话已有运行")
                body = payload.model_dump(mode="json")
                body["message"] = sanitized(body["message"])
                run = AgentRun(
                    id=uuid4(),
                    thread_id=thread_id,
                    request_id=payload.request_id,
                    status="RUNNING",
                    input_digest=digest,
                    prompt_version=prompt_version(),
                    model_id=model_identity(app, thread.mode),
                    request_payload=body,
                    budget={},
                    node_journal={},
                    resume_journal={},
                    event_seq=0,
                    epoch=0,
                )
                session.add(run)
                await session.flush()
                add_event(session, run, "run_created")
            run_id = run.id
        return await activate(app, actor, run_id, thread, connection), created


async def resume_thread(app, actor, thread_id, payload):
    body = payload.model_dump(mode="json", exclude_none=True)
    digest = payload_hash(body)
    if "clarification" in body:
        body["clarification"] = sanitized(body["clarification"])
    async with app.state.sessions.begin() as session:
        thread = await owned_thread(session, actor, thread_id)
    async with thread_lock(app.state.settings, thread_id) as connection:
        await refresh_expired(app, actor, thread, connection, payload.run_id)
        async with app.state.sessions.begin() as session:
            run = await session.scalar(
                select(AgentRun)
                .where(AgentRun.id == payload.run_id, AgentRun.thread_id == thread_id)
                .with_for_update()
            )
            if run is None:
                raise not_found()
            if run.prompt_version != prompt_version() or run.model_id != model_identity(
                app, thread.mode
            ):
                raise DomainError(409, "RUN_VERSION_MISMATCH", "运行提示或模型版本已变化")
            prior = run.resume_journal.get(str(payload.request_id))
            if prior:
                if prior["digest"] != digest:
                    raise DomainError(409, "IDEMPOTENCY_CONFLICT", "恢复请求内容不同")
                if prior["completed"]:
                    return view(run)
            else:
                pending = run.pending_confirmation
                if not pending or pending["interrupt_id"] != payload.interrupt_id:
                    raise DomainError(409, "STALE_INTERRUPT", "恢复必须匹配当前中断")
                if pending.get("type") == "clarification":
                    if not payload.clarification:
                        raise DomainError(409, "CLARIFICATION_REQUIRED", "需要补充信息")
                else:
                    if (
                        pending.get("proposal_id") != str(payload.proposal_id)
                        or payload.confirmation_id is None
                    ):
                        raise DomainError(409, "CONFIRMATION_MISMATCH", "提案与确认不匹配")
                    await validate_confirmation(
                        session, actor, payload.proposal_id, payload.confirmation_id
                    )
                run.resume_journal = {
                    **run.resume_journal,
                    str(payload.request_id): {
                        "digest": digest,
                        "payload": body,
                        "completed": False,
                    },
                }
                add_event(session, run, "resume_received", {"interrupt_id": payload.interrupt_id})
        return await activate(app, actor, payload.run_id, thread, connection, body)


async def trace_page(app, actor, run_id, after_seq, limit):
    page = await events(app, actor, run_id, after_seq, limit)
    async with app.state.sessions.begin() as session:
        run = await session.get(AgentRun, run_id)
        await owned_thread(session, actor, run.thread_id)
        return {
            "request_id": str(run.request_id),
            "thread_id": str(run.thread_id),
            "run_id": str(run.id),
            "model_id": run.model_id,
            "budget": {"used": run.budget.get("used", {}), "limits": asdict(Limits())},
            "status": run.status,
            **page,
            "items": [
                {**e, "span_id": f"{run.id}:{e['seq']}", "parent_span_id": str(run.id)}
                for e in page["items"]
            ],
        }


async def recover_run(app, actor, thread_id, run_id, request_id):
    """Re-enter the original durable execution using only authenticated navigation IDs.

    No new Run, input, approval, budget, or domain command is constructed here.
    This makes recovery possible after the browser has discarded its private input.
    """
    async with app.state.sessions.begin() as session:
        thread = await owned_thread(session, actor, thread_id)
    async with thread_lock(app.state.settings, thread_id) as connection:
        async with app.state.sessions.begin() as session:
            run = await session.scalar(
                select(AgentRun).where(AgentRun.id == run_id, AgentRun.thread_id == thread_id)
            )
            if run is None:
                raise not_found()
            if run.request_id != request_id:
                raise DomainError(409, "IDEMPOTENCY_CONFLICT", "恢复必须引用原请求")
            if run.prompt_version != prompt_version() or run.model_id != model_identity(
                app, thread.mode
            ):
                raise DomainError(409, "RUN_VERSION_MISMATCH", "运行提示或模型版本已变化")
            if run.status != "RUNNING" and run.last_error not in RECOVERABLE_ERRORS:
                return view(run)
            pending_id = (run.pending_confirmation or {}).get("interrupt_id")
            accepted = [
                entry["payload"]
                for entry in run.resume_journal.values()
                if not entry["completed"] and entry["payload"].get("interrupt_id") == pending_id
            ]
            resume_payload = accepted[0] if len(accepted) == 1 else None
        return await activate(app, actor, run_id, thread, connection, resume_payload)
