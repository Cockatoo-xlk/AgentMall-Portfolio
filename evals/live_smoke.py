"""One authorized synthetic purchase. No automatic replay or new run-id escape hatch."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from importlib.metadata import version
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from agentmall.agents.prompts import SYSTEM_PROMPT
from agentmall.infra.config import ROOT, Settings
from agentmall.infra.llm import (
    CONTEXT_BOUND,
    DOCUMENTED_REVISION,
    MAX_OUTPUT,
    MODEL_ID,
    PRICE_DATE,
    RESERVATION,
    AgentStopped,
    Budget,
    deepseek_model,
    load_live_key,
)
from agentmall.main import create_app
from agentmall.seed import DEMO_PASSWORD, seed
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

EVIDENCE = ROOT / "evals/evidence/t03-purchase.json"
SCENARIO = "帮我找一款 300 元以内的静音机械键盘，准备购买一件，送到演示宿舍地址。"


def guard_database(url):
    # Same restrictions as the existing PostgreSQL fixture, plus live server identity checks.
    p = make_url(url)
    if (
        p.drivername != "postgresql+psycopg"
        or p.database != "agentmall_test"
        or p.username != "agentmall"
        or p.host not in {"localhost", "127.0.0.1"}
        or p.query
    ):
        raise AgentStopped("DEDICATED_TEST_DATABASE_REQUIRED")
    return url


def create_isolated_schema(settings):
    if settings.test_database_url is None:
        raise AgentStopped("TEST_DATABASE_UNAVAILABLE")
    url = guard_database(settings.test_database_url.get_secret_value())
    schema = "test_" + uuid4().hex
    admin = create_engine(url)
    try:
        with admin.begin() as conn:
            if (
                conn.scalar(text("SELECT current_database()")) != "agentmall_test"
                or conn.scalar(text("SELECT current_user")) != "agentmall"
            ):
                raise AgentStopped("DATABASE_IDENTITY_MISMATCH")
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        admin.dispose()
    db = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with db.begin() as conn:
            cfg = Config(str(ROOT / "backend/alembic.ini"))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    finally:
        db.dispose()
    return settings.model_copy(
        update={"database_url": settings.test_database_url, "db_schema": schema}
    )


@asynccontextmanager
async def http_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_config=None, access_log=False, log_level="critical")
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise AgentStopped("HTTP_START_FAILED")
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=220
        ) as client:
            yield client
    finally:
        server.should_exit = True
        await task
        sock.close()


async def purchase_http(client, evidence, persist):
    login = await client.post(
        "/api/v1/auth/login", json={"login": "buyer1", "password": DEMO_PASSWORD}
    )
    if login.status_code != 200:
        raise AgentStopped("SYNTHETIC_LOGIN_FAILED")
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    response = await client.post(
        "/api/v1/agent/messages",
        headers=headers,
        json={"request_id": evidence["request_id"], "message": SCENARIO},
    )
    evidence["agent_http_status"] = response.status_code
    if response.status_code != 200:
        raise AgentStopped("AGENT_HTTP_FAILED")
    body = response.json()
    evidence["agent_response"] = body  # Synthetic scenario; facts rendered by backend.
    persist()
    if body["status"] != "proposal" or len(body["proposal_refs"]) != 1:
        raise AgentStopped("NO_PURCHASE_PROPOSAL")
    pid = UUID(body["proposal_refs"][0])
    proposal = await client.get(f"/api/v1/proposals/{pid}", headers=headers)
    if proposal.status_code != 200:
        raise AgentStopped("PROPOSAL_NOT_READABLE")
    dto = proposal.json()
    payload = dto["canonical_payload"]
    items = payload["items"]
    if (
        dto["status"] != "PENDING"
        or len(items) != 1
        or items[0]["quantity"] != 1
        or payload["total_cents"] > 30000
        or payload["address_label"] != "demo_dorm"
        or items[0]["attributes_snapshot"].get("switch") != "静音轴"
    ):
        raise AgentStopped("PROPOSAL_OUTSIDE_SYNTHETIC_INTENT")
    evidence["proposal_id"] = str(pid)
    # Explicitly synthetic user action, never an Agent tool or inferred model permission.
    evidence["confirmation_actor"] = "synthetic_user_script_via_authenticated_T02_API"
    confirmation = await client.post(
        f"/api/v1/proposals/{pid}/confirmations",
        headers=headers,
        json={"decision": "approve"},
    )
    if confirmation.status_code not in {200, 201}:
        raise AgentStopped("SYNTHETIC_CONFIRM_FAILED")
    cid = confirmation.json()["confirmation_id"]
    evidence["confirmation_id"] = cid
    persist()
    order = await client.post(
        "/api/v1/orders",
        headers={**headers, "Idempotency-Key": f"t03:order:{pid}"},
        json={"proposal_id": str(pid), "confirmation_id": cid},
    )
    if order.status_code not in {200, 201}:
        raise AgentStopped("DETERMINISTIC_ORDER_FAILED")
    evidence["order_receipt"] = order.json()
    evidence["order_id"] = order.json()["order_id"]
    replay = await client.post(
        "/api/v1/agent/messages",
        headers=headers,
        json={"request_id": evidence["request_id"], "message": SCENARIO},
    )
    if replay.status_code != 200 or replay.json()["status"] != "done":
        raise AgentStopped("AGENT_RECOVERY_FAILED")
    evidence["recovered_status"] = replay.json()["status"]
    persist()


def database_facts(settings, evidence):
    db = create_engine(
        guard_database(settings.database_url.get_secret_value()),
        connect_args={"options": f"-csearch_path={settings.db_schema}"},
    )
    try:
        with db.connect() as conn:
            result = dict(
                conn.execute(
                    text("""
                SELECT p.status proposal_status, c.decision, c.consumed_at IS NOT NULL consumed,
                c.result_ref::text confirmation_result, o.id::text order_id, o.status,
                o.total_cents, o.address_label, i.product_id::text product_id, i.quantity,
                i.unit_price_cents, pr.reserved, pr.on_hand, pr.category,
                r.result->>'order_id' receipt_order_id, e.event_type,
                (SELECT count(*) FROM orders) order_count,
                (SELECT count(*) FROM action_proposals) proposal_count,
                (SELECT count(*) FROM confirmations) confirmation_count,
                (SELECT count(*) FROM business_events) event_count
                FROM action_proposals p JOIN confirmations c ON c.proposal_id=p.id
                JOIN orders o ON o.proposal_id=p.id JOIN order_items i ON i.order_id=o.id
                JOIN products pr ON pr.id=i.product_id
                JOIN idempotency_requests r ON r.action_id=p.id AND r.operation='execute_checkout'
                JOIN business_events e ON e.action_id=p.id
                WHERE p.id=:id
            """),
                    {"id": evidence["proposal_id"]},
                )
                .mappings()
                .one()
            )
            if not (
                result["proposal_status"] == "EXECUTED"
                and result["decision"] == "approve"
                and result["consumed"]
                and result["status"] == "PENDING_PAYMENT"
                and result["confirmation_result"]
                == result["order_id"]
                == result["receipt_order_id"]
                and result["reserved"] == result["quantity"] == 1
                and result["total_cents"] == result["unit_price_cents"] <= 30000
                and result["order_count"]
                == result["proposal_count"]
                == result["confirmation_count"]
                == result["event_count"]
                == 1
                and result["event_type"] == "ORDER_CREATED"
                and result["category"] == "keyboard"
            ):
                raise AgentStopped("DATABASE_FACT_MISMATCH")
            return result
    finally:
        db.dispose()


def persist_json(path, document):
    temp = path.with_suffix(".pending")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def resume_ledger(path, max_calls, max_cost):
    """One continuation of the SAME scenario; never resets identity, usage or scope."""
    evidence = json.loads(path.read_text())
    if (
        evidence.get("status") != "LIVE_BLOCKED"
        or evidence.get("error_code") != "NO_PURCHASE_PROPOSAL"
        or evidence.get("provider") != "DeepSeek"
        or evidence.get("model_id") != MODEL_ID
        or evidence.get("price_checked_on") != PRICE_DATE
        or not re.fullmatch(r"test_[0-9a-f]{32}", evidence.get("schema", ""))
    ):
        raise AgentStopped("RESUME_SCOPE_INVALID")
    UUID(evidence["request_id"])
    attempts = evidence["attempts"]
    if not attempts or evidence["actual_http_requests"] != len(attempts):
        raise AgentStopped("RESUME_COUNT_INVALID")
    for index, attempt in enumerate(attempts, 1):
        usage = attempt["usage"]
        if not isinstance(usage, dict):
            raise AgentStopped("RESUME_USAGE_UNKNOWN")
        values = [
            usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")
        ]
        if (
            attempt["state"] != "SETTLED"
            or attempt["attempt"] != index
            or attempt["observed_response_model"] != MODEL_ID
            or any(type(v) is not int or v < 0 for v in values)
            or values[0] + values[1] != values[2]
            or values[0] > CONTEXT_BOUND
            or values[1] > MAX_OUTPUT
            or Decimal(attempt["upper_cost_cny"])
            != Decimal(values[0] * 2 + values[1] * 8) / 1_000_000
        ):
            raise AgentStopped("RESUME_USAGE_INVALID")
    budget = Budget(max_calls=max_calls, max_cost=max_cost, attempts=attempts)
    if len(attempts) >= budget.max_calls or budget.held + RESERVATION > budget.max_cost:
        raise AgentStopped("BUDGET_EXHAUSTED")
    # An exclusive permanent marker allows only one continuation, even after a crash.
    with path.with_suffix(".resume-started").open("x") as stream:
        json.dump(
            {
                "request_id": evidence["request_id"],
                "schema": evidence["schema"],
                "prior_http_requests": len(attempts),
            },
            stream,
        )
        stream.flush()
        os.fsync(stream.fileno())
    evidence.setdefault("prior_passes", []).append(
        {
            k: evidence.get(k)
            for k in (
                "status",
                "error_code",
                "trace",
                "agent_http_status",
                "agent_response",
            )
        }
    )
    evidence.update(status="CONTINUING", error_code=None, trace={})
    return evidence, budget


async def live(args):
    if not args.live:
        print("NOT_RUN: explicit --live required")
        return 2
    budget = Budget(max_calls=args.max_model_calls, max_cost=Decimal(args.max_cost_cny))
    # This price attestation is deliberately dated, not a perpetual spending authorization.
    if datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat() != PRICE_DATE:
        print("LIVE_BLOCKED: pricing/authorization date requires a fresh check")
        return 2
    if EVIDENCE.exists() and not args.resume:
        print(
            "NOT_RUN: this one authorized purchase already has a ledger; no automatic replay"
        )
        return 2
    if args.resume and not EVIDENCE.exists():
        raise AgentStopped("RESUME_LEDGER_MISSING")
    key = load_live_key()  # Only this explicit live path reads a real provider key.
    evidence = {
        "status": "STARTED",
        "provider": "DeepSeek",
        "model_id": MODEL_ID,
        "documented_revision": DOCUMENTED_REVISION,
        "immutable_revision_pinned": False,
        "observed_backend_revision": "UNKNOWN",
        "price_checked_on": PRICE_DATE,
        "price_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        "pricing": {
            "currency": "CNY",
            "unit_tokens": 1000000,
            "input_upper": 2,
            "output_upper": 8,
        },
        "sdk_versions": {
            p: version(p)
            for p in [
                "langchain",
                "langchain-core",
                "langchain-deepseek",
                "langchain-openai",
                "openai",
                "httpx",
            ]
        },
        "request_id": str(uuid4()),
        "scenario": "purchase",
        "attempts": budget.attempts,
        "actual_http_requests": 0,
        "trace": {},
        "actual_billed_cost_cny": "UNKNOWN",
    }
    if args.resume:
        evidence, budget = resume_ledger(
            EVIDENCE, args.max_model_calls, Decimal(args.max_cost_cny)
        )
    else:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        with EVIDENCE.open("x") as stream:
            stream.write('{"status":"RESERVED"}\n')
            stream.flush()
            os.fsync(stream.fileno())

    def persist():
        evidence["cost_upper_cny"] = str(budget.held)
        persist_json(EVIDENCE, evidence)

    evidence["prompt_sha256"] = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    budget.persist = persist
    persist()
    app = None
    try:
        settings = Settings()
        if args.resume:
            if settings.test_database_url is None:
                raise AgentStopped("TEST_DATABASE_UNAVAILABLE")
            guard_database(settings.test_database_url.get_secret_value())
            settings = settings.model_copy(
                update={
                    "database_url": settings.test_database_url,
                    "db_schema": evidence["schema"],
                }
            )
        else:
            settings = create_isolated_schema(settings)
        evidence["schema"] = settings.db_schema
        persist()
        app = create_app(settings)
        async with app.state.sessions.begin() as session:
            await seed(session, settings)

        async def before_send(request):
            if (
                request.url.host != "api.deepseek.com"
                or request.url.path != "/chat/completions"
                or request.method != "POST"
                or evidence["actual_http_requests"] >= len(budget.attempts)
            ):
                raise AgentStopped("UNEXPECTED_PROVIDER_HTTP")
            evidence["actual_http_requests"] += 1
            persist()  # Durable attempt evidence before transport send.

        with httpx.Client(trust_env=False, follow_redirects=False) as sync_client:
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                event_hooks={"request": [before_send]},
            ) as async_client:
                app.state.agent_model = deepseek_model(
                    key, http_client=sync_client, http_async_client=async_client
                )
                app.state.agent_budget_factory = lambda: budget
                app.state.agent_trace_factory = lambda: evidence["trace"]
                async with http_server(app) as client:
                    await purchase_http(client, evidence, persist)
        evidence["database_facts"] = database_facts(settings, evidence)
        if (
            not evidence["trace"].get("model_final_received")
            or evidence["trace"].get("error_code")
            or not any(
                t["name"] == "search_products" and t["ok"]
                for t in evidence["trace"].get("tools", [])
            )
        ):
            raise AgentStopped("MODEL_LOOP_INCOMPLETE")
        evidence["status"] = "LIVE_LLM_VERIFIED"
        evidence["cost_estimate_kind"] = (
            "usage_verified_peak_cache_miss_upper_bound_not_invoice"
        )
        return 0
    except AgentStopped as exc:
        evidence["status"], evidence["error_code"] = "LIVE_BLOCKED", exc.code
        return 2
    except Exception as exc:  # noqa: BLE001 -- sanitized experiment boundary
        evidence["status"], evidence["error_code"] = "LIVE_BLOCKED", type(exc).__name__
        return 2
    finally:
        if app:
            await app.state.engine.dispose()
        persist()
        print(
            json.dumps(
                {
                    k: evidence.get(k)
                    for k in [
                        "status",
                        "error_code",
                        "actual_http_requests",
                        "cost_upper_cny",
                        "proposal_id",
                        "order_id",
                        "schema",
                    ]
                },
                ensure_ascii=False,
            )
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["purchase"], required=True)
    parser.add_argument("--max-model-calls", type=int, default=8)
    parser.add_argument("--max-cost-cny", default="3")
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--resume", action="store_true", help="One continuation using original ledger"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(live(args))
    except AgentStopped as exc:
        print("LIVE_BLOCKED: " + exc.code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
