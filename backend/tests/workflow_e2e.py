"""Test-only fixture decisions; real LangGraph, tools, Domain Services and Checkpoint."""

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from multiagent_helpers import ai, call, choose_purchase, payload, route

from agentmall.agents.specialist_tools import ALLOWLISTS, SCHEMAS


def models(mode, boundary):
    if mode == "disabled":
        return None

    class WorkflowFixture(BaseChatModel):
        role: str

        @property
        def _llm_type(self):
            return "offline-t10-fixture"

        def bind_tools(self, tools, **kwargs):
            names = {t["function"]["name"] if isinstance(t, dict) else t.name for t in tools}
            assert names == (
                {"route"}
                if self.role == "supervisor"
                else set(SCHEMAS)
                if self.role == "single"
                else set(ALLOWLISTS[self.role])
            )
            return self.bind(**kwargs)

        def _generate(self, *args, **kwargs):
            raise AssertionError("async only")

        async def _agenerate(self, messages, **kwargs):
            boundary.fake_model_calls += 1
            data = payload(messages)
            constraints = data.get("canonical_constraints", data.get("constraints", {}))
            tools = [m for m in messages if isinstance(m, ToolMessage)]
            names = [m.name for m in tools]
            order = next(
                (
                    r["id"]
                    for r in data.get("entity_refs", [])
                    if r["kind"] == "order" and r["relation"] == "original"
                ),
                None,
            )
            response = AIMessage(content="Fixture 专业任务结束。")
            if self.role == "supervisor":
                completed = {r["subtask_id"] for r in data["completed"]}
                if mode == "clarify" and (
                    not constraints["quantity"] or not constraints["address_label"]
                ):
                    response = route("clarify")(messages)
                elif constraints["support_requested"] and "human" not in completed:
                    response = route("aftersales", "human_support", "human", read_only=False)(
                        messages
                    )
                elif constraints["return_requested"] and "return" not in completed:
                    response = route("aftersales", "prepare_return", "return", read_only=False)(
                        messages
                    )
                elif not constraints["support_requested"] and "shop" not in completed:
                    response = route("shopping", "find_products", "shop")(messages)
                elif constraints["purchase_requested"] and "buy" not in completed:
                    response = route(
                        "order", "prepare_checkout", "buy", depends=["shop"], read_only=False
                    )(messages)
                else:
                    response = route("finish")(messages)
            elif self.role == "shopping":
                if mode == "return_partial" and constraints["return_requested"]:
                    raise TimeoutError("fixture recommendation failure")
                if not tools:
                    response = ai(call("retrieve_products", {"query": "静音键盘"}))
            elif self.role == "order":
                if not tools:
                    response = choose_purchase(messages)
            elif self.role == "single":
                if not tools:
                    response = ai(call("retrieve_products", {"query": "静音键盘"}))
                elif constraints["purchase_requested"] and "prepare_checkout" not in names:
                    body = json.loads(tools[-1].content)
                    response = ai(
                        call("prepare_checkout", {"product_id": body["data"]["items"][0]["id"]})
                    )
            elif self.role == "aftersales":
                if data["goal"] == "human_support" and not tools:
                    response = ai(
                        call(
                            "create_support_ticket",
                            {
                                "order_id": order,
                                "reason": "POLICY_DISPUTE",
                                "summary": "Fixture 人工核对",
                            },
                        )
                    )
                elif data["goal"] == "prepare_return":
                    if not tools:
                        response = ai(
                            call(
                                "check_eligibility",
                                {"order_id": order, "reason_code": "QUALITY_ISSUE"},
                            ),
                            call(
                                "retrieve_policies",
                                {"order_id": order, "query": "质量问题退货期限"},
                            ),
                        )
                    elif "prepare_return" not in names:
                        response = ai(
                            call(
                                "prepare_return",
                                {
                                    "order_id": order,
                                    "reason_code": "QUALITY_ISSUE",
                                    "description": "Fixture 按键故障",
                                },
                            )
                        )
            # First supervisor call deliberately has unknown usage; retain its reservation.
            if self.role != "supervisor" or data.get("completed"):
                response.usage_metadata = {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                }
            return ChatResult(generations=[ChatGeneration(message=response)])

    return {
        role: WorkflowFixture(role=role)
        for role in ("supervisor", "shopping", "order", "aftersales", "single")
    }


async def graph_facts(harness):
    from sqlalchemy import text

    from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

    with harness.db.connect() as connection:
        runs = list(connection.execute(text("SELECT id, thread_id FROM agent_runs")).mappings())
    results = []
    async with checkpoint_saver(harness.settings) as saver:
        for run in runs:
            checkpoint = await saver.aget_tuple(checkpoint_config(run["thread_id"], run["id"]))
            if checkpoint:
                values = checkpoint.checkpoint["channel_values"]
                results.append(
                    {
                        "run_id": str(run["id"]),
                        "checkpoint_id": checkpoint.checkpoint["id"],
                        "graph": {
                            key: values.get(key)
                            for key in ("round", "next", "handled", "pending_action")
                        },
                        "pending_writes": len(checkpoint.pending_writes or []),
                    }
                )
    return results
