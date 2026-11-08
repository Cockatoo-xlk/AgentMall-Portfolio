"""Local-only Playwright backend: real FastAPI/PostgreSQL, explicitly fake model.

Run with backend/.venv/bin/python backend/tests/web_e2e_server.py --port 8001.
Only this test executable registers /__test routes. No live model is constructed.
"""

import argparse
import asyncio
import json
import os
import signal
import socket
import tempfile
from collections.abc import MutableMapping
from contextlib import AsyncExitStack, ExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

E2E_KEY = "agentmall-local-e2e"  # Public test control label, not a credential.
FIXTURE_MODE = "fake-model-real-fastapi-postgresql"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
Mode = Literal["proposal", "needs_input", "blocked", "error", "done"]


def validate_host(host):
    if host not in LOOPBACK:
        raise ValueError("E2E server requires a loopback host")
    return host


class FilteredEnvironment(MutableMapping):
    """Filter key names before retrieving values from the original environment."""

    def __init__(self, original):
        self.original, self.overrides, self.deleted = original, {}, set()

    @staticmethod
    def hidden(key):
        return any(
            part in key.upper()
            for part in (
                "DEEPSEEK",
                "OPENAI",
                "ANTHROPIC",
                "LANGSMITH",
                "LANGCHAIN",
                "GEMINI",
                "GOOGLE_API",
                "MISTRAL",
                "COHERE",
                "GROQ",
                "TOGETHER",
                "HUGGINGFACE",
            )
        )

    def __iter__(self):
        return iter(
            (set(self.original) | set(self.overrides))
            - self.deleted
            - {key for key in self.original if self.hidden(key)}
        )

    def __len__(self):
        return sum(1 for _ in self)

    def __getitem__(self, key):
        if self.hidden(key) or key in self.deleted:
            raise KeyError(key)
        return self.overrides[key] if key in self.overrides else self.original[key]

    def __setitem__(self, key, value):
        if self.hidden(key):
            raise ValueError("Provider environment is disabled in the E2E harness")
        self.overrides[key] = value
        self.deleted.discard(key)

    def __delitem__(self, key):
        self.overrides.pop(key, None)
        self.deleted.add(key)


@dataclass
class Boundary:
    provider_http_requests: int = 0
    real_model_calls: int = 0
    fake_model_calls: int = 0
    blocked_external_attempts: int = 0

    def allow(self, host):
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="replace")
        if host not in LOOPBACK:
            self.blocked_external_attempts += 1
            raise RuntimeError("E2E harness forbids external network/provider requests")


@contextmanager
def offline_boundary():
    """Install before importing any provider-capable library in the executable."""
    boundary = Boundary()
    with ExitStack() as cleanup:
        cleanup.enter_context(patch.object(os, "environ", FilteredEnvironment(os.environ)))
        # Imports occur after environment filtering, including SDK transitive imports.
        import httpx
        import httpx2

        for module in (httpx, httpx2):
            sync = module.HTTPTransport.handle_request
            asynchronous = module.AsyncHTTPTransport.handle_async_request

            def local_http(self, request, *, original=sync):
                boundary.allow(request.url.host)
                return original(self, request)

            async def local_http_async(self, request, *, original=asynchronous):
                boundary.allow(request.url.host)
                return await original(self, request)

            cleanup.enter_context(patch.object(module.HTTPTransport, "handle_request", local_http))
            cleanup.enter_context(
                patch.object(module.AsyncHTTPTransport, "handle_async_request", local_http_async)
            )
        for method in ("connect", "connect_ex"):
            original = getattr(socket.socket, method)

            def connect(sock, address, *, original=original):
                if isinstance(address, tuple):
                    boundary.allow(address[0])
                return original(sock, address)

            cleanup.enter_context(patch.object(socket.socket, method, connect))
        getaddrinfo, sendto = socket.getaddrinfo, socket.socket.sendto

        def resolve(host, *args, **kwargs):
            if host is not None:
                boundary.allow(host)
            return getaddrinfo(host, *args, **kwargs)

        def send(sock, data, *args):
            address = args[-1]
            if isinstance(address, tuple):
                boundary.allow(address[0])
            return sendto(sock, data, *args)

        cleanup.enter_context(patch.object(socket, "getaddrinfo", resolve))
        cleanup.enter_context(patch.object(socket.socket, "sendto", send))
        yield boundary


