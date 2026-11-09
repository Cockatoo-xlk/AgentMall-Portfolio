"""Scripted decisions drive the real create_agent and StateGraph execution paths."""

import inspect
import json
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from agentmall.agents.specialist_tools import ALLOWLISTS


class MultiModel(BaseChatModel):
    role: str
    script: list = Field(default_factory=list, exclude=True)
    seen: list = Field(default_factory=list, exclude=True)
    bound: list = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):
        return "offline-multi-script"

    def bind_tools(self, tools, **kwargs):
        self.bound = [t["function"]["name"] if isinstance(t, dict) else t.name for t in tools]
        from agentmall.agents.specialist_tools import WRITE_TOOLS_BY_GOAL, WRITES

        if self.role == "supervisor":
            variants = [{"route"}]
        else:
            reads = set(ALLOWLISTS[self.role]) - WRITES
            variants = [reads] + [
                reads | {name}
                for name in WRITE_TOOLS_BY_GOAL.values()
                if name in ALLOWLISTS[self.role]
            ]
        assert set(self.bound) in variants
        return self.bind(**kwargs)

    def _generate(self, *args, **kwargs):
        raise AssertionError("async only")

    async def _agenerate(self, messages, **kwargs):
        self.seen.append(messages)
        assert 0 < kwargs["max_tokens"] <= 2048
        if not self.script:
            raise RuntimeError("fixture script exhausted")
        step = self.script.pop(0)
        if callable(step):
            step = step(messages)
        if inspect.isawaitable(step):
            step = await step
        if isinstance(step, Exception):
            raise step
        if step.usage_metadata is None:
            step.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        return ChatResult(generations=[ChatGeneration(message=step)])


def call(name, args=None, ident=None):
    return {
        "name": name,
        "args": args or {},
        "id": ident or "call_" + uuid4().hex,
        "type": "tool_call",
    }


def ai(*calls):
    return AIMessage(content="", tool_calls=list(calls))


def final(text="完成"):
    return AIMessage(content=text)


def payload(messages):
    return json.loads(next(m.content for m in reversed(messages) if isinstance(m, HumanMessage)))


def route(target=None, goal=None, subtask="task", *, depends=(), read_only=True, change=None):
    def decision(messages):
        state = payload(messages)
        if target in {"finish", "clarify"}:
            return ai(call("route", {"tasks": [], "terminal": target}))
        kinds = {
            "shopping": {"product"},
            "order": {"product", "order", "proposal"},
            "aftersales": {"product", "order", "proposal", "case", "ticket"},
        }.get(target, set())
        task = {
            "subtask_id": subtask,
            "target": target,
            "goal": goal,
            "constraints": state["canonical_constraints"],
            "entity_refs": [
                r
                for r in state["entity_refs"]
                if r["kind"] in kinds
                and not (
                    target == "order" and r["kind"] == "proposal" and r["relation"] != "purchase"
                )
            ],
            "evidence_refs": state["evidence_refs"] if target == "aftersales" else [],
            "depends_on": list(depends),
            "read_only": read_only,
        }
        if change:
            change(task)
        return ai(call("route", {"tasks": [task], "terminal": None}))

    return decision


def make_models(supervisor=(), shopping=(), order=(), aftersales=()):
    return {
        name: MultiModel(role=name, script=list(script))
        for name, script in [
            ("supervisor", supervisor),
            ("shopping", shopping),
            ("order", order),
            ("aftersales", aftersales),
        ]
    }


async def install(env, models, *, encoder=None, indexed=True, embedding="fixture"):
    from retrieval_helpers import index

    if embedding == "local":
        import asyncio

        from agentmall.retrieval.embedding import LocalEncoder
        from agentmall.retrieval.ingest import index_policies, index_products, load_policies

        encoder = await asyncio.to_thread(LocalEncoder)
        async with env[2].state.sessions.begin() as session:
            await index_products(session, env[3].storefront_id, encoder)
            await index_policies(session, load_policies(), encoder)
    elif indexed:
        encoder = await index(env)
    env[2].state.multi_models = models
    env[2].state.retrieval_encoder = encoder
    trace = {}
    env[2].state.multi_trace_factory = lambda: trace
    return trace


async def send(
    env,
    buyer,
    *,
    message="找一款300元以内的静音键盘准备购买，送演示宿舍",
    constraints=None,
    request_id=None,
):
    body = {"request_id": request_id or str(uuid4()), "thread_id": str(uuid4()), "message": message}
    if constraints is not None:
        body["constraints"] = constraints
    response = await env[0].post("/api/v1/agent/multi/messages", headers=buyer, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def choose_purchase(messages):
    handoff = payload(messages)
    selected = next(
        r["id"]
        for r in handoff["entity_refs"]
        if r["kind"] == "product" and r["relation"] == "replacement"
    )
    return ai(call("prepare_checkout", {"product_id": selected}))


def last_result(messages):
    return json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))


def save_evidence(name, env, trace, result, *, baseline_counts):
    """Opt-in receipts from assertions in the same real graph/database test run."""
    import os
    from pathlib import Path

    from conftest import ROOT, row

    destination = os.environ.get("AGENTMALL_T08_EVIDENCE_DIR")
    if not destination:
        return
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT / "evals/evidence/t08"):
        raise ValueError("Evidence destination must be inside evals/evidence/t08")
    destination.mkdir(parents=True, exist_ok=True)
    from test_multiagent_integration import facts

    database = dict(
        row(
            env[1],
            "SELECT current_database() database, current_schema() schema, "
            "current_setting('server_version') server_version, "
            "(SELECT extversion FROM pg_extension WHERE extname='vector') vector_version",
        )
    )
    index = dict(
        row(
            env[1],
            "SELECT min(embedding_model) model_id, min(embedding_revision) revision, "
            "min(extensions.vector_dims(embedding)) dimensions, count(*) rows FROM product_search",
        )
    )
    receipt = {
        "case": name,
        "chat_provider": "SCRIPTED_FIXTURE",
        "paid_calls": 0,
        "database": database,
        "business_counts": dict(facts(env)),
        "baseline_counts": dict(baseline_counts),
        "business_delta": {key: value - baseline_counts[key] for key, value in facts(env).items()},
        "embedding": index,
        "trace": trace,
        "result": result,
        "schema_cleanup": "pytest owned-schema fixture runs after this receipt",
    }
    (destination / (name + ".json")).write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n"
    )


def assessment_reads(order_id):
    """Explicit synthetic assessment decisions, not an automatic production plan."""
    return [
        ai(
            call("get_order", {"order_id": str(order_id)}),
            call("check_eligibility", {"order_id": str(order_id), "reason_code": "QUALITY_ISSUE"}),
            call("retrieve_policies", {"order_id": str(order_id), "query": "质量问题退货期限"}),
        ),
        final(),
    ]
