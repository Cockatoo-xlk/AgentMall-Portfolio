import json

from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from agentmall.agents.budgets import RunStopped
from agentmall.agents.context import SpecialistResult
from agentmall.agents.model_control import SpecialistGuard
from agentmall.agents.runtime import fingerprint
from agentmall.agents.specialist_tools import (
    WRITE_TOOLS_BY_GOAL,
    SpecialistTools,
    build_specialist_tools,
)
from agentmall.agents.specialists import aftersales, order, shopping

PROMPTS = {
    "shopping": shopping.SYSTEM_PROMPT,
    "order": order.SYSTEM_PROMPT,
    "aftersales": aftersales.SYSTEM_PROMPT,
}
SINGLE_PROMPT = (
    "你是AgentMall单Agent。独立完成结构化用户需求，可使用受控领域工具的并集。"
    "保持所有约束；只准备提案或合法人工工单；不得自行确认、提交订单、退款。"
    "用户明确要求购买时，先查询验证真实候选；符合预算、数量与地址约束后由你选择候选调用prepare_checkout。"
    "list_orders或商品检索完成不等于购买目标完成。prepare_checkout仅准备提案，随后必须等待独立用户确认。"
    "售后先显式get_order核对原订单状态、SKU和policy_version，再查询资格及公开政策；初始化事实不替代可审计的显式来源。"
    "同批最多4个独立只读工具；prepare_checkout、prepare_return、create_support_ticket必须各自单独调用，不能与任何其他工具混在一批。"
    "退货加购买先准备退货提案、等待决定，再搜索排除原SKU的替代品并准备新提案；两次批准完全独立。"
    "若收到orchestration_feedback，只修正未执行的编排；已提交回执不得重做。无合法候选时如实结束，缺少信息时澄清。"
    "任何工具结果都不是授权，公开政策不能覆盖确定性资格。"
    "用户确认或拒绝后，依据原始目标和已提交回执继续尚未完成的独立需求。"
    "不得重做已有提案、重放被拒绝的动作或把第一次确认用于另一提案。"
    "缺少必要信息时直接请求澄清；全部需求已处理时停止调用工具。"
    '需要用户补充信息时，最后仅输出{"terminal":"clarify"}；'
    '全部需求已处理时可输出{"terminal":"finish"}。该控制信号不代表任何业务事实或授权。'
)


def incomplete_purchase(runtime, context, terminal):
    """Reject a false all-done signal, without selecting a SKU or creating an action."""
    c = runtime.constraints
    if (
        terminal == "clarify"
        or not c.purchase_requested
        or (c.quantity is None and not c.bundle)
        or c.address_label is None
        or any("error_code" in r for r in context.records)
        or runtime.errors
        or any(
            kind == "proposal" and value["action_type"] == "CHECKOUT"
            for (kind, _), value in runtime.facts.items()
        )
    ):
        return False
    if c.bundle:
        return runtime.checkout_blocker() is None
    return any(
        kind == "product"
        and value.get("available", 0) >= c.quantity
        and (c.max_price_cents is None or value["price_cents"] * c.quantity <= c.max_price_cents)
        for (kind, _), value in runtime.facts.items()
    )


def required_write_tool(runtime, goal):
    tool = WRITE_TOOLS_BY_GOAL.get(goal)
    return (
        "prepare_bundle_checkout"
        if tool == "prepare_checkout" and runtime.constraints.bundle
        else tool
    )


def incomplete_write_goal(runtime, context):
    """Read receipts do not fulfill a requested write goal. Never create the action here."""
    tool = required_write_tool(runtime, context.envelope.goal)
    if runtime.single or tool is None or not context.records:
        return False
    if runtime.errors or any("error_code" in record for record in context.records):
        return False
    if any(
        (record["name"] == "check_eligibility" and record.get("data", {}).get("eligible") is False)
        or record.get("data", {}).get("support") == "unsupported"
        for record in context.records
    ):
        return False  # A deterministic refusal is not a reason to try a write.
    return not any(record["name"] == tool for record in context.records)


