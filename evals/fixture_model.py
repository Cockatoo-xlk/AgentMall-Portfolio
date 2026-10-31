"""Disclosed scripted model outputs, shared domain program, no Oracle input.

This proves execution plumbing, not model decision quality. The live provider never uses it.
"""

import json

from agentmall.agents.specialist_tools import ALLOWLISTS
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import Field

from backend.tests.multiagent_helpers import MultiModel, ai, call, final, payload, route


class FixtureModel(MultiModel):
    single: bool = False
    unknown_usage: bool = False
    call_records: list = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):
        return "fixture-t12-program-v1"

    def bind_tools(self, tools, **kwargs):
        self.bound = [
            t["function"]["name"] if isinstance(t, dict) else t.name for t in tools
        ]
        permitted = (
            {"route"}
            if self.role == "supervisor"
            else {n for group in ALLOWLISTS.values() for n in group}
            if self.single
            else set(ALLOWLISTS[self.role])
        )
        if set(self.bound) != permitted:
            raise AssertionError("Fixture tool capability mismatch")
        return self.bind(**kwargs)

    async def _agenerate(self, messages, **kwargs):
        result = await super()._agenerate(messages, **kwargs)
        message = result.generations[0].message
        if self.unknown_usage:
            message.usage_metadata = None
            message.response_metadata["token_usage"] = {}
        self.call_records.append(
            {
                "role": "single" if self.single else self.role,
                "tool_names": [c["name"] for c in message.tool_calls],
                "usage": message.usage_metadata or "UNKNOWN",
                "usage_class": "SIMULATED_FIXTURE",
                "requested_max_output": kwargs["max_tokens"],
            }
        )
        return result


def choose_observed(messages):
    context = payload(messages)
    constraints = context["constraints"]
    candidates = []
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == "get_product":
            body = json.loads(message.content)
            if body.get("ok"):
                candidates.append(body["data"])
        if isinstance(message, ToolMessage) and message.name == "retrieve_products":
            result = json.loads(message.content)
            candidates = [
                row["product"] for row in result.get("data", {}).get("items", [])
            ]
            break
    if not candidates:
        candidates = [
            f["data"]
            for f in context.get("committed_facts", [])
            if f["kind"] == "product"
        ]
    quantity = constraints.get("quantity")
    maximum = constraints.get("max_price_cents")
    if candidates:
        suitable = [
            p
            for p in candidates
            if quantity and (maximum is None or quantity * p["price_cents"] <= maximum)
        ]
        return (
            ai(call("prepare_checkout", {"product_id": suitable[0]["id"]}))
            if suitable
            else final("无符合总预算的可购买候选。")
        )
    # Specialist gets only verified references from its supervisor, not the Oracle.
    selected = next(
        (
            r["id"]
            for r in context["entity_refs"]
            if r["kind"] == "product" and r["relation"] == "replacement"
        ),
        None,
    )
    return (
        ai(call("prepare_checkout", {"product_id": selected}))
        if selected
        else final("没有候选。")
    )


def inspect_candidates(messages):
    context = payload(messages)
    identifiers = [
        r["id"]
        for r in context["entity_refs"]
        if r["kind"] == "product" and r["relation"] == "replacement"
    ][:3]
    return (
        ai(*(call("get_product", {"product_id": ident}) for ident in identifiers))
        if identifiers
        else final("没有候选。")
    )