def fake_model(mode, boundary):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class FakeModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "agentmall-e2e-fake-model"

        def bind_tools(self, tools, **kwargs):
            if {tool.name for tool in tools} != {
                "search_products",
                "get_product",
                "prepare_checkout",
            }:
                raise AssertionError("Unexpected tool capability")
            return self

        def _generate(self, *args, **kwargs):
            raise AssertionError("E2E FakeModel is async only")

        async def _agenerate(self, messages, **kwargs):
            boundary.fake_model_calls += 1
            if mode == "error":
                raise RuntimeError("Synthetic E2E model failure")
            tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
            calls = []
            if mode == "proposal" and not tool_messages:
                calls = [
                    self.tool_call(
                        "search_products",
                        {
                            "query": "静音",
                            "category": "keyboard",
                            "max_price_cents": 30000,
                            "limit": 5,
                        },
                    )
                ]
            elif mode == "proposal" and tool_messages[-1].name == "search_products":
                result = json.loads(tool_messages[-1].content)
                products = [
                    item
                    for item in result.get("items", [])
                    if (
                        item["category"] == "keyboard"
                        and item["price_cents"] <= 30000
                        and item["attributes"].get("switch") == "静音轴"
                        and item["available"] >= 1
                    )
                ]
                if products:
                    calls = [
                        self.tool_call(
                            "prepare_checkout",
                            {
                                "items": [{"product_id": products[0]["id"], "quantity": 1}],
                                "address_label": "demo_dorm",
                            },
                        )
                    ]
            response = AIMessage(
                content="" if calls else "请核对真实提案并等待用户确认。",
                tool_calls=calls,
                usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                response_metadata={
                    "token_usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                    }
                },
            )
            return ChatResult(generations=[ChatGeneration(message=response)])

        @staticmethod
        def tool_call(name, arguments):
            return {
                "name": name,
                "args": arguments,
                "id": "e2e_" + uuid4().hex,
                "type": "tool_call",
            }

    return FakeModel()


