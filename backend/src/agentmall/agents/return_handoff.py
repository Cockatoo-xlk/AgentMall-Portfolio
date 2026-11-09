"""Server-observed assessment receipts, not model summaries or delegated authority."""

from sqlalchemy import and_, or_, select

from agentmall.actions.models import ActionProposal
from agentmall.actions.service import database_now
from agentmall.aftersales import service as aftersales
from agentmall.agents.budgets import RunStopped
from agentmall.infra.errors import DomainError
from agentmall.orders.lifecycle import owned_order


def record_assessment(runtime, context, result):
    envelope = context.envelope
    if runtime.single or envelope.goal != "assess_return":
        return
    # Even an incomplete assessment is recorded; a later write cannot bypass it.
    proof = {"subtask_id": envelope.subtask_id, "ready": False}
    rows = [row for row in context.records if not row.get("error_code")]
    orders = {row.get("source_order_id") for row in rows if row["name"] == "get_order"}
    if envelope.read_only and len(orders) == 1:
        order_id = next(iter(orders))
        reads = {row["name"]: row for row in rows if row.get("source_order_id") == order_id}
        order = reads["get_order"]["data"]["items"][0]
        eligibility = reads.get("check_eligibility", {}).get("data", {})
        citations = reads.get("retrieve_policies", {}).get("citations", [])
        evidence = [
            c["id"]
            for c in citations
            if c["visibility"] == "public" and c["policy_version"] == order["policy_version"]
        ]
        proof.update(
            order_id=order_id,
            order_version=order["version"],
            policy_version=order["policy_version"],
            original_product_ids=[item["product_id"] for item in order["items"]],
            reason_code=eligibility.get("reason_code"),
            eligible=eligibility.get("eligible") is True,
            evidence_refs=evidence,
            ready=result.status == "done"
            and bool(evidence)
            and eligibility.get("eligible") is True
            and eligibility.get("policy_version") == order["policy_version"],
        )
    runtime.facts[("return_assessment", envelope.subtask_id)] = proof
    runtime.event(
        "return_assessment_completed",
        role="aftersales",
        subtask_id=envelope.subtask_id,
        goal=envelope.goal,
        ok=proof["ready"],
        read_only=envelope.read_only,
    )


def assessment_for(runtime, task):
    assessments = [v for (kind, _), v in runtime.facts.items() if kind == "return_assessment"]
    matches = [v for v in assessments if v["subtask_id"] in task.depends_on]
    if len(matches) != 1 or not matches[0]["ready"]:
        raise RunStopped("RETURN_ASSESSMENT_REQUIRED")
    proof = matches[0]
    completed = runtime.completed.get(proof["subtask_id"])
    if completed is None or completed.status != "done":
        raise RunStopped("DEPENDENCY_NOT_READY")
    orders = {
        str(ref.id)
        for ref in task.entity_refs
        if ref.kind == "order" and ref.relation == "original"
    }
    if orders != {proof["order_id"]} or not set(proof["evidence_refs"]) <= set(
        map(str, task.evidence_refs)
    ):
        raise RunStopped("RETURN_ASSESSMENT_REQUIRED")
    if proof["reason_code"] != runtime.constraints.reason_code:
        raise RunStopped("HANDOFF_CONSTRAINT_CHANGED")
    return proof


async def validate_return_task(runtime, task, session, actor):
    if runtime.single or task.goal != "prepare_return":
        return
    if not runtime.constraints.return_requested:
        raise RunStopped("RETURN_NOT_REQUESTED")
    if await runtime.selected_order(session, actor) is None:
        raise DomainError(409, "ORDER_SELECTION_REQUIRED", "请明确要处理的本人订单")
    proof = assessment_for(runtime, task)
    if proof is not None:
        from agentmall.orders import service as orders

        order = await orders.get_order(session, actor, proof["order_id"])
        await revalidate_return(runtime, task, session, actor, order)


async def revalidate_return(runtime, task, session, actor, order):
    if runtime.single:
        return
    proof = assessment_for(runtime, task)
    # Serialize cross-Run duplicate checks using the existing domain ownership lock.
    # This session is also used by prepare_action, so the lock spans preparation.
    order = await owned_order(session, actor, order.id, lock=True)
    if proof is not None:
        if (
            str(order.id) != proof["order_id"]
            or order.version != proof["order_version"]
            or order.policy_version != proof["policy_version"]
        ):
            raise DomainError(409, "RETURN_EVIDENCE_STALE", "订单或政策已变化，须重新核验")
        eligibility = await aftersales.check_eligibility(
            session, actor, order.id, proof["reason_code"]
        )
        if not eligibility.eligible:
            raise DomainError(409, "AFTERSALES_INELIGIBLE", "当前资格不允许退货")
    # An earlier Run's pending proposal must not be duplicated under a new origin.
    existing = await session.scalar(
        select(ActionProposal.id)
        .where(
            ActionProposal.actor_id == actor.user_id,
            ActionProposal.store_id == actor.store_id,
            ActionProposal.action_type == "RETURN_REQUEST",
            ActionProposal.canonical_payload["order_id"].astext == str(order.id),
            or_(
                ActionProposal.status == "EXECUTED",
                and_(
                    ActionProposal.status.in_(("PENDING", "APPROVED")),
                    ActionProposal.expires_at > await database_now(session),
                ),
            ),
            ActionProposal.origin_request_id != runtime.return_request_id,
        )
        .limit(1)
    )
    if existing:
        raise DomainError(409, "RETURN_PROPOSAL_EXISTS", "已有退货提案，须先处理")
    runtime.event(
        "return_evidence_revalidated",
        role="aftersales",
        subtask_id=task.subtask_id,
        goal=task.goal,
        resource_id=str(order.id),
        ok=True,
    )
