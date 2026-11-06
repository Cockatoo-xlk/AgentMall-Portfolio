"""T08 ephemeral StateGraph; no checkpoints, interrupts or confirmation execution."""

import asyncio
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from langsmith import tracing_context

from agentmall.agents.budgets import GraphBudget, RunStopped
from agentmall.agents.context import GraphResult, MultiRequest, SpecialistResult
from agentmall.agents.runtime import RunContext
from agentmall.agents.specialist_tools import authenticate, recover_receipts
from agentmall.agents.specialists.runner import run_specialist
from agentmall.agents.supervisor import choose_plan
from agentmall.identity.service import require_buyer
from agentmall.infra.errors import DomainError


def merge_results(left, right):
    return {**left, **right}


class GraphState(TypedDict, total=False):
    request_id: str
    thread_id: str
    user_goal: str
    plan: dict
    dispatch: list
    next: str
    handoff: object
    results: Annotated[dict, merge_results]
    entity_refs: list
    budget: dict
    errors: list
    terminated: bool


def build_graph(runtime):
    async def supervisor(state):
        await runtime.budget.take("steps")
        try:
            plan = await choose_plan(runtime)
            envelopes = await runtime.validate_tasks(plan.tasks) if plan.tasks else []
            return {
                "plan": plan.model_dump(mode="json"),
                "dispatch": envelopes,
                "next": plan.terminal or "specialists",
                "budget": runtime.budget.snapshot(),
            }
        except RunStopped as exc:
            code = exc.code
        except DomainError as exc:
            code = exc.code
        except TimeoutError:
            code = "SUPERVISOR_TIMEOUT"
        except Exception:
            code = "SUPERVISOR_FAILED"
        runtime.errors.append(code)
        return {"next": "finish", "errors": list(runtime.errors)}

    def dispatch(state):
        if state["next"] in {"finish", "clarify"}:
            return "finish"
        return [Send(envelope.target, {"handoff": envelope}) for envelope in state["dispatch"]]

    def specialist_node(role):
        async def execute(state):
            envelope = state["handoff"]
            assert envelope.target == role
            await runtime.budget.take("steps")
            try:
                result = await run_specialist(runtime, envelope)
            except RunStopped as exc:
                result = SpecialistResult(
                    subtask_id=envelope.subtask_id,
                    target=role,
                    status="blocked",
                    summary="共享预算已耗尽。",
                    error_code=exc.code,
                )
                runtime.completed[envelope.subtask_id] = result
            if result.error_code in {"BUDGET_EXCEEDED", "MODEL_USAGE_INVALID"}:
                runtime.errors.append(result.error_code)
            return {"results": {result.subtask_id: result}}

        return execute

    async def merge(state):
        await runtime.budget.take("steps")
        return {
            "entity_refs": [r.model_dump(mode="json") for r in runtime.references.values()],
            "budget": runtime.budget.snapshot(),
            "errors": list(runtime.errors),
        }

    def continue_or_finish(state):
        return "finish" if runtime.errors else "supervisor"

    async def finish(state):
        await runtime.budget.take("steps")
        runtime.event("graph_finish", terminal=state.get("next", "finish"))
        return {"terminated": True, "budget": runtime.budget.snapshot()}

    graph = StateGraph(GraphState)
    graph.add_node("supervisor", supervisor)
    for role in ("shopping", "order", "aftersales"):
        graph.add_node(role, specialist_node(role))
    graph.add_node("merge", merge)
    graph.add_node("finish", finish)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", dispatch, ["shopping", "order", "aftersales", "finish"]
    )
    for role in ("shopping", "order", "aftersales"):
        graph.add_edge(role, "merge")
    graph.add_conditional_edges("merge", continue_or_finish, ["supervisor", "finish"])
    graph.add_edge("finish", END)
    return graph.compile()


