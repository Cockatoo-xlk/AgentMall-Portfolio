import asyncio
import hashlib
import json
import re

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langsmith import tracing_context
from pydantic import ValidationError

from agentmall.agents.prompts import SYSTEM_PROMPT
from agentmall.agents.schemas import TOOL_SCHEMAS, AgentResponse, ResourceRef
from agentmall.agents.tools import ToolContext, build_tools
from agentmall.identity.service import require_buyer
from agentmall.infra.llm import AgentStopped, Budget


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class Guard(AgentMiddleware):
    def __init__(self, budget, trace):
        self.budget, self.trace = budget, trace
        self.ids = set()

    async def awrap_model_call(self, request, handler):
        self.budget.start()
        async with asyncio.timeout(35):
            result = await handler(request)
        messages = [m for m in result.result if isinstance(m, AIMessage)]
        if len(messages) != 1:
            raise AgentStopped("MODEL_PROTOCOL_ERROR")
        self.budget.finish(messages[0])
        return result

    async def aafter_model(self, state, runtime):
        message = state["messages"][-1]
        calls = message.tool_calls
        if message.invalid_tool_calls:
            raise AgentStopped("INVALID_TOOL_BATCH")
        if len(calls) > 4 or len(self.ids) + len(calls) > 16:
            raise AgentStopped("TOOL_BUDGET_EXHAUSTED")
        if len(calls) > 1 and any(c["name"] == "prepare_checkout" for c in calls):
            raise AgentStopped("UNORDERED_WRITE_BATCH")
        try:
            for raw in message.additional_kwargs.get("tool_calls", []):
                json.loads(raw["function"]["arguments"], object_pairs_hook=unique_object)
            new_ids = set()
            for call in calls:
                ident = call["id"]
                if (
                    not isinstance(ident, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ident)
                    or ident in self.ids
                    or ident in new_ids
                ):
                    raise ValueError("Invalid call identity")
                TOOL_SCHEMAS[call["name"]].model_validate(call["args"])
                new_ids.add(ident)
        except (KeyError, ValueError, TypeError, ValidationError) as exc:
            raise AgentStopped("INVALID_TOOL_BATCH") from exc
        self.ids.update(new_ids)
        if not calls:
            if not isinstance(message.content, str) or not message.content.strip():
                raise AgentStopped("MODEL_FINAL_EMPTY")
            self.trace["model_final_received"] = True
            self.trace["model_final_sha256"] = hashlib.sha256(message.content.encode()).hexdigest()
            self.trace["model_final_length"] = len(message.content)
        return None

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        body = json.loads(result.content)
        args = (
            TOOL_SCHEMAS[request.tool_call["name"]]
            .model_validate(request.tool_call["args"])
            .model_dump(mode="json")
        )
        if args.get("query") is not None:
            args["query_sha256"] = hashlib.sha256(args.pop("query").encode()).hexdigest()
        self.trace.setdefault("tools", []).append(
            {
                "tool_call_id": request.tool_call["id"],
                "name": request.tool_call["name"],
                "validated_arguments": args,
                "ok": body.get("ok", False),
                "error_code": body.get("error_code"),
                "proposal_id": body.get("proposal_id"),
                "product_ids": [i["id"] for i in body.get("items", [])]
                if "items" in body
                else ([body["id"]] if "id" in body else []),
            }
        )
        self.budget.save()
        return result


def proposal_response(proposal):
    payload = proposal.canonical_payload
    summary = "；".join(
        f"{i['name_snapshot']} × {i['quantity']}，单价{i['unit_price_cents']}分"
        for i in payload["items"]
    )
    refs = [ResourceRef(type="product", id=i["product_id"]) for i in payload["items"]]
    status = "proposal"
    if proposal.result:
        state = f"已有订单 {proposal.result.order_id}，状态 {proposal.result.status}"
        refs.append(ResourceRef(type="order", id=proposal.result.order_id))
        status = "done"
    elif proposal.status in {"REJECTED", "EXPIRED"}:
        state = "提案已拒绝或过期；如需购买请发起新请求"
        status = "blocked"
    elif proposal.status == "APPROVED":
        state = "已记录用户确认，尚无订单回执；请通过订单接口核对或执行"
    else:
        state = "等待用户通过确认接口确认；尚未下单"
    return AgentResponse(
        answer=f"{summary}。合计{payload['total_cents']}分。{state}。",
        proposal_refs=[proposal.proposal_id],
        resource_refs=refs,
        status=status,
    )


async def run_single_agent(
    actor, request_id, message, *, sessions, model=None, budget=None, trace=None
):
    require_buyer(actor)
    context = ToolContext(actor, request_id, sessions)
    if proposal := await context.recover():
        return proposal_response(proposal)
    if model is None:
        return AgentResponse(answer="模型未启用，尚未创建提案或订单。", status="blocked")
    budget = budget or Budget()
    trace = trace if trace is not None else {}
    guard = Guard(budget, trace)
    agent = create_agent(
        model, build_tools(context), system_prompt=SYSTEM_PROMPT, middleware=[guard]
    )
    error = None
    try:
        # Never export user messages/tool results to LangSmith, even if globally enabled.
        with tracing_context(enabled=False):
            async with asyncio.timeout(180):
                await agent.ainvoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config={"recursion_limit": 40, "callbacks": []},
                )
    except AgentStopped as exc:
        error = exc.code
    except TimeoutError:
        error = "PROVIDER_TIMEOUT"
    except Exception:
        error = "AGENT_UNAVAILABLE"  # Never serialize exception strings/provider response bodies.
    trace["error_code"] = error
    budget.save()
    # A provider failure cannot erase a committed proposal, including uncertain commit outcomes.
    if proposal := await context.recover():
        return proposal_response(proposal)
    if error:
        return AgentResponse(
            answer="本次处理未完成，未查询到购买提案。请核对后重试。",
            status="blocked" if "BUDGET" in error or "USAGE" in error else "error",
        )
    if context.tool_errors:
        return AgentResponse(
            answer="商品查询或提案准备未完成，请重新核对价格、库存和提案；尚未查询到购买提案。",
            status="error",
        )
    if context.observed:
        facts = "；".join(
            f"{p.name}（{p.id}）：{p.price_cents}分，可用{p.available}"
            for p in context.observed.values()
        )
        return AgentResponse(
            answer=f"已查询：{facts}。请明确选择商品、数量和演示地址；尚未创建提案或订单。",
            resource_refs=[ResourceRef(type="product", id=i) for i in context.observed],
            status="needs_input",
        )
    return AgentResponse(
        answer="请提供商品需求、数量和演示地址；尚未创建提案或订单。", status="needs_input"
    )