@dataclass
class Harness:
    app: object
    db: object
    settings: object
    schema: str
    boundary: Boundary
    sdk_program: object = None
    sdk_directory: object = None
    catalog_profile: str = "legacy"
    mode: Mode = "proposal"
    workflow_mode: str = "purchase"
    answer_failure_used: bool = False
    start_interrupted_used: bool = False
    offset: timedelta = timedelta(0)
    agent_traces: list = field(default_factory=list)
    request_mode: ContextVar = field(default_factory=lambda: ContextVar("e2e_mode"))
    request_offset: ContextVar = field(default_factory=lambda: ContextVar("e2e_offset"))

    def status(self):
        return {
            "schema": self.schema,
            "checkpoint_schema": self.settings.checkpoint_schema,
            "fixture_mode": FIXTURE_MODE,
            "catalog_dataset": "expanded-120-v1"
            if self.catalog_profile == "expanded"
            else "legacy-12-v1",
            "mode": self.mode,
            "provider_http_requests": self.boundary.provider_http_requests,
            "real_model_calls": self.boundary.real_model_calls,
            "fake_model_calls": self.boundary.fake_model_calls,
            "blocked_external_attempts": self.boundary.blocked_external_attempts,
        }

    def trace(self):
        trace = {"fixture_mode": FIXTURE_MODE, "mode": self.request_mode.get(self.mode)}
        self.agent_traces.append(trace)
        return trace

    def facts(self):
        from sqlalchemy import text

        # Independent synchronous connection: never infer DB effects from HTTP responses.
        with self.db.connect() as connection:
            state = dict(
                connection.execute(
                    text(
                        "SELECT (SELECT count(*) FROM orders) orders, "
                        "(SELECT count(*) FROM action_proposals) proposals, "
                        "(SELECT count(*) FROM confirmations) confirmations, "
                        "(SELECT coalesce(sum(reserved), 0) FROM products) reserved, "
                        "(SELECT count(*) FROM idempotency_requests "
                        "WHERE action_id IS NOT NULL) receipts, "
                        "(SELECT count(*) FROM business_events) events"
                    )
                )
                .mappings()
                .one()
            )
            for key, query in {
                "thread_context_rows": "SELECT * FROM agent_thread_contexts ORDER BY thread_id",
                "candidate_set_rows": "SELECT * FROM agent_candidate_sets ORDER BY created_at,id",
                "context_mutation_rows": (
                    "SELECT * FROM agent_context_mutations ORDER BY created_at,id"
                ),
                "run_rows": "SELECT id, thread_id, request_id, status, pending_confirmation, "
                "result, last_error, COALESCE("
                "(SELECT value->'output'->'runtime_state'->'constraints' "
                "FROM jsonb_each(agent_runs.node_journal) WHERE "
                "value->'output'->'runtime_state' ? 'constraints' "
                "ORDER BY (value->>'seq')::integer DESC LIMIT 1), "
                "context_snapshot->'constraints',request_payload->'constraints') AS constraints "
                "FROM agent_runs ORDER BY created_at",
                "run_event_rows": "SELECT run_id, seq, event_type, agent, action_id, "
                "payload_summary, timestamp FROM run_events ORDER BY run_id, seq",
                "case_rows": "SELECT id, order_id, status, proposal_id, policy_version "
                "FROM aftersales_cases ORDER BY created_at",
                "refund_rows": "SELECT id, case_id, status FROM refunds ORDER BY created_at",
                "ticket_rows": "SELECT id, order_id, status, resolution, version "
                "FROM support_tickets ORDER BY created_at",
                "proposal_rows": "SELECT id, actor_id, origin_request_id, action_type, status, "
                "expires_at, payload_hash, canonical_payload FROM action_proposals "
                "ORDER BY created_at,id",
                "cart_rows": "SELECT id,user_id,store_id,version FROM carts ORDER BY id",
                "cart_item_rows": "SELECT id,cart_id,store_id,product_id,quantity "
                "FROM cart_items ORDER BY cart_id,product_id",
                "order_rows": "SELECT * FROM orders ORDER BY created_at,id",
                "confirmation_rows": "SELECT * FROM confirmations ORDER BY created_at,id",
                "payment_rows": "SELECT id, order_id, action_id, status, amount_cents, provider "
                "FROM payments ORDER BY created_at,id",
                "receipt_rows": "SELECT id, action_id, actor_id, operation, key, result "
                "FROM idempotency_requests WHERE action_id IS NOT NULL ORDER BY created_at,id",
                "event_rows": "SELECT * FROM business_events ORDER BY occurred_at,id",
                "product_rows": "SELECT id, name, category, price_cents, on_hand, reserved, "
                "active, attributes FROM products ORDER BY id",
            }.items():
                state[key] = [dict(row) for row in connection.execute(text(query)).mappings()]
            state["checkpoint_rows"] = connection.scalar(
                text(f'SELECT count(*) FROM "{self.settings.checkpoint_schema}".checkpoints')
            )
        sdk = None
        if self.sdk_program is not None:
            provider = self.app.state.playground
            from uuid import uuid5

            sdk = provider.ledger.summary(
                uuid5(self.settings.storefront_id, "buyer1"), self.settings.storefront_id
            )
            sdk["wire_requests"] = len(self.sdk_program.requests)
            sdk["tools"] = [
                c["function"]["name"]
                for record in self.sdk_program.requests
                for c in record["body"].get("tools", [])
            ]
        return {**self.status(), **state, "agent_traces": self.agent_traces, "sdk": sdk}

    async def close_sdk(self):
        provider = getattr(self.app.state, "playground", None)
        if provider is not None:
            await provider.close()
            self.app.state.playground = None
        if self.sdk_directory is not None:
            self.sdk_directory.cleanup()
        self.sdk_program, self.sdk_directory = None, None

    async def reset(self):
        from sqlalchemy import text

        from agentmall.seed import seed

        await self.close_sdk()
        tables = (
            "catalog_commands",
            "catalog_index_jobs",
            "product_drafts",
            "catalog_imports",
            "agent_context_mutations",
            "agent_candidate_sets",
            "agent_thread_contexts",
            "run_events",
            "agent_runs",
            "agent_threads",
            "product_search",
            "knowledge_chunks",
            "knowledge_documents",
            "refunds",
            "support_tickets",
            "aftersales_cases",
            "payments",
            "business_events",
            "order_items",
            "orders",
            "confirmations",
            "idempotency_requests",
            "action_proposals",
            "cart_items",
            "carts",
            "products",
            "users",
        )
        # Exact owned schema and full FK set; no CASCADE or search-path fallback on reset.
        targets = ", ".join(f'"{self.schema}"."{table}"' for table in tables)
        with self.db.begin() as connection:
            connection.execute(text(f"TRUNCATE TABLE {targets}"))
            connection.execute(
                text(
                    "TRUNCATE "
                    + ", ".join(
                        f'"{self.settings.checkpoint_schema}"."{table}"'
                        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
                    )
                )
            )
        from agentmall.payments.service import MockPaymentAdapter

        self.app.state.mock_payment_adapter = MockPaymentAdapter()
        self.checkout_failure = False
        self.mode, self.offset = "proposal", timedelta(0)
        self.workflow_mode = "purchase"
        self.answer_failure_used = False
        self.start_interrupted_used = False
        self.agent_traces.clear()
        self.boundary.fake_model_calls = 0
        async with self.app.state.sessions.begin() as session:
            await seed(
                session,
                self.settings,
                profile=os.environ.get("AGENTMALL_DEMO_CATALOG_PROFILE", "legacy"),
            )
            self.catalog_profile = os.environ.get("AGENTMALL_DEMO_CATALOG_PROFILE", "legacy")
        from retrieval_helpers import index

        await index((None, self.db, self.app, self.settings))


