"""Opt-in factory. The default FastAPI application remains MODEL_DISABLED."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi.responses import JSONResponse

from agentmall.infra.llm import load_live_key
from agentmall.playground.ledger import PlaygroundLedger
from agentmall.playground.policy import PlaygroundRejected, validate_approval
from agentmall.playground.provider import metered_model


class Playground:
    def __init__(self, ledger, clients):
        self.ledger, self.clients = ledger, clients

    @property
    def identity(self):
        return self.ledger.policy.evidence_mode + ":" + self.ledger.policy.binding

    async def close(self):
        for clients in self.clients:
            await clients.close()


def attach_models(app, policy, state_dir, key, transport_factory=None):
    ledger = PlaygroundLedger(state_dir / "ledger.json", policy)
    clients, models = [], {}
    for role in ["supervisor", "shopping", "order", "aftersales", "single"]:
        inner = transport_factory(role) if transport_factory else None
        model, pair = metered_model(ledger, role, key, inner)
        models[role] = model
        clients.append(pair)
    provider = Playground(ledger, clients)
    app.state.multi_models = {
        k: models[k] for k in ["supervisor", "shopping", "order", "aftersales"]
    }
    app.state.durable_single_model = models["single"]
    app.state.playground = provider
    old = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        try:
            async with old(instance):
                yield
        finally:
            await provider.close()

    app.router.lifespan_context = lifespan
    return provider


def create_live_app(policy, *, approval_path, state_dir, settings=None):
    # Approval and source/price checks precede ANY key access or ledger creation.
    if not policy.enabled:
        raise PlaygroundRejected("LIVE_DISABLED")
    validate_approval(policy, approval_path)
    if settings is None or settings.db_schema == "public" or settings.checkpoint_schema is None:
        raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED")
    from agentmall.agents.persistence import connection_info
    from agentmall.main import create_app

    connection_info(settings)  # Keep the exact original loopback55433/database guard.
    from agentmall.playground.environment import verify_owned
    from agentmall.retrieval.embedding import LocalEncoder

    verify_owned(settings, policy.environment_id)
    try:
        encoder = LocalEncoder()
    except Exception:
        raise PlaygroundRejected("LOCAL_BGE_REQUIRED") from None
    os.environ.pop("OPENAI_LOG", None)
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    from agentmall.playground.lease import ServerLease

    lease = ServerLease(state_dir)
    for name in ["openai", "httpx", "httpcore"]:
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        key = load_live_key()
        app = create_app(settings)
        attach_models(app, policy, state_dir, key)
    except BaseException:
        lease.close()
        raise
    app.state.retrieval_encoder = encoder
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def live_lifespan(instance):
        try:
            async with lifespan(instance):
                from agentmall.retrieval.ingest import index_policies, index_products, load_policies

                async with app.state.sessions.begin() as session:
                    await index_products(session, settings.storefront_id, encoder)
                    await index_policies(session, load_policies(), encoder)
                yield
        finally:
            lease.close()

    app.router.lifespan_context = live_lifespan

    @app.middleware("http")
    async def loopback_only(request, call_next):
        if (
            request.client is None
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in {"127.0.0.1", "localhost"}
        ):
            return JSONResponse(
                {"code": "LOCALHOST_REQUIRED", "message": "仅允许本机访问"}, status_code=403
            )
        return await call_next(request)

    return app
