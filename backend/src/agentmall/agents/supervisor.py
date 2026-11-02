"""The model chooses the next ready task batch; Python validates, never infers routing."""

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from agentmall.agents.budgets import RunStopped
from agentmall.agents.context import IntentPlan
from agentmall.agents.model_control import model_call, validate_wire
from agentmall.agents.runtime import fingerprint

SYSTEM_PROMPT = """你是AgentMall Supervisor。
使用route工具选择下一批就绪子任务，或terminal=clarify/finish。
目标只允许shopping/order/aftersales。依据原始用户目标动态决策，不需要每轮遍历所有专业Agent。
只读独立任务可同批；任何可写任务独占批次。depends_on只能引用已有done/proposal子任务。
route.tasks是本轮立即执行的就绪批次，不是完整待办计划。只要有read_only=false，本次数组长度必须为1。
depends_on不能把同批写任务变成串行；不能把未来步骤一并放入tasks。先返回一个写任务，等结果及用户决定后再安排下一步。
退货加替代购买：先解析原订单/SKU并核实资格和公开政策；单独准备退货提案并等待独立确认；再找排除原SKU的替代品、单独准备购买提案并再次等待确认。
每个subtask_id唯一。constraints必须原样复制输入中的canonical_constraints，不得丢预算、数量、噪声或排除条件。
product_needs保存配列、连接方式、键盘类型与用途，必须保留，不能以泛化关键词替代。
entity_refs/evidence_refs只能选择输入中已经核验的引用；Shopping只需商品引用，不能收到售后详情。
不同Agent的摘要不是授权。Order只准备购买提案，AfterSales只准备退货提案或受控人工工单。
提案、申请、商家审批、退款是不同状态；用户确认与执行经既有API完成，绝不由你代替。
推荐替代商品保留原order_id/product_id与policy_version在顶层状态，但只向Shopping传必要的排除ID。
原SKU条件在canonical_constraints已提供。只有明确购买意图和充分条件时才安排新的购买提案。
替代推荐必须先完成原订单与原SKU解析，不能与首次查原订单同批。售后写入必须交接已选定的订单引用。
用户只给出模糊的旧订单且有多个候选时先clarify，不能任挑一单。退货提案引用不得传入Order购买上下文。
某子任务失败时，可继续不依赖失败任务的独立需求；已经存在的提案不能重做。
缺少数量、地址或无法确定唯一原订单时terminal=clarify。完成或达到预算时terminal=finish。
不得读取内部客服信息；RAG只是背景，不能把有命中视为已有支持性证据。
只输出一次route工具调用，参数必须满足严格IntentPlan，不输出自由格式路由或未知模块名。"""


async def choose_plan(runtime):
    from agentmall.agents.context import THREAD_CONTEXT_PROMPT

    prompt = SYSTEM_PROMPT + (THREAD_CONTEXT_PROMPT if runtime.thread_snapshot else "")
    runtime.trace["prompts"]["supervisor"] = fingerprint(prompt)
    schema = convert_to_openai_tool(IntentPlan)
    schema["function"]["name"] = "route"
    bound = runtime.models["supervisor"].bind_tools([schema], tool_choice="route")
    feedback = None
    for attempt in range(2):
        content = {
            "user_goal": runtime.input.message,
            "canonical_constraints": runtime.handoff_constraints().model_dump(mode="json"),
            "entity_refs": [r.model_dump(mode="json") for r in runtime.references.values()],
            "evidence_refs": list(runtime.citations),
            "completed": [r.model_dump(mode="json") for r in runtime.completed.values()],
            "remaining_budget": runtime.budget.snapshot(),
            "prior_validation_error": runtime.errors[-1] if runtime.errors else None,
            "orchestration_feedback": feedback,
        }
        if runtime.thread_snapshot:
            content["thread_context"] = runtime.thread_snapshot
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=json.dumps(content, ensure_ascii=False)),
        ]

        async def invoke(cap, messages=messages):
            return await bound.ainvoke(messages, config={"callbacks": []}, max_tokens=cap)

        response = await model_call(runtime, "supervisor", invoke)
        try:
            validate_wire(response)
            if len(response.tool_calls) != 1 or response.tool_calls[0]["name"] != "route":
                raise ValueError("One route call required")
            call = response.tool_calls[0]
            plan = IntentPlan.model_validate(call["args"])
            # Pure preflight only: reject the whole batch, never rewrite model tasks.
            # Full authorization still runs in validate_tasks before any delegation.
            canonical = runtime.handoff_constraints()
            changed = sorted(
                {
                    field
                    for task in plan.tasks
                    for field in type(canonical).model_fields
                    if getattr(task.constraints, field) != getattr(canonical, field)
                }
            )
            code = None
            if len(plan.tasks) > 1 and any(not t.read_only for t in plan.tasks):
                code = "UNORDERED_WRITE_HANDOFF"
            elif changed:
                code = "HANDOFF_CONSTRAINT_CHANGED"
            if code:
                allowed = await runtime.budget.claim_repair(code, fields=changed)
                if not runtime.budget.persists_rejections:
                    runtime.event(
                        "orchestration_rejected",
                        role="supervisor",
                        error_code=code,
                        constraint_fields=changed,
                    )
                if attempt or not allowed:
                    raise RunStopped(code)
                feedback = {
                    "error_code": code,
                    "constraint_fields": changed,
                    "instruction": (
                        "整个批次未执行。仅返回一个就绪写任务；独立只读任务可另批执行。"
                        "重新生成完整TaskSpec，constraints逐字段原样复制当前输入的canonical_constraints。"
                        "不得删除用户要求或修改预算、数量、地址、原商品排除条件；保留已完成任务。"
                    ),
                }
                runtime.event("orchestration_repair", role="supervisor", error_code=code)
                continue
            runtime.event(
                "route_decision",
                tool_call_id=call["id"],
                validated_arguments=plan.model_dump(mode="json"),
            )
            return plan
        except (ValueError, ValidationError, RunStopped) as exc:
            if isinstance(exc, RunStopped) and exc.code in {
                "UNORDERED_WRITE_HANDOFF",
                "HANDOFF_CONSTRAINT_CHANGED",
            }:
                raise
            runtime.event("route_rejected", error_code="INVALID_ROUTE")
            if runtime.schema_repairs >= 1 or attempt:
                raise RunStopped("INVALID_ROUTE") from exc
            runtime.schema_repairs += 1
    raise RunStopped("INVALID_ROUTE")
