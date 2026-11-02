"""Trusted ephemeral runtime, separate from model-editable graph state."""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from uuid import UUID, uuid5

from agentmall.actions import service as actions
from agentmall.aftersales import service as aftersales
from agentmall.agents.budgets import RunStopped
from agentmall.agents.context import HandoffEnvelope, user_constraints
from agentmall.agents.specialist_tools import authenticate, order_data, product_allowed, ref
from agentmall.catalog import service as catalog
from agentmall.infra.errors import DomainError
from agentmall.orders import service as orders
from agentmall.orders.schemas import OrderFilters
from agentmall.support import service as support


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


@dataclass
class RunContext:
    actor: object
    settings: object
    sessions: object
    input: object
    models: dict
    encoder: object
    budget: object
    trace: dict
    references: dict = field(default_factory=dict)
    facts: dict = field(default_factory=dict)
    citations: dict = field(default_factory=dict)
    completed: dict = field(default_factory=dict)
    pending: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    seen_tasks: set = field(default_factory=set)
    signatures: set = field(default_factory=set)
    tool_ids: set = field(default_factory=set)
    tool_repeats: dict = field(default_factory=dict)
    write_lock: object = field(default_factory=asyncio.Lock)
    schema_repairs: int = 0
    explicit_order_ids: set = field(default_factory=set)
    guard: object = None
    single: bool = False
    thread_snapshot: dict = field(default_factory=dict)
    candidate_lists: dict = field(default_factory=dict)

    def tool_allowlist(self, role):
        from agentmall.agents.specialist_tools import ALLOWLISTS

        return (
            tuple(dict.fromkeys(name for names in ALLOWLISTS.values() for name in names))
            if self.single
            else ALLOWLISTS[role]
        )

    def __post_init__(self):
        url = self.sessions.kw["bind"].url
        if (url.host, url.port, url.database) != ("127.0.0.1", 55433, "agentmall_test"):
            raise RunStopped("DATABASE_SCOPE_MISMATCH")
        from agentmall.agents.context import Constraints

        self.constraints = (
            Constraints.model_validate(self.thread_snapshot["constraints"])
            if self.thread_snapshot
            else user_constraints(self.input)
        )
        self.return_request_id = uuid5(self.input.request_id, "return")
        self.ticket_request_id = uuid5(self.input.request_id, "human")
        self.trace.update(
            request_id=str(self.input.request_id),
            thread_id=str(self.input.thread_id),
            execution_mode=self.mode,
            events=[],
            prompts={},
            tool_allowlists={},
            limits=self.budget.snapshot()["limits"],
        )

    @property
    def mode(self):
        if not self.models:
            return "DISABLED"
        return (
            "FIXTURE"
            if all(
                getattr(m, "_llm_type", "").startswith(("offline", "fixture"))
                for m in self.models.values()
            )
            else "MODEL_ENABLED"
        )

    @property
    def exclusions(self):
        result = set(self.constraints.exclude_product_ids)
        if self.constraints.exclude_original:
            result.update(
                ref.id
                for ref in self.references.values()
                if ref.kind == "product" and ref.relation == "original"
            )
        return result

    def handoff_constraints(self):
        return self.constraints.model_copy(
            update={"exclude_product_ids": sorted(self.exclusions, key=str)}
        )

    def event(self, kind, **values):
        self.trace["events"].append({"seq": len(self.trace["events"]) + 1, "kind": kind, **values})

    async def hydrate_explicit_entities(self):
        """Resolve only UUIDs explicitly supplied by the user, without forwarding raw text."""
        identifiers = list(
            dict.fromkeys(
                re.findall(
                    r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}"
                    r"[0-9a-fA-F]{12}(?![0-9a-fA-F])",
                    self.input.message,
                )
            )
        )[:4]
        async with self.sessions.begin() as session:
            actor = await authenticate(self, session)
            from agentmall.agents.memory import verify_items

            selected = self.thread_snapshot.get("selected", [])
            await verify_items(session, actor, selected)
            for item in selected:
                product = await catalog.get_product(session, actor, UUID(item["id"]))
                if not product_allowed(self, product):
                    raise DomainError(409, "CONSTRAINT_MISMATCH", "所选商品不符合当前偏好")
                self.facts[("product", str(product.id))] = product.model_dump(mode="json")
                entity = ref("product", product.id, "replacement")
                self.references[(entity.kind, str(entity.id), entity.relation)] = entity
            product_ids = []
            for identifier in identifiers:
                # A reference is exposed only after the same domain owner/store check as a tool.
                try:
                    order = await orders.get_order(session, actor, UUID(identifier))
                except DomainError as exc:
                    if exc.code != "NOT_FOUND":
                        raise
                    product_ids.append(UUID(identifier))
                    continue
                else:
                    self.explicit_order_ids.add(order.id)
                    self.facts[("order", str(order.id))] = order_data(order)
                    entities = [ref("order", order.id, "original", order.policy_version)]
                    entities.extend(
                        ref("product", item.product_id, "original") for item in order.items
                    )
                for entity in entities:
                    self.references[(entity.kind, str(entity.id), entity.relation)] = entity
            for identifier in product_ids:
                if ("product", str(identifier), "original") in self.references:
                    continue  # An owned order's original SKU is an opaque exclusion.
                product = await catalog.get_product(session, actor, identifier)
                if not product_allowed(self, product):
                    raise DomainError(409, "CONSTRAINT_MISMATCH", "商品不满足用户约束")
                self.facts[("product", str(product.id))] = product.model_dump(mode="json")
                entity = ref("product", product.id, "replacement")
                self.references[("product", str(product.id), "replacement")] = entity

    def prune_excluded_candidates(self):
        for product_id in self.exclusions:
            self.facts.pop(("product", str(product_id)), None)
            self.references.pop(("product", str(product_id), "replacement"), None)
        for key, result in list(self.completed.items()):
            self.completed[key] = result.model_copy(
                update={
                    "entity_refs": [
                        ref
                        for ref in result.entity_refs
                        if not (
                            ref.kind == "product"
                            and ref.relation == "replacement"
                            and ref.id in self.exclusions
                        )
                    ]
                }
            )

    async def selected_order(self, session, actor):
        if self.explicit_order_ids:
            return (
                next(iter(self.explicit_order_ids)) if len(self.explicit_order_ids) == 1 else None
            )
        page = await orders.list_orders(session, actor, OrderFilters(limit=2))
        return page.items[0].id if len(page.items) == 1 and page.next_cursor is None else None

    async def validate_write_order(self, session, actor, envelope, order_id):
        selected = await self.selected_order(session, actor)
        if selected is None:
            raise DomainError(409, "ORDER_SELECTION_REQUIRED", "请明确要处理的本人订单")
        refs = {e.id for e in envelope.entity_refs if e.kind == "order"}
        if order_id != selected or order_id not in refs:
            raise DomainError(409, "ORDER_SCOPE_MISMATCH", "写操作必须绑定用户选定且已交接的订单")

    async def validate_tasks(self, tasks):
        if len(tasks) > 1 and any(not t.read_only for t in tasks):
            raise RunStopped("UNORDERED_WRITE_HANDOFF")
        envelopes = []
        async with self.sessions.begin() as session:
            actor = await authenticate(self, session)
            for task in tasks:
                if task.subtask_id in self.seen_tasks:
                    raise RunStopped("REPEATED_DELEGATION")
                if task.constraints != self.handoff_constraints():
                    raise RunStopped("HANDOFF_CONSTRAINT_CHANGED")
                if task.target == "shopping" and self.constraints.exclude_original:
                    selected = await self.selected_order(session, actor)
                    if selected is None or ("order", str(selected)) not in self.facts:
                        raise RunStopped("REPLACEMENT_SOURCE_REQUIRED")
                if any(
                    dep not in self.completed
                    or self.completed[dep].status not in {"done", "proposal"}
                    for dep in task.depends_on
                ):
                    raise RunStopped("DEPENDENCY_NOT_READY")
                permitted = {
                    "shopping": {"product"},
                    "order": {"product", "order", "proposal"},
                    "aftersales": {"product", "order", "proposal", "case", "ticket"},
                }[task.target]
                for entity in task.entity_refs:
                    if entity.kind not in permitted:
                        raise RunStopped("CONTEXT_SCOPE_VIOLATION")
                    if (
                        task.target == "order"
                        and entity.kind == "proposal"
                        and entity.relation != "purchase"
                    ):
                        raise RunStopped("CONTEXT_SCOPE_VIOLATION")
                    if (entity.kind, str(entity.id), entity.relation) not in self.references:
                        raise RunStopped("UNOBSERVED_REFERENCE")
                    if entity.kind == "product":
                        # Original delisted SKUs are opaque exclusions, never offered as candidates.
                        if entity.relation != "original":
                            await catalog.get_product(session, actor, entity.id)
                    elif entity.kind == "order":
                        order = await orders.get_order(session, actor, entity.id)
                        if entity.policy_version != order.policy_version:
                            raise RunStopped("POLICY_VERSION_MISMATCH")
                    elif entity.kind == "proposal":
                        await actions.get_proposal(session, actor, entity.id)
                    elif entity.kind == "case":
                        await aftersales.get_case(session, actor, entity.id)
                    else:
                        await support.get_ticket(session, actor, entity.id)
                if task.evidence_refs and task.target != "aftersales":
                    raise RunStopped("CONTEXT_SCOPE_VIOLATION")
                if any(str(e) not in self.citations for e in task.evidence_refs):
                    raise RunStopped("UNOBSERVED_CITATION")
                signature = fingerprint(
                    task.model_dump(exclude={"subtask_id", "depends_on"})
                    | {"facts": fingerprint({str(k): v for k, v in self.facts.items()})}
                )
                if signature in self.signatures:
                    raise RunStopped("REPEATED_DELEGATION")
                envelopes.append((task, signature))
        # Whole batch validates before any delegation. A shared atomic reservation prevents races.
        await self.budget.take("delegations", len(envelopes))
        result = []
        for task, signature in envelopes:
            envelope = HandoffEnvelope(**task.model_dump(), remaining_budget=self.budget.snapshot())
            self.seen_tasks.add(task.subtask_id)
            self.signatures.add(signature)
            self.pending[task.subtask_id] = envelope
            result.append(envelope)
            self.event("handoff", payload=envelope.model_dump(mode="json"))
        return result