def render(runtime, terminal):
    runtime.prune_excluded_candidates()
    results = list(runtime.completed.values())
    facts = [
        {"kind": kind, "id": ident, "data": value} for (kind, ident), value in runtime.facts.items()
    ]
    proposals = [f for f in facts if f["kind"] == "proposal"]
    errors = list(dict.fromkeys(runtime.errors + [r.error_code for r in results if r.error_code]))
    lines = []
    for fact in facts:
        data = fact["data"]
        if fact["kind"] == "proposal":
            action = "购买" if data["action_type"] == "CHECKOUT" else "退货申请"
            lines.append(f"{action}提案 {fact['id']}，状态 {data['status']}。")
            if data["status"] == "PENDING":
                lines.append("等待用户独立确认；尚未提交订单或售后申请。")
            elif data["status"] == "REJECTED":
                lines.append("用户已拒绝，没有代替用户再次确认。")
            if data["result"]:
                lines.append(f"数据库回执状态：{data['result']['status']}。")
        elif fact["kind"] == "product":
            lines.append(
                f"商品 {data['name']}（{fact['id']}）："
                f"{data['price_cents']}分，可用{data['available']}。"
            )
        elif fact["kind"] == "order":
            lines.append(
                f"本人订单 {fact['id']}：{data['status']}，政策 {data['policy_version']}。"
            )
        elif fact["kind"] == "eligibility":
            lines.append(
                f"确定性售后资格：{'符合' if data['eligible'] else '不符合'}；"
                f"原因 {','.join(data['reason_codes']) or '无'}。"
            )
        elif fact["kind"] == "ticket":
            lines.append(f"人工工单 {fact['id']}：{data['status']}，未授权任何退款。")
        elif fact["kind"] == "cart":
            lines.append(f"本人购物车：{len(data['items'])}种商品，版本 {data['version']}。")
        elif fact["kind"] == "order_list":
            lines.append(f"本人订单查询返回 {data['count']} 条记录。")
    if "UNSUPPORTED_EVIDENCE" in errors:
        lines.append("没有支持所请求信息的公开证据，不能提供或编造内部信息。")
    if runtime.citations:
        lines.append("政策引用仅作背景；资格以确定性服务为准。")
    if terminal == "clarify":
        lines.append("尚有需求需要补充或继续核验，请明确商品、数量、演示地址或原订单。")
    if any(
        code in errors
        for code in (
            "ORDER_SELECTION_REQUIRED",
            "ORDER_SCOPE_MISMATCH",
            "REPLACEMENT_SOURCE_REQUIRED",
        )
    ):
        lines.append("请明确要处理的本人原订单；替代推荐需要先确定原商品。")
    if "PURCHASE_DETAILS_REQUIRED" in errors:
        lines.append("购买提案需要明确购买意图、数量及演示地址。")
    if errors:
        lines.append("部分步骤未完成，已有真实结果保留。")
    pending = any(p["data"]["status"] in {"PENDING", "APPROVED"} for p in proposals)
    rejected = bool(proposals) and all(p["data"]["status"] == "REJECTED" for p in proposals)
    status = (
        "partial"
        if errors and facts
        else "blocked"
        if errors or rejected
        else "proposal"
        if pending
        else "needs_input"
        if terminal == "clarify" or not facts
        else "done"
    )
    return GraphResult(
        request_id=runtime.input.request_id,
        thread_id=runtime.input.thread_id,
        status=status,
        answer="".join(lines) or "需要补充明确需求，尚未产生业务回执。",
        results=results,
        entity_refs=list(runtime.references.values()),
        proposal_ids=[p["id"] for p in proposals],
        citations=list(runtime.citations.values()),
        facts=facts,
        budget=runtime.budget.snapshot(),
        error_codes=errors,
        unfinished=list(runtime.pending)
        + [r.subtask_id for r in results if r.status in {"error", "blocked", "needs_input"}],
        execution_mode=runtime.mode,
    )


async def run_graph(
    actor,
    thread_id,
    input,
    *,
    sessions,
    settings,
    models=None,
    encoder=None,
    budget=None,
    trace=None,
):
    require_buyer(actor)
    payload = MultiRequest.model_validate(input)
    if payload.thread_id != thread_id:
        raise ValueError("Thread association mismatch")
    budget = budget or GraphBudget()
    if not models:
        return GraphResult(
            request_id=payload.request_id,
            thread_id=thread_id,
            status="blocked",
            answer="多Agent模型未启用，尚未创建提案或订单。",
            budget=budget.snapshot(),
            error_codes=["MODEL_DISABLED"],
            execution_mode="DISABLED",
        )
    if set(models) != {"supervisor", "shopping", "order", "aftersales"}:
        raise ValueError("Four model roles required")
    try:
        runtime = RunContext(
            actor,
            settings,
            sessions,
            payload,
            models,
            encoder,
            budget,
            trace if trace is not None else {},
        )
    except RunStopped as exc:
        return GraphResult(
            request_id=payload.request_id,
            thread_id=thread_id,
            status="blocked",
            answer="运行数据库范围不匹配。",
            budget=budget.snapshot(),
            error_codes=[exc.code],
            execution_mode="DISABLED",
        )
    # Include initial DB acquisition and receipt lookup in the shared wall-time budget.
    try:
        async with asyncio.timeout(min(5, budget.seconds_left)):
            async with sessions.begin() as session:
                await authenticate(runtime, session)
            await recover_receipts(runtime)
    except TimeoutError:
        runtime.errors.append("INITIAL_RECEIPT_RECHECK_FAILED")
        return render(runtime, "finish")
    if runtime.facts:
        return render(runtime, "finish")
    graph = build_graph(runtime)
    runtime.trace["graph_nodes"] = sorted(graph.get_graph().nodes)
    terminal = "finish"
    try:
        with tracing_context(enabled=False):
            async with asyncio.timeout(budget.seconds_left):
                await runtime.hydrate_explicit_entities()
                state = await graph.ainvoke(
                    {
                        "request_id": str(payload.request_id),
                        "thread_id": str(thread_id),
                        "user_goal": payload.message,
                        "results": {},
                        "errors": [],
                        "budget": budget.snapshot(),
                    },
                    config={"recursion_limit": budget.limits.steps + 1, "callbacks": []},
                )
                terminal = state.get("next", "finish")
    except RunStopped as exc:
        runtime.errors.append(exc.code)
    except DomainError as exc:
        runtime.errors.append(exc.code)
    except TimeoutError:
        runtime.errors.append("BUDGET_EXCEEDED")
    except Exception:
        runtime.errors.append("GRAPH_FAILED")
    # Bounded deterministic receipt reconciliation, without another model request.
    try:
        async with asyncio.timeout(5):
            await recover_receipts(runtime)
    except DomainError:
        runtime.facts.clear()
        runtime.references.clear()
        runtime.citations.clear()
        runtime.completed.clear()
        runtime.errors.append("AUTHORIZATION_CHANGED")
    except Exception:
        runtime.errors.append("RECEIPT_RECHECK_FAILED")
    result = render(runtime, terminal)
    runtime.trace["result"] = result.model_dump(mode="json")
    return result
