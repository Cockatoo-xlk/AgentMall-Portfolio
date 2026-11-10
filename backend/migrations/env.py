import asyncio

from alembic import context

from agentmall.actions.models import ActionProposal, Confirmation, IdempotencyRequest  # noqa: F401
from agentmall.aftersales.models import AfterSalesCase, Refund  # noqa: F401
from agentmall.agents.models import AgentRun, AgentThread, RunEvent  # noqa: F401
from agentmall.cart.models import Cart, CartItem  # noqa: F401
from agentmall.catalog.models import Product  # noqa: F401
from agentmall.catalog_operations.models import (  # noqa: F401
    CatalogCommand,
    CatalogImport,
    CatalogIndexJob,
    ProductDraft,
)
from agentmall.identity.models import User  # noqa: F401
from agentmall.infra.audit import BusinessEvent  # noqa: F401
from agentmall.infra.config import Settings
from agentmall.infra.db import Base, database
from agentmall.orders.models import Order, OrderItem  # noqa: F401
from agentmall.payments.models import Payment  # noqa: F401
from agentmall.retrieval.models import KnowledgeChunk, KnowledgeDocument, ProductSearch  # noqa: F401
from agentmall.support.models import SupportTicket  # noqa: F401


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run():
    engine, _ = database(Settings())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if connection := context.config.attributes.get("connection"):
    migrate(connection)
elif context.is_offline_mode():
    context.configure(
        url="postgresql+psycopg://", target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run())
