"""The model chooses the next ready task batch; Python validates, never infers routing."""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from agentmall.agents.budgets import RunStopped
from agentmall.agents.context import IntentPlan, asks_return_policy
from agentmall.agents.model_control import model_call, validate_wire
from agentmall.agents.runtime import fingerprint
from agentmall.agents.specialist_tools import WRITE_TOOLS_BY_GOAL

SYSTEM_PROMPT = """你是AgentMall Supervisor。
使用route工具选择下一批就绪子任务，或terminal=clarify/finish。
目标只允许shopping/order/aftersales。依据原始用户目标动态决策，不需要每轮遍历所有专业Agent。
只读独立任务可同批；任何可写任务独占批次。depends_on只能引用已有done/proposal子任务。
route.tasks是本轮立即执行的就绪批次，不是完整待办计划。只要有read_only=false，本次数组长度必须为1。
depends_on不能把同批写任务变成串行；不能把未来步骤一并放入tasks。先返回一个写任务，等结果及用户决定后再安排下一步。
仅政策查询安排只读资格与政策核验。仅推荐安排Shopping，不安排购买。
退货加替代推荐：解析原订单/SKU并核实资格与公开政策，退货提案独立确认后推荐排除原SKU的商品。
只有canonical_constraints.purchase_requested为true且checkout_blocker为空时，才安排独立购买提案并再次等待确认。
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


def unfinished_goal(runtime, user_goal):
    # Check known user goals against verified outcomes. Preserve genuine failures.
    if runtime.errors or any(
        result.status in {"error", "blocked", "needs_input"} or result.error_code
        for result in runtime.completed.values()
    ):
        return None
    actions = {
        value["action_type"]
        for (kind, _), value in runtime.facts.items()
        if kind == "proposal" and value["status"] in {"PENDING", "APPROVED", "EXECUTED", "REJECTED"}
    }
    if runtime.constraints.return_requested and "RETURN_REQUEST" not in actions:
        return "RETURN_GOAL_UNRESOLVED"
    if runtime.constraints.purchase_requested and "CHECKOUT" not in actions:
        return runtime.checkout_blocker() or "PURCHASE_GOAL_UNRESOLVED"
    if asks_return_policy(user_goal) and not (
        runtime.citations and any(kind == "eligibility" for kind, _ in runtime.facts)
    ):
        return "POLICY_GOAL_UNRESOLVED"
    if runtime.constraints.bundle:
        return (
            None
            if runtime.facts.get(("bundle_status", "current"), {}).get("status")
            in {"READY", "NO_FEASIBLE_BUNDLE"}
            or runtime.thread_snapshot.get("selected_bundle")
            else "BUNDLE_GOAL_UNRESOLVED"
        )
    recommendation = r"推荐(?!的)|找(?:个|一款)?替代(?:品|商品)"
    goal = re.sub(
        r"(?:不要|别|无需|不必|不用)(?:再|帮我)*\s*(?:" + recommendation + ")", "", user_goal
    )
    revoked = runtime.input.message != user_goal and re.search(
        r"(?:不要|不用|不必|无需|别)(?:再|帮我)*\s*推荐", runtime.input.message
    )
    if (
        not revoked
        and re.search(recommendation, goal)
        and not any(
            result.target == "shopping"
            and result.status == "done"
            and any(
                entity.kind == "product"
                and entity.id not in runtime.exclusions
                and ("product", str(entity.id)) in runtime.facts
                for entity in result.entity_refs
            )
            for result in runtime.completed.values()
        )
    ):
        return "RECOMMENDATION_GOAL_UNRESOLVED"
    return None


def awaits_return_decision(runtime, tasks):
    if not runtime.constraints.return_requested or any(
        kind == "proposal"
        and fact["action_type"] == "RETURN_REQUEST"
        and fact["status"] in {"EXECUTED", "REJECTED", "EXPIRED"}
        for (kind, _), fact in runtime.facts.items()
    ):
        return False
    if any(task.goal == "prepare_checkout" for task in tasks):
        return True
    return (
        runtime.constraints.exclude_original
        and any(task.goal == "find_products" for task in tasks)
        and not any(
            result.target == "aftersales" and result.error_code
            for result in runtime.completed.values()
        )
    )


async def choose_plan(runtime, user_goal=None, *, durable=False):
    from agentmall.agents.context import THREAD_CONTEXT_PROMPT

    prompt = SYSTEM_PROMPT + (THREAD_CONTEXT_PROMPT if runtime.thread_snapshot else "")
    runtime.trace["prompts"]["supervisor"] = fingerprint(prompt)
    schema = convert_to_openai_tool(IntentPlan)
    schema["function"]["name"] = "route"
    bound = runtime.models["supervisor"].bind_tools([schema], tool_choice="route")
    checkout_blocker = runtime.checkout_blocker()
    feedback = None
    for attempt in range(2):
        content = {
            "user_goal": user_goal or runtime.input.message,
            "checkout_blocker": checkout_blocker,
            "checkout_product_id": runtime.purchase_target_id,
            "canonical_constraints": runtime.handoff_constraints().model_dump(mode="json"),
            "entity_refs": [r.model_dump(mode="json") for r in runtime.references.values()],
            "evidence_refs": list(runtime.citations),
            "completed": [r.model_dump(mode="json") for r in runtime.completed.values()],
            "remaining_budget": runtime.budget.snapshot(),
            "prior_validation_error": runtime.errors[-1] if runtime.errors else None,
            "orchestration_feedback": feedback,
        }
        if user_goal and user_goal != runtime.input.message:
            content["clarification"] = runtime.input.message
        if runtime.constraints.bundle:
            content["bundle_progress"] = {
                "composition": runtime.facts.get(("bundle_status", "current"))
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
            elif any(
                not task.read_only and task.goal not in WRITE_TOOLS_BY_GOAL for task in plan.tasks
            ):
                code = "HANDOFF_WRITE_SCOPE_CHANGED"
            elif not runtime.constraints.return_requested and any(
                task.goal == "prepare_return" for task in plan.tasks
            ):
                code = "RETURN_NOT_REQUESTED"
            elif checkout_blocker == "PURCHASE_NOT_REQUESTED" and any(
                task.goal == "prepare_checkout" for task in plan.tasks
            ):
                code = checkout_blocker
            elif durable and awaits_return_decision(runtime, plan.tasks):
                code = "RETURN_DECISION_REQUIRED"
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
                        "只读目标必须标记read_only=true。未请求购买或退货时移除相应写任务。"
                        "组合退货任务中，先处理退货及其独立确认，再安排替代任务。"
                    ),
                }
                runtime.event("orchestration_repair", role="supervisor", error_code=code)
                continue
            clarification = None
            if checkout_blocker and any(task.goal == "prepare_checkout" for task in plan.tasks):
                clarification = checkout_blocker
            elif plan.terminal == "finish":
                clarification = unfinished_goal(runtime, user_goal or runtime.input.message)
            if clarification:
                runtime.event("route_clarification_required", error_code=clarification)
                plan = IntentPlan(terminal="clarify")
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
                "PURCHASE_NOT_REQUESTED",
                "RETURN_DECISION_REQUIRED",
                "HANDOFF_WRITE_SCOPE_CHANGED",
                "RETURN_NOT_REQUESTED",
            }:
                raise
            runtime.event("route_rejected", error_code="INVALID_ROUTE")
            if runtime.schema_repairs >= 1 or attempt:
                raise RunStopped("INVALID_ROUTE") from exc
            runtime.schema_repairs += 1
    raise RunStopped("INVALID_ROUTE")
