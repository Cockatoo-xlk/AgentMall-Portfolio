"""The persistent outer graph; same supervisor/specialist core, isolated branch runtime."""

import asyncio
from typing import Annotated, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from agentmall.agents.context import HandoffEnvelope, SpecialistResult
from agentmall.agents.durable_budget import node_key
from agentmall.agents.resume import execute_confirmation
from agentmall.agents.runtime import RunContext
from agentmall.agents.specialist_tools import authenticate, recover_receipts
from agentmall.agents.specialists.runner import run_specialist
from agentmall.agents.state import delta, merge_state, restore, snapshot
from agentmall.agents.supervisor import choose_plan
from agentmall.infra.errors import DomainError


class DurableState(TypedDict, total=False):
    thread_id: str
    run_id: str
    request_id: str
    user_goal: str
    runtime_state: Annotated[dict, merge_state]
    round: int
    plan: dict
    dispatch: list[dict]
    handoff: dict
    next: str
    pending_action: dict | None
    resume_payload: dict
    handled: list[str]


def build_durable_graph(base, saver, store):
    branch_barriers = {}

    def fresh(data):
        local = RunContext(
            base.actor,
            base.settings,
            base.sessions,
            base.input,
            base.models,
            base.encoder,
            base.budget,
            {},
            guard=base.guard,
            single=base.single,
        )
        return restore(local, data)

    def wrap(name, fn):
        async def execute_node(state):
            ident = (
                state.get("handoff", {}).get("subtask_id")
                if name in {"shopping", "order", "aftersales"}
                else None
            )
            if name in {"wait_confirmation", "execute_confirmed"}:
                ident = (state.get("pending_action") or {}).get(
                    "proposal_id", f"clarify:{state.get('round', 0)}"
                )
            if name == "choose_confirmation":
                ident = f"{state.get('round', 0)}:{len(state.get('handled', []))}"
            key = f"{name}:{ident or state.get('round', 0)}"
            cached = await store.cached(key)
            if cached is not None:
                return cached
            token = node_key.set(key)
            try:
                await base.budget.take("steps")
                local = fresh(state["runtime_state"])
                before = snapshot(local)
                async with local.sessions.begin() as session:
                    await authenticate(local, session)
                output = await fn(local, state)
                output["runtime_state"] = delta(before, snapshot(local))
                await store.save(key, output, local.trace["events"])
                return output
            finally:
                node_key.reset(token)

        async def node(state):
            if name not in {"shopping", "order", "aftersales"}:
                return await execute_node(state)
            ident = state["handoff"]["subtask_id"]
            if ident in base.completed:
                return await execute_node(state)
            remaining = set(state["runtime_state"]["pending"]) - set(base.completed)
            barrier = branch_barriers.setdefault(state["round"], asyncio.Barrier(len(remaining)))
            failure = None
            try:
                output = await execute_node(state)
            except Exception as exc:
                failure = exc
                if store.failure is None:
                    store.failure = exc
            # Settle dispatched siblings before Pregel cancels them. External
            # cancellation still propagates; a stalled branch cannot extend the
            # Run deadline. Keep the originating error if draining also times out.
            try:
                async with asyncio.timeout(max(0, base.budget.seconds_left)):
                    await barrier.wait()
            except (TimeoutError, asyncio.CancelledError) as drain_error:
                if failure is not None:
                    raise failure from drain_error
                raise
            if failure is not None:
                raise failure
            return output

        return node

    async def bootstrap(runtime, state):
        await runtime.hydrate_explicit_entities()
        return {"next": "single" if runtime.single else "supervisor"}

    async def supervisor(runtime, state):
        plan = await choose_plan(runtime)
        envelopes = await runtime.validate_tasks(plan.tasks) if plan.tasks else []
        return {
            "round": state.get("round", 0) + 1,
            "plan": plan.model_dump(mode="json"),
            "dispatch": [e.model_dump(mode="json") for e in envelopes],
            "next": plan.terminal or "specialists",
        }

    async def specialist(runtime, state):
        envelope = HandoffEnvelope.model_validate(state["handoff"])
        # Reconcile a domain commit that happened before this node's journal/checkpoint.
        await recover_receipts(runtime)
        action = {"prepare_checkout": "CHECKOUT", "prepare_return": "RETURN_REQUEST"}.get(
            envelope.goal
        )
        existing = [
            UUID(ident)
            for (kind, ident), value in runtime.facts.items()
            if kind == "proposal" and value["action_type"] == action
        ]
        if existing:
            result = SpecialistResult(
                subtask_id=envelope.subtask_id,
                target=envelope.target,
                status="proposal",
                summary="已从业务数据库恢复原提案，等待独立确认。",
                proposal_ids=existing,
            )
            runtime.completed[result.subtask_id] = result
            runtime.pending.pop(result.subtask_id, None)
        else:
            await run_specialist(runtime, envelope)
        return {}

    async def single(runtime, state):
        await recover_receipts(runtime)
        handled = set(state.get("handled", []))
        if any(
            kind == "proposal"
            and ident not in handled
            and value["status"] in {"PENDING", "APPROVED"}
            for (kind, ident), value in runtime.facts.items()
        ):
            return {"next": "finish"}
        await runtime.budget.take("delegations")
        envelope = HandoffEnvelope(
            subtask_id=f"single_{state.get('round', 0)}",
            target="order",
            goal="inspect_orders",
            constraints=runtime.handoff_constraints(),
            entity_refs=list(runtime.references.values()),
            read_only=False,
            remaining_budget=runtime.budget.snapshot(),
        )
        result = await run_specialist(runtime, envelope)
        # Explicit clarification remains possible after an earlier independent
        # business decision. A completed action never authorizes the next action.
        return {"next": "clarify" if result.status == "needs_input" else "finish"}

    async def merge(runtime, state):
        handled = set(state.get("handled", []))
        if any(
            kind == "proposal"
            and ident not in handled
            and value["status"] in {"PENDING", "APPROVED"}
            for (kind, ident), value in runtime.facts.items()
        ):
            return {"next": "choose_confirmation"}
        return {"next": "supervisor"}

    async def choose_confirmation(runtime, state):
        await recover_receipts(runtime)
        handled = set(state.get("handled", []))
        pending = [
            {"proposal_id": ident, "action_type": value["action_type"]}
            for (kind, ident), value in runtime.facts.items()
            if kind == "proposal"
            and value["status"] in {"PENDING", "APPROVED"}
            and ident not in handled
        ]
        pending.sort(key=lambda p: (p["action_type"] != "RETURN_REQUEST", p["proposal_id"]))
        if pending:
            return {"pending_action": pending[0], "next": "wait_confirmation"}
        if state.get("plan", {}).get("terminal") == "clarify" or state.get("next") == "clarify":
            return {"pending_action": {"type": "clarification"}, "next": "wait_confirmation"}
        return {"pending_action": None, "next": "finish"}

    async def wait_confirmation(runtime, state):
        # All side effects are in other nodes; interrupt may restart this function.
        value = interrupt({"type": "confirmation", **(state["pending_action"] or {})})
        return {"resume_payload": value}

    async def execute(runtime, state):
        payload = state["resume_payload"]
        pending = state["pending_action"] or {}
        if pending.get("type") == "clarification":
            if not payload.get("clarification"):
                raise DomainError(409, "STALE_INTERRUPT", "当前中断需要补充信息")
        elif payload.get("proposal_id") != pending.get("proposal_id") or payload.get(
            "clarification"
        ):
            raise DomainError(409, "STALE_INTERRUPT", "当前中断绑定另一份提案")
        if payload.get("expired"):
            from agentmall.actions.service import get_proposal

            async with runtime.sessions.begin() as session:
                actor = await authenticate(runtime, session)
                proposal = await get_proposal(session, actor, UUID(payload["proposal_id"]))
                if proposal.status != "EXPIRED" or proposal.result is not None:
                    raise DomainError(409, "STALE_INTERRUPT", "仅可自动结束已过期提案的等待")
            runtime.errors.append("STALE_PROPOSAL")
            return {
                "handled": [*state.get("handled", []), payload["proposal_id"]],
                "next": "single" if runtime.single else "supervisor",
                **({"round": state.get("round", 0) + 1} if runtime.single else {}),
            }
        if payload.get("clarification"):
            from agentmall.agents.context import user_constraints

            runtime.input = runtime.input.model_copy(
                update={"message": (runtime.input.message + " " + payload["clarification"])[:2000]}
            )
            runtime.constraints = user_constraints(runtime.input)
            await runtime.hydrate_explicit_entities()
            return {
                "next": "single" if runtime.single else "supervisor",
                "round": state.get("round", 0) + 1,
                "pending_action": None,
            }
        try:
            await execute_confirmation(runtime, payload)
        except DomainError as exc:
            runtime.errors.append(exc.code)
        return {
            "handled": [*state.get("handled", []), payload["proposal_id"]],
            "next": "single" if runtime.single else "supervisor",
            **({"round": state.get("round", 0) + 1} if runtime.single else {}),
        }

    async def finish(runtime, state):
        await recover_receipts(runtime)
        return {"next": "done"}

    def dispatch(state):
        if state["next"] in {"finish", "clarify"}:
            return "choose_confirmation"
        return [
            Send(
                e["target"],
                {
                    "runtime_state": state["runtime_state"],
                    "handoff": e,
                    "round": state["round"],
                },
            )
            for e in state["dispatch"]
        ]

    graph = StateGraph(DurableState)
    for name, fn in [
        ("bootstrap", bootstrap),
        ("supervisor", supervisor),
        ("single", single),
        ("shopping", specialist),
        ("order", specialist),
        ("aftersales", specialist),
        ("merge", merge),
        ("choose_confirmation", choose_confirmation),
        ("wait_confirmation", wait_confirmation),
        ("execute_confirmed", execute),
        ("finish", finish),
    ]:
        graph.add_node(name, wrap(name, fn))
    graph.add_edge(START, "bootstrap")
    graph.add_conditional_edges("bootstrap", lambda s: s["next"], ["single", "supervisor"])
    graph.add_conditional_edges(
        "supervisor", dispatch, ["shopping", "order", "aftersales", "choose_confirmation"]
    )
    for role in ("shopping", "order", "aftersales"):
        graph.add_edge(role, "merge")
    graph.add_conditional_edges("merge", lambda s: s["next"], ["supervisor", "choose_confirmation"])
    graph.add_edge("single", "choose_confirmation")
    graph.add_conditional_edges(
        "choose_confirmation", lambda s: s["next"], ["wait_confirmation", "finish"]
    )
    graph.add_edge("wait_confirmation", "execute_confirmed")
    graph.add_conditional_edges(
        "execute_confirmed", lambda s: s["next"], ["supervisor", "single", "choose_confirmation"]
    )
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=saver)
