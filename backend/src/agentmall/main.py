from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException

from agentmall.actions.routes import router as actions_router
from agentmall.aftersales.routes import router as aftersales_router
from agentmall.agents.budgets import GraphBudget
from agentmall.agents.routes import router as agent_router
from agentmall.cart.routes import router as cart_router
from agentmall.catalog.routes import router as catalog_router
from agentmall.identity.routes import router as identity_router
from agentmall.infra.config import Settings
from agentmall.infra.db import database
from agentmall.infra.errors import DomainError
from agentmall.infra.llm import Budget
from agentmall.orders.routes import router as orders_router
from agentmall.payments.routes import router as payments_router
from agentmall.payments.service import MockPaymentAdapter
from agentmall.retrieval.routes import router as retrieval_router
from agentmall.support.routes import router as support_router


def create_app(settings: Settings | None = None):
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="AgentMall T06", version="0.6.0", lifespan=lifespan)
    app.state.settings = settings or Settings()
    app.state.mock_payment_adapter = MockPaymentAdapter(app.state.settings.mock_payment_result)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    def error(request, status, code, message, retryable=False, details=None):
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(
            status_code=status,
            headers=headers,
            content={
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", str(uuid4())),
                "retryable": retryable,
                "details": details or {},
            },
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return error(request, exc.status, exc.code, exc.message, exc.retryable)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Never echo input values (including passwords, tokens or arbitrary JSON).
        return error(
            request,
            422,
            "VALIDATION_ERROR",
            "请求参数不符合接口契约",
            details={
                "errors": [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(request, exc.status_code, "HTTP_ERROR", "请求不可用")

    @app.exception_handler(DBAPIError)
    async def database_error(request: Request, exc: DBAPIError):
        return error(request, 503, "DATABASE_UNAVAILABLE", "数据库操作未完成，请先核对状态", True)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error(request, 500, "INTERNAL_ERROR", "请求未完成，请先核对状态")

    for router in (
        identity_router,
        catalog_router,
        cart_router,
        actions_router,
        orders_router,
        payments_router,
        aftersales_router,
        support_router,
        retrieval_router,
    ):
        app.include_router(router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.state.multi_models = None
    app.state.durable_single_model = None
    app.state.multi_budget_factory = GraphBudget
    app.state.multi_trace_factory = dict
    app.state.retrieval_encoder = None
    app.state.agent_model = None  # Explicit injection only; ordinary startup never loads a key.
    app.state.agent_budget_factory = Budget
    app.state.agent_trace_factory = dict
    app.state.engine, app.state.sessions = database(app.state.settings)
    return app
