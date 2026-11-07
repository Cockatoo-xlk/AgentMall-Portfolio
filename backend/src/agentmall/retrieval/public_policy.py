"""Bounded public policy text, without model inference or eligibility claims."""

from sqlalchemy import func, or_, select

from agentmall.identity.service import require_buyer
from agentmall.infra.errors import DomainError
from agentmall.retrieval.models import KnowledgeChunk as K
from agentmall.retrieval.models import KnowledgeDocument as D
from agentmall.retrieval.search import policy_scope


async def get_public_return_policy(session, actor, order_id=None, policy_version=None):
    if order_id is not None:
        require_buyer(actor)
        scope = await policy_scope(session, actor, order_id)  # Existing owned-order gate first.
    else:
        # A separate public domain query; the old buyer-only RAG API is unchanged.
        scope = [
            D.store_id == actor.store_id,
            D.kind == "policy",
            D.visibility == "public",
            D.version == (policy_version or "demo-v1"),
            D.valid_from <= func.now(),
            or_(D.valid_to.is_(None), D.valid_to > func.now()),
        ]
    if policy_version is not None:
        scope.append(D.version == policy_version)
    rows = (
        await session.execute(
            select(D, K)
            .join(K, K.document_id == D.id)
            .where(*scope)
            .order_by(D.id, K.section_id)
            .limit(20)
        )
    ).all()
    if not rows:
        raise DomainError(404, "POLICY_NOT_FOUND", "没有有效的公开政策原件")
    return {
        "items": [
            {
                "document_id": d.id,
                "title": d.title,
                "text": k.text,
                "source_uri": f"{d.source_uri}#{k.section_id}",
                "policy_version": d.version,
            }
            for d, k in rows
        ],
        "informational_only": True,
    }