def mount_controls(harness):
    from fastapi import APIRouter, Depends, HTTPException, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, ConfigDict, Field
    from sqlalchemy import text
    from starlette.datastructures import State

    class RequestState(State):
        def __getattr__(self, name):
            if name == "agent_model":
                mode = harness.request_mode.get(harness.mode)
                return None if mode in {"blocked", "done"} else fake_model(mode, harness.boundary)
            if name in {"multi_models", "durable_single_model"}:
                if self._state.get("playground") is not None:
                    return self._state[name]
                from workflow_e2e import models

                value = models(harness.workflow_mode, harness.boundary)
                if name == "durable_single_model":
                    return value["single"] if value else None
                return {k: v for k, v in value.items() if k != "single"} if value else None
            return super().__getattr__(name)

    harness.app.state = RequestState(harness.app.state._state)
    harness.app.state.agent_trace_factory = harness.trace

    @harness.app.middleware("http")
    async def local_request(request: Request, call_next):
        if request.client is None or request.client.host not in LOOPBACK:
            return JSONResponse({"detail": "Loopback required"}, status_code=403)
        mode_token = harness.request_mode.set(harness.mode)
        time_token = harness.request_offset.set(harness.offset)
        try:
            return await call_next(request)
        finally:
            harness.request_mode.reset(mode_token)
            harness.request_offset.reset(time_token)

    def authorize(request: Request):
        if request.headers.get("X-E2E-Key") != E2E_KEY:
            raise HTTPException(403, "E2E test key required")

    class ModeRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        mode: Mode

    class ExpireRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        proposal_id: UUID

    class UserRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        login: Literal["buyer1", "buyer2", "merchant"]

    class ProductRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        product_id: UUID

    class CheckoutFailureRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        enabled: bool

    class PaymentModeRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        result: Literal["SUCCEEDED", "DECLINED"]

    class OrderConditionRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        order_id: UUID
        condition: Literal["near_expiry", "expire", "stale_version"]

    router = APIRouter(prefix="/__test", dependencies=[Depends(authorize)])

    @router.get("/health")
    async def health():
        return {"ready": True, **harness.status()}

    @router.get("/facts")
    async def facts():
        from workflow_e2e import graph_facts

        return {**harness.facts(), "checkpoints": await graph_facts(harness)}

    class WorkflowMode(BaseModel):
        mode: Literal[
            "purchase",
            "return_replace",
            "return_partial",
            "denied",
            "human",
            "disabled",
            "clarify",
            "answer_failure",
            "start_interrupted",
            "start_unfinalized",
        ]

    @router.post("/workflow-mode")
    async def workflow_mode(payload: WorkflowMode):
        harness.workflow_mode = payload.mode
        return {"mode": payload.mode}

    class SDKMode(BaseModel):
        model_config = ConfigDict(extra="forbid")
        program: Literal[
            "context",
            "context-catalog",
            "bundle",
            "purchase",
            "recommend",
            "orders",
            "return_replace",
            "timeout",
            "missing_usage",
            "malicious",
        ]
        order_id: UUID | None = None
        delay_ms: int = Field(0, ge=0, le=1500)

    @router.post("/sdk-mode")
    async def sdk_mode(payload: SDKMode):
        from pathlib import Path

        from playground_helpers import install_sdk

        await harness.close_sdk()
        harness.sdk_directory = tempfile.TemporaryDirectory(prefix="agentmall-sdk-mock-")
        if payload.program == "bundle":
            from bundle_helpers import install_bundle_sdk

            _, harness.sdk_program = await install_bundle_sdk(
                (None, harness.db, harness.app, harness.settings), Path(harness.sdk_directory.name)
            )
            return {"mode": "MOCK_TRANSPORT", "real_model_calls": 0}
        if payload.program in {"context", "context-catalog"}:
            from multiturn_helpers import install_context_sdk, wireless_products

            env = (None, harness.db, harness.app, harness.settings)
            if payload.program == "context":
                await wireless_products(env)
            _, harness.sdk_program = await install_context_sdk(
                env, Path(harness.sdk_directory.name)
            )
            return {"mode": "MOCK_TRANSPORT", "real_model_calls": 0}
        _, harness.sdk_program = await install_sdk(
            (None, harness.db, harness.app, harness.settings),
            Path(harness.sdk_directory.name),
            payload.program,
            str(payload.order_id) if payload.order_id else None,
            delay_ms=payload.delay_ms,
        )
        return {"mode": "MOCK_TRANSPORT", "real_model_calls": 0}

    @router.post("/checkout-failure")
    async def checkout_failure(payload: CheckoutFailureRequest):
        harness.checkout_failure = payload.enabled
        return {"enabled": payload.enabled}

    @router.post("/payment-mode")
    async def payment_mode(payload: PaymentModeRequest):
        from agentmall.payments.service import MockPaymentAdapter

        harness.app.state.mock_payment_adapter = MockPaymentAdapter(payload.result)
        return {"result": payload.result}

    @router.post("/order-condition")
    async def order_condition(payload: OrderConditionRequest):
        # The immutable order expiry is never changed. Server time is anchored in
        # PostgreSQL and advanced locally for this one isolated test process.
        with harness.db.begin() as connection:
            if payload.condition == "stale_version":
                changed = (
                    connection.execute(
                        text(
                            "UPDATE orders SET version=version+1 WHERE id=:id "
                            "AND status='PENDING_PAYMENT' RETURNING id,version,expires_at"
                        ),
                        {"id": payload.order_id},
                    )
                    .mappings()
                    .one_or_none()
                )
            else:
                changed = (
                    connection.execute(
                        text(
                            "SELECT id,version,expires_at,clock_timestamp() AS db_now "
                            "FROM orders WHERE id=:id AND status='PENDING_PAYMENT'"
                        ),
                        {"id": payload.order_id},
                    )
                    .mappings()
                    .one_or_none()
                )
            if changed is None:
                raise HTTPException(404, "Unknown pending synthetic order")
            if payload.condition != "stale_version":
                extra = timedelta(seconds=-60 if payload.condition == "near_expiry" else 1)
                harness.offset = max(
                    harness.offset, changed["expires_at"] - changed["db_now"] + extra
                )
        return {
            "condition": payload.condition,
            "order_id": payload.order_id,
            "version": changed["version"],
            "expires_at": changed["expires_at"],
            "server_clock_offset_seconds": harness.offset.total_seconds(),
        }

    @router.post("/expanded-catalog")
    async def expanded_catalog():
        # Local test-control boundary only; never a public product mutation API.
        from agentmall.seed import seed

        harness.catalog_profile = "expanded"
        async with harness.app.state.sessions.begin() as session:
            await seed(session, harness.settings, profile="expanded")
        from retrieval_helpers import index

        count = await index((None, harness.db, harness.app, harness.settings))
        return {"dataset": "expanded-120-v1", "model": "FIXTURE", "indexed": count is not None}

    @router.post("/reset")
    async def reset():
        await harness.reset()
        return {"reset": True, **harness.status()}

    @router.post("/agent-mode")
    async def agent_mode(payload: ModeRequest):
        harness.mode = payload.mode
        return harness.status()

    @router.post("/expire")
    async def expire(payload: ExpireRequest):
        with harness.db.connect() as connection:
            expiry = connection.scalar(
                text("SELECT expires_at FROM action_proposals WHERE id=:id"),
                {"id": payload.proposal_id},
            )
            if expiry is None:
                raise HTTPException(404, "Unknown proposal")
            now = connection.scalar(text("SELECT clock_timestamp()"))
        harness.offset = max(harness.offset, expiry - now + timedelta(seconds=1))
        return {"proposal_id": payload.proposal_id, "clock_advanced": True, **harness.status()}

    @router.post("/disable-user")
    async def disable_user(payload: UserRequest):
        with harness.db.begin() as connection:
            connection.execute(
                text("UPDATE users SET disabled=true WHERE login=:login"),
                {"login": payload.login},
            )
        return {"login": payload.login, "disabled": True}

    @router.post("/delist-product")
    async def delist_product(payload: ProductRequest):
        with harness.db.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE products SET active=false, catalog_version=catalog_version+1 "
                    "WHERE id=:id"
                ),
                {"id": payload.product_id},
            )
            if result.rowcount != 1:
                raise HTTPException(404, "Unknown product")
        return {"product_id": payload.product_id, "active": False}

    harness.app.include_router(router)


