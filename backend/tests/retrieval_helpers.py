from uuid import uuid5

from agentmall.identity.service import ActorContext


def actor(settings, login="buyer1", store=None):
    return ActorContext(
        uuid5(settings.storefront_id, login), "buyer", store or settings.storefront_id
    )


class FixtureEncoder:
    """Deliberately non-semantic unit vector: verifies plumbing only."""

    model_id = "agentmall/fixture"
    revision = "unit-v1"
    dimension = 512

    def encode(self, texts, *, query=False):
        return [[1.0] + [0.0] * 511 for _ in texts]


async def index(env):
    from agentmall.retrieval.ingest import index_policies, index_products, load_policies

    encoder = FixtureEncoder()
    async with env[2].state.sessions.begin() as session:
        await index_products(session, env[3].storefront_id, encoder)
        await index_policies(session, load_policies(), encoder)
    env[2].state.retrieval_encoder = encoder
    return encoder
