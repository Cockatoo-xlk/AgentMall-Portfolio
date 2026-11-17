"""Formal FastAPI/PG composition for the fixed product smoke; no automatic decisions.

Local trusted Python host only. Docker provisioning stays with the operator;
this module has no Docker CLI/socket, old L8 Host, Agent or Orchestrator.
"""

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from agentmall.main import create_app
from agentmall.playground.environment import initialize_environment, verify_owned
from agentmall.retrieval.embedding import LocalEncoder, identity, validate_vectors
from agentmall.retrieval.ingest import index_policies, index_products, load_policies
from agentmall.seed import DEMO_PASSWORD
from sqlalchemy import create_engine, text

from evals.smoke_runner import (
    SmokeOperator,
    SmokeStopped,
    attach_smoke_models,
    export_evidence,
    load_verified,
)


def sql_facts(settings):
    """Independent, read-only, explicit projection. No private checkpoint bodies."""
    engine = create_engine(
        settings.database_url.get_secret_value(),
        connect_args={
            "options": f"-csearch_path={settings.db_schema},extensions -cstatement_timeout=3000"
        },
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if conn.scalar(text("SELECT current_schema()")) != settings.db_schema:
                raise SmokeStopped("SQL_SCHEMA_MISMATCH")
            statements = {
                "orders": (
                    "SELECT id,user_id,store_id,proposal_id,status,total_cents,address_label "
                    "FROM orders ORDER BY id"
                ),
                "items": (
                    "SELECT order_id,product_id,quantity,unit_price_cents,attributes_snapshot "
                    "FROM order_items ORDER BY id"
                ),
                "cases": (
                    "SELECT id,order_id,user_id,store_id,proposal_id,status,reason_code "
                    "FROM aftersales_cases ORDER BY id"
                ),
                "confirmations": (
                    "SELECT id,proposal_id,actor_id,store_id,decision,consumed_at,result_ref "
                    "FROM confirmations ORDER BY id"
                ),
                "proposals": (
                    "SELECT id,actor_id,store_id,action_type,status,payload_hash "
                    "FROM action_proposals ORDER BY id"
                ),
                "products": (
                    "SELECT id,store_id,name,price_cents,active,on_hand,reserved,attributes "
                    "FROM products ORDER BY id"
                ),
                "runs": (
                    "SELECT id,thread_id,request_id,status,epoch,budget,last_error,"
                    "worker_token IS NOT NULL has_worker,lock_pid IS NOT NULL has_lock,"
                    "event_seq FROM agent_runs ORDER BY id"
                ),
                "receipts": (
                    "SELECT action_id,operation,result FROM idempotency_requests ORDER BY id"
                ),
            }
            data = {
                k: [dict(r) for r in conn.execute(text(v)).mappings()]
                for k, v in statements.items()
            }
            data["payments"] = conn.scalar(text("SELECT count(*) FROM payments"))
            data["refunds"] = conn.scalar(text("SELECT count(*) FROM refunds"))
            cp = settings.checkpoint_schema
            # Settings validates cp_ plus32 hex before this identifier is interpolated.
            data["checkpoint_count"] = conn.scalar(
                text(f'SELECT count(*) FROM "{cp}".checkpoints')
            )
            return json.loads(json.dumps(data, default=str))
    finally:
        engine.dispose()


async def _api(client, method, path, auth=None, data=None):
    headers = {**(auth or {})}
    if method == "POST":
        headers["Idempotency-Key"] = str(uuid4())
    response = await client.request(
        method, "/api/v1" + path, headers=headers, json=data
    )
    if response.is_error:
        raise SmokeStopped("FIXTURE_API_REJECTED")
    return response.json()


async def prepare_delivered_fixture(client, buyer, original_name):
    """Declared C setup only, before baseline/Agent. Two SETUP confirmations.

    The mock-payment adapter moves synthetic DB state; it cannot transfer funds.
    Agent/Smoke operator approvals are never performed by this setup function.
    """
    products = await _api(client, "GET", "/products?limit=100")
    selected = [
        p
        for p in products["items"]
        if p["name"] == original_name and p["available"] > 0
    ]
    if len(selected) != 1:
        raise SmokeStopped("FIXTURE_PRODUCT_AMBIGUOUS")
    proposal = await _api(
        client,
        "POST",
        "/checkout/proposals",
        buyer,
        {
            "request_id": str(uuid4()),
            "address_label": "demo_dorm",
            "items": [{"product_id": selected[0]["id"], "quantity": 1}],
        },
    )
    approval = await _api(
        client,
        "POST",
        f"/proposals/{proposal['proposal_id']}/confirmations",
        buyer,
        {"decision": "approve"},
    )
    receipt = await _api(
        client,
        "POST",
        "/orders",
        buyer,
        {
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": approval["confirmation_id"],
        },
    )
    order = await _api(client, "GET", "/orders/" + receipt["order_id"], buyer)
    payment = await _api(
        client,
        "POST",
        f"/orders/{order['id']}/payment-proposals",
        buyer,
        {"request_id": str(uuid4()), "expected_version": order["version"]},
    )
    confirmation = await _api(
        client,
        "POST",
        f"/proposals/{payment['proposal_id']}/confirmations",
        buyer,
        {"decision": "approve"},
    )
    await _api(
        client,
        "POST",
        f"/orders/{order['id']}/mock-payments",
        buyer,
        {
            "proposal_id": payment["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
    )
    login = await _api(
        client,
        "POST",
        "/auth/login",
        data={"login": "merchant", "password": DEMO_PASSWORD},
    )
    merchant = {"Authorization": "Bearer " + login["access_token"]}
    order = await _api(client, "GET", "/orders/" + order["id"], buyer)
    for action in ("ship", "deliver"):
        order = await _api(
            client,
            "POST",
            f"/merchant/orders/{order['id']}/{action}",
            merchant,
            {"expected_version": order["version"]},
        )
    if order["status"] != "DELIVERED":
        raise SmokeStopped("DELIVERED_FIXTURE_REQUIRED")
    return {
        "order_id": order["id"],
        "setup_confirmations": [
            approval["confirmation_id"],
            confirmation["confirmation_id"],
        ],
    }


class SmokeSession:
    def __init__(self, gate, state_dir):
        self.gate, self.directory = gate, Path(state_dir)
        self.app = self.client = self.provider = None
        self.run = self.thread_id = None
        self.start_request_id = None
        self.frozen = False
        self.stage_facts = []

    def require_mutable(self):
        if self.frozen:
            raise SmokeStopped("SESSION_FROZEN")

    async def initialize(
        self,
        database_url,
        price,
        *,
        encoder_factory=None,
        transport_factory=None,
        key_source=None,
    ):
        """ARM must already be durable. No Run, key or Sender exists on failure."""
        self.gate.check()
        row = self.gate.read()["tasks"][-1]
        if row["state"] != "INITIALIZING" or self.directory.exists():
            raise SmokeStopped("FRESH_ARM_AND_DIRECTORY_REQUIRED")
        self.directory.mkdir(mode=0o700)
        try:
            async with asyncio.timeout(self.gate.remaining()):
                self.settings, environment_id = await initialize_environment(
                    self.directory, database_url
                )
                self.app = create_app(self.settings)
                verify_owned(self.settings, environment_id)
                if self.gate.mode == "LIVE_DEEPSEEK" and encoder_factory is not None:
                    raise SmokeStopped("LIVE_REQUIRES_FIXED_LOCAL_BGE")
                encoder = (encoder_factory or LocalEncoder)()
                identity(encoder)
                validate_vectors(
                    encoder, encoder.encode(["Smoke initialization"], query=True), 1
                )
                self.gate.check()
                self.app.state.retrieval_encoder = encoder
                async with self.app.state.sessions.begin() as session:
                    await index_products(session, self.settings.storefront_id, encoder)
                    await index_policies(session, load_policies(), encoder)
                self.client = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.app),
                    base_url="http://127.0.0.1",
                    trust_env=False,
                    follow_redirects=False,
                    timeout=90,
                )
                login = await _api(
                    self.client,
                    "POST",
                    "/auth/login",
                    data={"login": "buyer1", "password": DEMO_PASSWORD},
                )
                self.auth = {"Authorization": "Bearer " + login["access_token"]}
                actor = await _api(self.client, "GET", "/me", self.auth)
                if actor["role"] != "buyer" or actor["store_id"] != str(
                    self.settings.storefront_id
                ):
                    raise SmokeStopped("ACTOR_STORE_MISMATCH")
                task = self.gate.current_task()
                self.setup = (
                    await prepare_delivered_fixture(
                        self.client, self.auth, task["fixture"]["original_product"]
                    )
                    if task["fixture"].get("recipe") == "fresh-legacy-delivered"
                    else {}
                )
                self.baseline = sql_facts(self.settings)
                self.gate.initialized(
                    str(environment_id),
                    self.settings.db_schema,
                    self.settings.checkpoint_schema,
                )
                self.gate.bind_actor(actor["user_id"], actor["store_id"])
                # Only now may a future authorized FD source be consumed.
                self.provider = await attach_smoke_models(
                    self.app,
                    self.gate,
                    self.directory,
                    price,
                    transport_factory,
                    key_source=key_source,
                )
                self.operator = SmokeOperator(
                    self.client, self.auth, self.gate, self.provider.ledger
                )
                self.thread_id = await self.operator.create_thread(task["architecture"])
                self.gate.bind_thread(self.thread_id)
                self.task = task
                self.gate.check()
        except BaseException:
            self.gate.stop("INITIALIZATION_STOPPED")
            await self.close()
            raise

    async def start(self, *, expected_context_version=None):
        self.require_mutable()
        self.gate.start_episode()
        message = self.task["user_request"]
        if "{delivered_order_id}" in message:
            if not self.setup.get("order_id"):
                raise SmokeStopped("OWNED_DELIVERED_ORDER_REQUIRED")
            message = message.replace("{delivered_order_id}", self.setup["order_id"])
        # Hash freezes the resolved owned input; assertions/fixture never enter the model.
        from evals.smoke_runner import digest

        self.gate.audit("resolved_input", message_sha256=digest(message))
        self.start_request_id = str(uuid4())
        self.gate.audit("start_request", request_id=self.start_request_id)
        if expected_context_version is None:
            self.run = await self.operator.start(
                self.thread_id, self.start_request_id, message
            )
        else:
            self.run = await self.operator._request(
                "POST",
                f"/api/v1/agent/threads/{self.thread_id}/runs",
                {
                    "request_id": self.start_request_id,
                    "message": message,
                    "expected_context_version": expected_context_version,
                },
            )
        self.stage_facts.append({"stage": "after-start", "facts": self.facts()})
        return self.run

    async def inspect(self):
        if self.run is None:
            if self.thread_id is None or self.start_request_id is None:
                raise SmokeStopped("RUN_NOT_STARTED")
            # A synchronous Run may have committed before a fatal response caused
            # the operator to halt. Discover only that exact request, via GET.
            thread = await self.operator._request(
                "GET", "/api/v1/agent/threads/" + self.thread_id
            )
            matches = [
                r
                for r in thread["runs"]
                if r["request_id"] == self.start_request_id
                and r["thread_id"] == self.thread_id
            ]
            if len(matches) != 1:
                raise SmokeStopped("RUN_IDENTITY_NOT_OBSERVED")
            self.run = matches[0]
        return await self.operator.inspect(self.thread_id, self.run["id"])

    async def decide(self, inspection, decision, *, operator):
        self.require_mutable()
        self.stage_facts.append(
            {
                "stage": "before-decision",
                "action_type": inspection["proposal"]["action_type"],
                "facts": self.facts(),
            }
        )
        return await self.operator.decide(
            inspection, decision=decision, operator=operator
        )

    async def resume(self, inspection, confirmation_id, request_id):
        self.require_mutable()
        self.run = await self.operator.resume(
            self.thread_id, inspection, confirmation_id, request_id
        )
        self.stage_facts.append(
            {
                "stage": "after-resume",
                "action_type": inspection["proposal"]["action_type"],
                "facts": self.facts(),
            }
        )
        return self.run

    def facts(self):
        try:
            return sql_facts(self.settings)
        except Exception:  # noqa: BLE001 - fail closed and suppress private exception text
            self.gate.stop("BUSINESS_STATE_UNKNOWN")
            raise SmokeStopped("BUSINESS_STATE_UNKNOWN") from None

    async def freeze_export_verify(self):
        """Readable even after halt: export does not resume execution or settle fees."""
        self.frozen = True  # Even an incomplete export can never reopen writes.
        inspection = await self.inspect()
        run = inspection["run"]
        events = await self.operator.events(run["id"])
        safe = {
            k: run.get(k)
            for k in (
                "id",
                "thread_id",
                "request_id",
                "status",
                "budget",
                "last_error",
                "pending_confirmation",
            )
        }
        evidence = {
            "classification": self.gate.mode,
            "stop_code": self.gate.read()["stop_code"],
            "actor_binding": {
                k: self.gate.read()["tasks"][-1][k] for k in ("user_id", "store_id")
            },
            "binding": self.gate.binding,
            "task_id": self.task["id"],
            "case_index": self.gate.case_index(),
            "run": safe,
            "product_facts": [
                f
                for f in (run.get("result") or {}).get("facts", [])
                if f.get("kind") == "product"
            ],
            "events": events,
            "baseline": self.baseline,
            "after": self.facts(),
            "stage_facts": self.stage_facts,
            "ledger": self.operator.ledger.read(),
            "setup": self.setup,
            "operator_audit": self.gate.read()["tasks"][-1]["audit"],
            "actual_supplier_invoice_cny": "UNKNOWN",
        }
        value = export_evidence(self.directory, evidence)
        return value, load_verified(self.directory)

    async def close(self):
        pairs = self.provider.clients if self.provider else []
        if self.provider:
            await self.provider.close()
            self.provider = None
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.app:
            self.app.state.multi_models = self.app.state.durable_single_model = None
            await self.app.state.engine.dispose()
            from agentmall.playground.environment import private_write

            proof = self.directory / "clients-closed.json"
            if not proof.exists():
                private_write(
                    proof,
                    {
                        "scope": "OWNED_SESSION_SDK_CLIENTS_NOT_HOST_PROCESS_EXIT",
                        "binding": self.gate.binding,
                        "execution_id": self.gate.read()["tasks"][-1]["execution_id"],
                        "closed_at": self.gate.clock(),
                        "client_pairs": len(pairs),
                        "all_closed": all(
                            p.asynchronous.is_closed and p.synchronous.is_closed
                            for p in pairs
                        ),
                        "models_detached": True,
                    },
                )

    async def cleanup(self, owner_cleanup_reference):
        """Independent operator permission, exact owned schemas; Oracle FAIL is allowed.

        This never deletes a container/volume or calls a Provider. A stopped or
        ambiguous execution remains preserved. No Live permission is renewed.
        """
        from agentmall.agents.persistence import connection_info
        from psycopg import AsyncConnection, sql

        evidence = load_verified(self.directory)
        row = self.gate.read()["tasks"][-1]
        if (
            not isinstance(owner_cleanup_reference, str)
            or len(owner_cleanup_reference) < 12
            or row["state"] != "VERIFIED"
            or self.gate.read()["stop_code"]
            or row["business_schema"] != self.settings.db_schema
            or row["checkpoint_schema"] != self.settings.checkpoint_schema
            or evidence["run"]["status"] not in {"COMPLETED", "FAILED", "PARTIAL"}
            or evidence["ledger"]["halted"]
            or any(a["state"] != "SETTLED" for a in evidence["ledger"]["attempts"])
            or any(r["has_worker"] or r["has_lock"] for r in evidence["after"]["runs"])
        ):
            raise SmokeStopped("CLEANUP_ADMISSION_REJECTED")
        if self.provider is not None or self.client is not None:
            raise SmokeStopped("CLOSE_BEFORE_CLEANUP")
        closed = json.loads((self.directory / "clients-closed.json").read_bytes())
        if (
            not closed["all_closed"]
            or closed["binding"] != self.gate.binding
            or closed["execution_id"] != row["execution_id"]
        ):
            raise SmokeStopped("CLOSE_PROOF_INVALID")
        verify_owned(self.settings, UUID(row["environment_id"]))
        names = [self.settings.db_schema, self.settings.checkpoint_schema]
        async with await AsyncConnection.connect(
            connection_info(self.settings), connect_timeout=3
        ) as conn:
            for name in names:
                await conn.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name))
                )
            await conn.commit()
            remaining = await (
                await conn.execute(
                    "SELECT nspname FROM pg_namespace WHERE nspname=ANY(%s)", (names,)
                )
            ).fetchall()
            if remaining:
                raise SmokeStopped("CLEANUP_INCOMPLETE")
        from agentmall.playground.environment import private_write

        private_write(
            self.directory / "cleanup.json",
            {
                "phase": "VERIFIED_SCHEMAS_REMOVED",
                "environment_id": row["environment_id"],
                "schemas": names,
                "owner_cleanup_reference": owner_cleanup_reference,
                "evidence_sha256": row["evidence_sha256"],
                "provider_calls": 0,
            },
        )