@asynccontextmanager
async def isolated_app():
    with offline_boundary() as boundary:
        from conftest import guard_test_database, migrate
        from sqlalchemy import create_engine, text

        from agentmall.actions import service as actions
        from agentmall.infra.config import Settings
        from agentmall.main import create_app
        from agentmall.orders import service as orders
        from agentmall.seed import seed

        base = Settings()
        if base.test_database_url is None:
            raise ValueError("AGENTMALL_TEST_DATABASE_URL is required")
        url = guard_test_database(base.test_database_url.get_secret_value())
        schema = "test_" + uuid4().hex
        checkpoint_schema = "cp_" + uuid4().hex
        settings = base.model_copy(
            update={
                "database_url": base.test_database_url,
                "db_schema": schema,
                "checkpoint_schema": checkpoint_schema,
            }
        )
        async with AsyncExitStack() as cleanup:
            admin = create_engine(url)
            cleanup.callback(admin.dispose)
            with admin.begin() as connection:
                if connection.scalar(text("SELECT current_database()")) != "agentmall_test":
                    raise ValueError("E2E database identity mismatch")
                if connection.scalar(text("SELECT current_user")) != "agentmall":
                    raise ValueError("E2E database role mismatch")
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))

            def drop_owned_schema():
                # Registered only after this process successfully creates this exact UUID schema.
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

            cleanup.callback(drop_owned_schema)
            with admin.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{checkpoint_schema}"'))

            def drop_owned_checkpoint():
                with admin.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{checkpoint_schema}" CASCADE'))

            cleanup.callback(drop_owned_checkpoint)
            from agentmall.agents.persistence import setup_checkpoint

            await setup_checkpoint(settings)
            db = create_engine(url, connect_args={"options": f"-csearch_path={schema},extensions"})
            cleanup.callback(db.dispose)
            with db.begin() as connection:
                migrate(connection)
            app = create_app(settings)
            from agentmall.catalog_operations.parser import MockCatalogParser

            app.state.catalog_parser = MockCatalogParser()
            # Test transport delays only the mock decision, never invents business tool data.
            import httpx

            from agentmall.merchant_copilot.model import MockMerchantModel

            merchant_fixture = MockMerchantModel()

            async def merchant_response(request):
                if b"select_verified_advice" in request.content:
                    await asyncio.sleep(0.5)
                return merchant_fixture.respond(request)

            app.state.merchant_copilot_model = MockMerchantModel(
                httpx.MockTransport(merchant_response)
            )
            cleanup.push_async_callback(app.state.engine.dispose)
            harness = Harness(app, db, settings, schema, boundary)
            cleanup.push_async_callback(harness.close_sdk)
            mount_controls(harness)
            from agentmall.agents import run_service

            original_save = run_service.NodeStore.save

            async def test_save(store, key, output, trace):
                await original_save(store, key, output, trace)
                if (
                    harness.workflow_mode == "start_interrupted"
                    and not harness.start_interrupted_used
                ):
                    harness.start_interrupted_used = True
                    raise RuntimeError("Fixture interrupted after node journal")

            cleanup.enter_context(patch.object(run_service.NodeStore, "save", test_save))
            original_render = run_service.render

            def test_render(runtime, terminal):
                has_receipt = any(
                    kind == "proposal" and value.get("result")
                    for (kind, _), value in runtime.facts.items()
                )
                if (
                    harness.workflow_mode == "answer_failure"
                    and has_receipt
                    or harness.workflow_mode == "start_unfinalized"
                ) and not harness.answer_failure_used:
                    harness.answer_failure_used = True
                    raise RuntimeError("Fixture post-commit answer rendering failure")
                return original_render(runtime, terminal)

            cleanup.enter_context(patch.object(run_service, "render", test_render))
            original_clock = actions.database_now

            async def test_clock(session):
                return await original_clock(session) + harness.request_offset.get(harness.offset)

            # Process-local test seam; immutable proposal rows and DB triggers remain intact.
            cleanup.enter_context(patch.object(actions, "database_now", test_clock))
            cleanup.enter_context(patch.object(orders, "database_now", test_clock))
            order_event = orders.write_order_event

            async def test_order_event(*args, **kwargs):
                await order_event(*args, **kwargs)
                if getattr(harness, "checkout_failure", False):
                    raise RuntimeError("Fixture checkout precommit rollback")

            cleanup.enter_context(patch.object(orders, "write_order_event", test_order_event))
            from agentmall.payments import service as payments

            cleanup.enter_context(patch.object(payments, "database_now", test_clock))
            async with app.state.sessions.begin() as session:
                await seed(
                    session,
                    settings,
                    profile=os.environ.get("AGENTMALL_DEMO_CATALOG_PROFILE", "legacy"),
                )
                harness.catalog_profile = os.environ.get("AGENTMALL_DEMO_CATALOG_PROFILE", "legacy")
            from retrieval_helpers import index

            await index((None, db, app, settings))
            yield harness


async def serve(host, port):
    validate_host(host)
    async with isolated_app() as harness:
        import uvicorn

        class CleanupServer(uvicorn.Server):
            @contextmanager
            def capture_signals(self):
                # Uvicorn normally replays SIGTERM before serve() returns. That can
                # kill Python before our outer schema cleanup. Own graceful signals here.
                handlers = {
                    sig: signal.signal(sig, self.handle_exit)
                    for sig in (signal.SIGINT, signal.SIGTERM)
                }
                try:
                    yield
                finally:
                    for sig, handler in handlers.items():
                        signal.signal(sig, handler)

        print(json.dumps({"event": "e2e_backend_ready", **harness.status()}), flush=True)
        server = CleanupServer(
            uvicorn.Config(harness.app, host=host, port=port, log_level="warning")
        )
        try:
            await server.serve()
        finally:
            print(json.dumps({"event": "e2e_backend_stopping", **harness.status()}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    arguments = parser.parse_args()
    validate_host(arguments.host)
    if not 1 <= arguments.port <= 65535:
        raise ValueError("Port must be 1..65535")
    asyncio.run(serve(arguments.host, arguments.port))


if __name__ == "__main__":
    main()
