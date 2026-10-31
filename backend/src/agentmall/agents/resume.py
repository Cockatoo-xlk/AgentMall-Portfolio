"""Authenticated confirmation binding and deterministic, replayable domain execution."""

from uuid import UUID

from agentmall.actions import service as actions
from agentmall.infra.errors import DomainError
from agentmall.orders import service as orders


async def validate_confirmation(session, actor, proposal_id, confirmation_id):
    proposal = await actions.get_proposal(session, actor, proposal_id)
    if proposal.action_type not in {"CHECKOUT", "RETURN_REQUEST"}:
        raise DomainError(403, "ACTION_FORBIDDEN", "本图不执行该动作")
    if proposal.confirmation is None or proposal.confirmation.confirmation_id != confirmation_id:
        raise DomainError(409, "CONFIRMATION_MISMATCH", "确认必须属于当前提案")
    if proposal.status == "EXPIRED" and proposal.result is None:
        raise DomainError(409, "STALE_PROPOSAL", "提案已过期")
    return proposal


async def execute_confirmation(runtime, payload):
    async with runtime.sessions.begin() as session:
        from agentmall.agents.specialist_tools import SpecialistTools, authenticate, ref

        actor = await authenticate(runtime, session)
        proposal = await validate_confirmation(
            session, actor, UUID(payload["proposal_id"]), UUID(payload["confirmation_id"])
        )
        if proposal.confirmation.decision == "approve":
            await orders.execute_confirmed_action(
                session,
                actor,
                proposal.proposal_id,
                proposal.confirmation.confirmation_id,
                f"t09:execute:{proposal.proposal_id}",
                expected_action=proposal.action_type,
            )
        proposal = await actions.get_proposal(session, actor, proposal.proposal_id)
        data = SpecialistTools.proposal_data(proposal)
    runtime.facts[("proposal", str(proposal.proposal_id))] = data
    if proposal.result:
        kind = "order" if proposal.action_type == "CHECKOUT" else "case"
        entity = ref(kind, proposal.result.resource_id, "purchase" if kind == "order" else "return")
        runtime.references[(entity.kind, str(entity.id), entity.relation)] = entity
    runtime.event(
        "business_receipt",
        action_id=str(proposal.proposal_id),
        status=proposal.status,
        resource_id=str(proposal.result.resource_id) if proposal.result else None,
    )