def fixture_models(program, goal, refs, fault):
    """Only public task instructions/resource aliases and the declared fault plan enter here."""
    query = (
        "鼠标"
        if "鼠标" in goal
        else "耳机"
        if "耳机" in goal
        else "静音键盘"
        if "静音" in goal
        else "键盘"
    )
    oid = refs.get("original_order")
    calls = {
        "products": lambda: ai(call("retrieve_products", {"query": query})),
        "orders": lambda: (
            ai(call("get_order", {"order_id": oid})) if oid else ai(call("list_orders"))
        ),
        "eligibility": lambda: ai(
            call("check_eligibility", {"order_id": oid, "reason_code": "QUALITY_ISSUE"})
        ),
        "policies": lambda: ai(
            call(
                "retrieve_policies",
                {
                    "order_id": oid,
                    "query": "内部客服政策" if "内部" in goal else "质量问题退货期限",
                },
            )
        ),
        "return": lambda: ai(
            call(
                "prepare_return",
                {
                    "order_id": oid,
                    "reason_code": "QUALITY_ISSUE",
                    "description": "合成商品按键故障",
                },
            )
        ),
        "ticket": lambda: ai(
            call(
                "create_support_ticket",
                {
                    "order_id": oid,
                    "reason": "EXPLANATION",
                    "summary": "合成用户要求人工解释售后规则",
                },
            )
        ),
        "checkout": lambda: choose_observed,
    }
    groups = []
    for stage in program:
        target = (
            "shopping"
            if stage == "products"
            else "order"
            if stage == "checkout"
            or (stage == "orders" and "eligibility" not in program)
            else "aftersales"
        )
        if stage == "clarify":
            groups.append(("clarify", [stage]))
        elif (
            groups
            and groups[-1][0] == target
            and groups[-1][1][-1] not in {"return", "checkout", "ticket"}
        ):
            groups[-1][1].append(stage)
        else:
            groups.append((target, [stage]))

    def script(stages, *, finish=True):
        steps, reads = [], []
        for stage in stages:
            step = calls[stage]()
            if stage in {"return", "checkout", "ticket"}:
                if reads:
                    steps.append(ai(*reads))
                    reads = []
                steps.append(step)
            else:
                reads.extend(step.tool_calls)
                if len(reads) == 4:
                    steps.append(ai(*reads))
                    reads = []
        if reads:
            steps.append(ai(*reads))
        if finish and stages[-1] not in {"return", "checkout", "ticket"}:
            steps.append(final())
        return steps

    scripts = {role: [] for role in ("supervisor", "shopping", "order", "aftersales")}
    single_steps = []
    for index, (role, stages) in enumerate(groups):
        if role == "clarify":
            scripts["supervisor"].append(route("clarify"))
            single_steps.append(final("请补充明确的数量、预算和演示地址"))
            continue
        end = stages[-1]
        target_goal = {
            "shopping": "find_products",
            "order": "prepare_checkout" if end == "checkout" else "inspect_orders",
            "aftersales": "prepare_return"
            if end == "return"
            else "human_support"
            if end == "ticket"
            else "assess_return",
        }[role]
        scripts["supervisor"].append(
            route(
                role,
                target_goal,
                f"stage_{index}",
                read_only=end not in {"checkout", "return", "ticket"},
            )
        )
        steps = script(stages)
        if stages == ["checkout"]:
            steps = [inspect_candidates, choose_observed]
        scripts[role].extend(steps)
        # Inner single loops keep reading until a write/terminal, no invented supervisor calls.
        single_steps.extend(script(stages, finish=False))
    scripts["supervisor"].append(route("finish"))
    single_steps.append(final())

    def inject(steps):
        if fault == "provider_error":
            return [RuntimeError("Synthetic provider transport failure")]
        if fault == "budget_exhaustion":
            return [
                ai(call("retrieve_products", {"query": query + f" 条件{i}"}))
                for i in range(20)
            ]
        if fault in {"unknown_tool", "forged_refund"}:
            return [
                ai(
                    call(
                        "refund" if fault == "forged_refund" else "unavailable_tool",
                        {"amount_cents": 1},
                    )
                )
            ]
        if fault in {
            "invalid_schema",
            "forged_approval",
            "forged_actor",
            "forged_store",
        }:
            first = next(
                (s for s in steps if isinstance(s, AIMessage) and s.tool_calls), None
            )
            if first:
                damaged = first.model_copy(deep=True)
                field = {
                    "invalid_schema": "extra",
                    "forged_approval": "approved",
                    "forged_actor": "actor_id",
                    "forged_store": "store_id",
                }[fault]
                damaged.tool_calls[0]["args"][field] = (
                    True if field == "approved" else "forged"
                )
                return [damaged]
        return steps

    if fault == "replacement_failure":
        scripts["shopping"] = [
            RuntimeError("Synthetic replacement recommendation failure")
        ]
        for index, step in enumerate(single_steps):
            if isinstance(step, AIMessage) and any(
                c["name"] == "retrieve_products" for c in step.tool_calls
            ):
                single_steps[index:] = [
                    RuntimeError("Synthetic replacement recommendation failure")
                ]
                break
    elif fault in {
        "provider_error",
        "budget_exhaustion",
        "unknown_tool",
        "forged_refund",
        "invalid_schema",
        "forged_approval",
        "forged_actor",
        "forged_store",
    }:
        single_steps = inject(single_steps)
        first_role = next(role for role, _ in groups if role != "clarify")
        scripts[first_role] = inject(scripts[first_role])
        scripts["supervisor"] = [scripts["supervisor"][0], route("finish")]
    models = {
        role: FixtureModel(
            role=role,
            script=steps,
            unknown_usage=fault == "unknown_usage" and role != "supervisor",
        )
        for role, steps in scripts.items()
    }
    single = FixtureModel(
        role="order",
        single=True,
        script=single_steps,
        unknown_usage=fault == "unknown_usage",
    )
    return single, models