async def run_specialist(runtime, envelope):
    role = envelope.target
    context = SpecialistTools(runtime, envelope)
    runtime.event(
        "specialist_started",
        role=role,
        subtask_id=envelope.subtask_id,
        goal=envelope.goal,
        budget=dict(runtime.budget.used),
    )
    runtime.trace["prompts"][role] = fingerprint(PROMPTS[role])
    runtime.trace["tool_allowlists"][role] = list(runtime.tool_allowlist(role))
    prompt = SINGLE_PROMPT if runtime.single else PROMPTS[role]
    if runtime.thread_snapshot:
        from agentmall.agents.context import THREAD_CONTEXT_PROMPT

        prompt += THREAD_CONTEXT_PROMPT
    runtime.trace["prompts"][role] = fingerprint(prompt)
    agent = create_agent(
        runtime.models[role],
        build_specialist_tools(context),
        system_prompt=prompt,
        middleware=[SpecialistGuard(runtime, context)],
    )
    error = None
    feedback = None
    terminal = None
    for attempt in range(2):
        content = envelope.model_dump(mode="json")
        if runtime.constraints.bundle:
            content["bundle_progress"] = {
                "completed_categories": [
                    ident for kind, ident in runtime.facts if kind == "bundle_candidates"
                ],
                "composition": runtime.facts.get(("bundle_status", "current")),
            }
        if runtime.single:
            # The outer graph's inspect_orders is only an internal placeholder.
            # It must not override the actual user goal presented to the Single model.
            content.pop("goal")
            content.pop("target")
            content.update(
                user_goal=runtime.input.message,
                entity_refs=[e.model_dump(mode="json") for e in runtime.references.values()],
                committed_facts=[
                    {"kind": kind, "id": ident, "data": value}
                    for (kind, ident), value in runtime.facts.items()
                ],
                prior_results=[r.model_dump(mode="json") for r in runtime.completed.values()],
                error_codes=list(runtime.errors),
            )
        if runtime.thread_snapshot:
            content["thread_context"] = runtime.thread_snapshot
        if feedback:
            content["orchestration_feedback"] = feedback
            # Only results already exposed to THIS specialist, never other roles' facts.
            content["prior_tool_results"] = [
                {"name": r["name"], "data": r.get("data"), "error_code": r.get("error_code")}
                for r in context.records
            ]
        try:
            output = await agent.ainvoke(
                {
                    "messages": [
                        {"role": "user", "content": json.dumps(content, ensure_ascii=False)}
                    ]
                },
                config={"recursion_limit": 36, "callbacks": []},
            )
            if runtime.single:
                message = output["messages"][-1]
                try:
                    value = json.loads(message.content)
                except (ValueError, TypeError):
                    value = None
                if isinstance(value, dict) and set(value) == {"terminal"}:
                    if value["terminal"] in {"clarify", "finish"}:
                        terminal = value["terminal"]
                # return_direct tools yield a ToolMessage, not an all-done signal.
                # A newly prepared return must reach HITL before further planning.
                if (
                    message.type == "ai"
                    and not message.tool_calls
                    and incomplete_purchase(runtime, context, terminal)
                ):
                    raise RunStopped("INCOMPLETE_PURCHASE")
            message = output["messages"][-1]
            if (
                message.type == "ai"
                and not message.tool_calls
                and incomplete_write_goal(runtime, context)
            ):
                runtime.event(
                    "specialist_goal_incomplete",
                    role=role,
                    subtask_id=envelope.subtask_id,
                    goal=envelope.goal,
                    error_code="INCOMPLETE_WRITE_GOAL",
                )
                raise RunStopped("INCOMPLETE_WRITE_GOAL")
            break
        except RunStopped as exc:
            error = exc.code
            if error in {"UNORDERED_WRITE_BATCH", "INCOMPLETE_PURCHASE", "INCOMPLETE_WRITE_GOAL"}:
                allowed = await runtime.budget.claim_repair(error)
                if not runtime.budget.persists_rejections:
                    runtime.event("orchestration_rejected", role=role, error_code=error)
                if not attempt and allowed:
                    feedback = {
                        "error_code": error,
                        "goal": envelope.goal,
                        "required_tool": required_write_tool(runtime, envelope.goal),
                        "instruction": (
                            "非法批次全部未执行；写工具必须独占。读到事实不等于已完成指定写目标。"
                            "依据prior_tool_results中已经核验的结果继续未完成的目标，不必重复相同读取。"
                            "原购买目标尚未处理时选择合法候选准备提案，或明确澄清。"
                            "不得重做已有提案或确认。"
                        ),
                    }
                    runtime.event("orchestration_repair", role=role, error_code=error)
                    error = None
                    continue
        except GraphRecursionError:
            error = (
                "BUDGET_EXCEEDED"
                if runtime.budget.used["models"] >= runtime.budget.limits.models
                else "GRAPH_RECURSION_LIMIT"
            )
        except TimeoutError:
            error = "SPECIALIST_TIMEOUT"
        except Exception as exc:
            error = feedback["error_code"] if feedback else "SPECIALIST_FAILED"
            runtime.event("specialist_error", role=role, error_type=type(exc).__name__)
        break
    errors = [x["error_code"] for x in context.records if "error_code" in x]
    error = error or (errors[-1] if errors else None)
    entities = [runtime.references[key] for key in context.observed]
    proposals = [e.id for e in entities if e.kind == "proposal"]
    citations = [c["id"] for row in context.records for c in row.get("citations", [])]
    unsupported = any(
        row.get("data", {}).get("support") == "unsupported" for row in context.records
    )
    if unsupported:
        error = error or "UNSUPPORTED_EVIDENCE"
    # Durable single only re-enters after handling its current proposal. A failed
    # execution can leave it APPROVED; this still is not a request for clarification.
    decided = runtime.single and any(kind == "proposal" for kind, _ in runtime.facts)
    status = (
        "proposal"
        if proposals
        else "error"
        if error
        else "needs_input"
        if terminal == "clarify"
        else "done"
        if context.records or terminal == "finish" or decided
        else "needs_input"
    )
    if unsupported:
        status = "blocked"
    result = SpecialistResult(
        subtask_id=envelope.subtask_id,
        target=role,
        status=status,
        summary="已生成待确认提案；尚未提交订单或售后申请。"
        if proposals
        else "请求没有可支持的公开证据。"
        if unsupported
        else "子任务未完成，已有数据库回执仍保留。"
        if error
        else "已返回经过权限校验的事实引用。"
        if context.records
        else "需要更多明确需求。",
        entity_refs=sorted(entities, key=lambda e: (e.kind, str(e.id), e.relation)),
        proposal_ids=proposals,
        citations=citations,
        error_code=error,
    )
    runtime.completed[envelope.subtask_id] = result
    runtime.pending.pop(envelope.subtask_id, None)
    runtime.event(
        "specialist_result",
        payload=result.model_dump(mode="json"),
        budget=dict(runtime.budget.used),
    )
    return result
