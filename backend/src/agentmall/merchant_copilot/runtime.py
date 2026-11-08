"""Short-lived LangGraph; only read tools. No buyer thread or durable write executor."""

import asyncio
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agentmall.identity.service import require_merchant
from agentmall.infra.errors import DomainError

from .evidence import permitted, priority, summarize, validate_advice
from .tools import DomainReader


class State(TypedDict, total=False):
    plan: object
    next: int
    evidence: dict
    event: dict
    summary: dict
    advice: object
    result: dict


def model_for(app):
    model = getattr(app.state, "merchant_copilot_model", None)
    if model is None:
        raise DomainError(503, "MODEL_DISABLED", "商家模型未启用；普通API不调用真实Provider")
    if model.mode != "MOCK_TRANSPORT":
        raise DomainError(503, "MODEL_MODE_UNSUPPORTED", "本版本只启用显式MockTransport")
    return model


async def analyze_events(app, actor, question):
    require_merchant(actor)
    model = model_for(app)
    start = time.perf_counter()
    counts = {
        "model_calls": 0,
        "tool_calls": 0,
        "input_token_upper_bound": 0,
        "reported_fixture_input_tokens": 0,
        "reported_fixture_output_tokens": 0,
    }

    async def infer(stage, payload):
        if counts["model_calls"] >= 2:
            raise ValueError("MODEL_CALL_BOUND")
        counts["model_calls"] += 1
        async with asyncio.timeout(5):
            value, size, usage = await model.invoke(stage, payload)
        counts["input_token_upper_bound"] += size
        counts["reported_fixture_input_tokens"] += usage["input_tokens"]
        counts["reported_fixture_output_tokens"] += usage["output_tokens"]
        if (
            counts["input_token_upper_bound"] > 65536
            or counts["reported_fixture_output_tokens"] > 4096
        ):
            raise ValueError("TOKEN_BOUND")
        return value

    try:
        async with asyncio.timeout(15):
            async with app.state.sessions.begin() as session:
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                await session.execute(text("SET LOCAL statement_timeout=2000"))
                reader = DomainReader(app, session, actor, max_pages=question.max_pages)

                focused = (
                    await reader.detail("case", question.case_id) if question.case_id else None
                )

                async def planning(state):
                    plan = await infer("plan", question.model_dump(mode="json"))
                    if (
                        (not plan.calls and not plan.clarification)
                        or len({c.name for c in plan.calls}) != len(plan.calls)
                        or (plan.clarification and plan.calls)
                    ):
                        raise ValueError("INVALID_PLAN")
                    if focused and not plan.clarification:
                        required = {"get_merchant_after_sales", "get_applicable_policy"}
                        if not required <= {c.name for c in plan.calls}:
                            raise ValueError("FOCUSED_CASE_PLAN_INCOMPLETE")
                        for call in plan.calls:
                            if call.name in required and str(call.arguments.get("case_id")) != str(
                                question.case_id
                            ):
                                raise ValueError("FOCUSED_CASE_MISMATCH")
                            if (
                                call.name == "get_merchant_order"
                                and str(call.arguments.get("order_id"))
                                != focused["facts"]["order_id"]
                            ):
                                raise ValueError("FOCUSED_ORDER_MISMATCH")
                    return {
                        "plan": plan,
                        "next": 0,
                        "evidence": {},
                        "event": {
                            "phase": "plan",
                            "tool_names": [c.name for c in plan.calls],
                            "status": "COMPLETED",
                        },
                    }

                async def reading(state):
                    call = state["plan"].calls[state["next"]]
                    tick = time.perf_counter()
                    data = await reader.read(call)
                    counts["tool_calls"] += 1
                    return {
                        "next": state["next"] + 1,
                        "evidence": state["evidence"] | {e["key"]: e for e in data},
                        "event": {
                            "phase": "tool",
                            "name": call.name,
                            "records": len(data),
                            "read_at": reader.read_at,
                            "latency_ms": (time.perf_counter() - tick) * 1000,
                            "status": "COMPLETED",
                        },
                    }

                async def summarizing(state):
                    counts["tool_calls"] += 1
                    return {
                        "summary": summarize(state["evidence"], reader.scopes),
                        "event": {
                            "phase": "tool",
                            "name": "summarize_operations",
                            "records": len(state["evidence"]),
                            "status": "COMPLETED",
                        },
                    }

                async def recommending(state):
                    options = [
                        {"evidence_id": e["key"], "action": permitted(e)}
                        for e in sorted(state["evidence"].values(), key=priority)
                        if permitted(e)
                    ]
                    advice = await infer(
                        "recommend",
                        {
                            "summary": state["summary"],
                            "eligible_options": options[:40],
                            "case_id": str(question.case_id) if question.case_id else None,
                        },
                    )
                    return {
                        "advice": advice,
                        "event": {"phase": "recommend", "status": "COMPLETED"},
                    }

                async def validating(state):
                    suggestions, draft = validate_advice(
                        state["advice"], state["evidence"], question.case_id
                    )
                    result = {
                        "status": "NEEDS_INPUT" if state["plan"].clarification else "COMPLETED",
                        "clarification": state["plan"].clarification,
                        "model_mode": model.mode,
                        "summary": state["summary"],
                        "evidence": list(state["evidence"].values()),
                        "suggestions": suggestions,
                        "review_draft": draft,
                        "metrics": {
                            **counts,
                            "db_pages": reader.page_reads,
                            "verified_suggestions": len(suggestions),
                            "unsupported_claims": 0,
                            "grounded_claim_rate": 1.0 if suggestions else None,
                            "business_writes": 0,
                            "permission_violations": 0,
                            "latency_ms": (time.perf_counter() - start) * 1000,
                        },
                        "limitations": [
                            "MOCK_TRANSPORT decisions do not establish real LLM capability",
                            "Observed bounded records only; see coverage before "
                            "interpreting counts",
                            "Read-only snapshot, not authorization or current-state guarantee",
                            "No durable merchant analysis history; disconnect cancels analysis",
                        ],
                    }
                    referenced = {s["evidence_key"] for s in suggestions}
                    if draft:
                        referenced.update(draft["evidence_keys"])
                    # Retain requested detail/policy facts even when no action is eligible.
                    referenced.update(
                        e["key"]
                        for e in state["evidence"].values()
                        if e["kind"] == "policy" or e["id"] == str(question.case_id)
                    )
                    if not referenced:
                        referenced.update(list(state["evidence"])[:20])
                    result["evidence"] = [
                        e for k, e in state["evidence"].items() if k in referenced
                    ]
                    eligible = sum(permitted(e) is not None for e in state["evidence"].values())
                    result["summary"].update(
                        eligible_todo_count=eligible,
                        shown_todo_count=len(suggestions),
                        advice_truncated=eligible > len(suggestions),
                    )
                    import json

                    if len(json.dumps(result, ensure_ascii=False).encode()) > 60000:
                        raise ValueError("RESULT_BOUND")
                    return {"result": result, "event": {"phase": "validate", "status": "COMPLETED"}}

                graph = StateGraph(State)
                for name, fn in [
                    ("plan", planning),
                    ("read", reading),
                    ("summarize", summarizing),
                    ("recommend", recommending),
                    ("validate", validating),
                ]:
                    graph.add_node(name, fn)

                def route(state):
                    return "read" if state["next"] < len(state["plan"].calls) else "summarize"

                graph.add_edge(START, "plan")
                graph.add_conditional_edges("plan", route)
                graph.add_conditional_edges("read", route)
                graph.add_edge("summarize", "recommend")
                graph.add_edge("recommend", "validate")
                graph.add_edge("validate", END)
                final = None
                async for update in graph.compile().astream(
                    {}, config={"recursion_limit": 20}, stream_mode="updates"
                ):
                    for value in update.values():
                        yield "progress", value["event"]
                        if "result" in value:
                            final = value["result"]
                yield "result", final
    except TimeoutError:
        raise DomainError(504, "COPILOT_TIMEOUT", "只读分析超时；未执行任何业务操作") from None
    except (ValueError, ValidationError):
        raise DomainError(
            422, "COPILOT_EVIDENCE_REJECTED", "模型工具或建议缺少合法证据，已拒绝"
        ) from None
    except DBAPIError:
        raise DomainError(503, "DATABASE_UNAVAILABLE", "读取失败，没有执行业务操作") from None
    except DomainError:
        raise
    except Exception:
        raise DomainError(503, "COPILOT_FAILED", "只读分析未完成；没有业务执行权限") from None
