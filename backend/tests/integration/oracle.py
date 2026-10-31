"""Read committed facts through a new physical connection, never an ORM identity map."""

from contextlib import contextmanager
from uuid import uuid5

from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from agentmall.agents.context import GraphResult

TABLES = (
    "products",
    "carts",
    "cart_items",
    "action_proposals",
    "confirmations",
    "idempotency_requests",
    "orders",
    "order_items",
    "payments",
    "aftersales_cases",
    "refunds",
    "support_tickets",
    "business_events",
    "agent_threads",
    "agent_runs",
    "run_events",
)


@contextmanager
def reader(env):
    settings = env[3]
    url = make_url(settings.database_url.get_secret_value())
    assert (url.host, url.port, url.database, url.username) == (
        "127.0.0.1",
        55433,
        "agentmall_test",
        "agentmall",
    )
    assert settings.db_schema.startswith("test_") and len(settings.db_schema) == 37
    engine = create_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "options": f"-csearch_path={settings.db_schema},extensions "
            "-cstatement_timeout=10000 -clock_timeout=3000",
            "application_name": f"t11:oracle:{settings.db_schema}",
        },
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            yield conn
    finally:
        engine.dispose()


def fingerprints(env, *, checkpoint=False):
    """Opaque full-row digests: detect changes without exporting passwords or private prompts."""
    with reader(env) as conn:
        tables = [*TABLES, "users", "knowledge_documents", "knowledge_chunks", "product_search"]
        if checkpoint:
            schema = env[3].checkpoint_schema
            assert schema.startswith("cp_") and len(schema) == 35
            tables += [
                f"{schema}.{name}"
                for name in (
                    "checkpoints",
                    "checkpoint_writes",
                    "checkpoint_blobs",
                    "checkpoint_migrations",
                )
            ]
        return {
            table: dict(
                conn.execute(
                    text(
                        "SELECT count(*) AS count, md5(coalesce(string_agg(to_jsonb(t)::text, '' "
                        f"ORDER BY to_jsonb(t)::text),'')) AS digest FROM {table} t"
                    )
                )
                .mappings()
                .one()
            )
            for table in tables
        }


def inspect_database(env, baseline=None):
    with reader(env) as conn:
        metadata = dict(
            conn.execute(
                text(
                    "SELECT pg_backend_pid() AS oracle_pid, clock_timestamp() AS observed_at, "
                    "current_database() AS database,current_schema() AS schema, "
                    "current_setting('server_version') AS postgres, "
                    "current_setting('transaction_isolation') AS isolation, "
                    "current_setting('transaction_read_only') AS read_only, "
                    "(SELECT extversion FROM pg_extension WHERE extname='vector') AS pgvector, "
                    "(SELECT version_num FROM alembic_version) AS revision"
                )
            )
            .mappings()
            .one()
        )
        tables = {
            t: [dict(r) for r in conn.execute(text(f"SELECT * FROM {t}")).mappings()]
            for t in TABLES
        }
        constraints = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT c.conname,c.contype,c.convalidated FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=current_schema() "
                    "AND c.contype IN ('c','u','f') ORDER BY c.conname"
                )
            ).mappings()
        ]
    violations = []

    def require(ok, rule, ident=None):
        if not ok:
            violations.append({"rule": rule, "id": str(ident) if ident else None})

    def unique(table, key, rule):
        values = [r[key] for r in tables[table] if r[key] is not None]
        require(len(values) == len(set(values)), rule)

    products = {p["id"]: p for p in tables["products"]}
    orders = {r["id"]: r for r in tables["orders"]}
    proposals = {r["id"]: r for r in tables["action_proposals"]}
    cases = {r["id"]: r for r in tables["aftersales_cases"]}
    payments = {r["id"]: r for r in tables["payments"]}
    receipts = {r["action_id"]: r for r in tables["idempotency_requests"] if r["action_id"]}
    confirmations = {r["proposal_id"]: r for r in tables["confirmations"]}
    items = tables["order_items"]
    sold = {
        pid: sum(
            i["quantity"]
            for i in items
            if i["product_id"] == pid
            and any(p["order_id"] == i["order_id"] for p in payments.values())
        )
        for pid in products
    }
    for pid, p in products.items():
        require(0 <= p["reserved"] <= p["on_hand"], "STOCK_CHECK", pid)
        pending = sum(
            i["quantity"]
            for i in items
            if i["product_id"] == pid and orders[i["order_id"]]["status"] == "PENDING_PAYMENT"
        )
        require(p["reserved"] == pending, "RESERVATION_MISMATCH", pid)
        if baseline and str(pid) in baseline["inventory"]:
            original = baseline["inventory"][str(pid)]
            require(
                p["on_hand"] + sold[pid] == original["on_hand"] + original["sold"],
                "INVENTORY_CONSERVATION_NO_REFUND_RESTOCK",
                pid,
            )
    for o in orders.values():
        p = proposals.get(o["proposal_id"])
        require(
            p is not None and (o["user_id"], o["store_id"]) == (p["actor_id"], p["store_id"]),
            "ORDER_SCOPE",
            o["id"],
        )
        relevant = [i for i in items if i["order_id"] == o["id"]]
        require(
            bool(relevant)
            and sum(i["unit_price_cents"] * i["quantity"] for i in relevant) == o["total_cents"],
            "ORDER_TOTAL",
            o["id"],
        )
        paid = [p for p in payments.values() if p["order_id"] == o["id"]]
        require(
            len(paid) == (1 if o["status"] in {"PAID", "SHIPPED", "DELIVERED", "REFUNDED"} else 0),
            "PAYMENT_ORDER_STATE",
            o["id"],
        )
        require(
            sum(
                e["aggregate_id"] == o["id"] and e["event_type"] == "ORDER_CREATED"
                for e in tables["business_events"]
            )
            == 1,
            "ORDER_CREATED_EVENT",
            o["id"],
        )
    for i in items:
        require(
            i["store_id"]
            == orders[i["order_id"]]["store_id"]
            == products[i["product_id"]]["store_id"],
            "ITEM_SCOPE",
            i["id"],
        )
    for p in payments.values():
        o = orders[p["order_id"]]
        require(
            p["amount_cents"] == o["total_cents"]
            and p["store_id"] == o["store_id"]
            and p["status"] == "SUCCEEDED",
            "PAYMENT_AMOUNT_SCOPE",
            p["id"],
        )
    for c in cases.values():
        o = orders[c["order_id"]]
        require(
            (c["user_id"], c["store_id"]) == (o["user_id"], o["store_id"])
            and c["policy_version"] == o["policy_version"],
            "CASE_SCOPE",
            c["id"],
        )
        if c["status"] == "REFUNDED":
            require(
                sum(r["case_id"] == c["id"] for r in tables["refunds"]) == 1,
                "REFUNDED_CASE_RECEIPT",
                c["id"],
            )
    for r in tables["refunds"]:
        p, c, o = payments[r["payment_id"]], cases[r["case_id"]], orders[r["order_id"]]
        require(
            r["amount_cents"] == p["amount_cents"]
            and r["order_id"] == p["order_id"] == c["order_id"]
            and r["store_id"] == p["store_id"] == c["store_id"] == o["store_id"]
            and c["status"] == o["status"] == "REFUNDED",
            "REFUND_AMOUNT_STATE_SCOPE",
            r["id"],
        )
        matching_events = [
            e
            for e in tables["business_events"]
            if e["event_type"] == "REFUND_SUCCEEDED"
            and e["action_id"] == r["action_id"]
            and e["aggregate_id"] == r["case_id"]
            and e["aggregate_type"] == "aftersales_case"
        ]
        require(len(matching_events) == 1, "REFUND_EVENT_MISSING", r["id"])
    for ticket in tables["support_tickets"]:
        if ticket["order_id"]:
            o = orders[ticket["order_id"]]
            require(
                (ticket["user_id"], ticket["store_id"]) == (o["user_id"], o["store_id"]),
                "TICKET_SCOPE",
                ticket["id"],
            )
    resources = set(orders) | set(cases) | {r["id"] for r in tables["refunds"]}
    for pid, p in proposals.items():
        c, receipt = confirmations.get(pid), receipts.get(pid)
        if p["status"] == "EXECUTED":
            require(
                c is not None
                and c["decision"] == "approve"
                and c["consumed_at"]
                and receipt
                and receipt["completed_at"]
                and receipt["result"],
                "COMPLETED_CONFIRMATION_RECEIPT",
                pid,
            )
        if c and c["consumed_at"]:
            require(
                p["status"] == "EXECUTED"
                and receipt
                and receipt["result"]
                and str(c["result_ref"]) == receipt["result"].get("resource_id")
                and c["result_ref"] in resources,
                "CONSUMED_CONFIRMATION_RESULT",
                pid,
            )
        if receipt:
            require(
                receipt["completed_at"] is not None and receipt["result"] is not None,
                "RECEIPT_COMPLETE",
                pid,
            )
    for table, key in [
        ("orders", "proposal_id"),
        ("aftersales_cases", "proposal_id"),
        ("payments", "order_id"),
        ("payments", "action_id"),
        ("refunds", "payment_id"),
        ("refunds", "case_id"),
        ("refunds", "action_id"),
        ("idempotency_requests", "action_id"),
    ]:
        unique(table, key, f"UNIQUE_{table}_{key}")
    event_keys = [
        (e["aggregate_id"], e["action_id"], e["event_type"]) for e in tables["business_events"]
    ]
    require(len(event_keys) == len(set(event_keys)), "BUSINESS_EVENT_UNIQUE")
    threads = {t["id"]: t for t in tables["agent_threads"]}
    for run in tables["agent_runs"]:
        seqs = sorted(e["seq"] for e in tables["run_events"] if e["run_id"] == run["id"])
        require(seqs == list(range(1, run["event_seq"] + 1)), "RUN_EVENT_SEQUENCE", run["id"])
        if run["status"] == "COMPLETED":
            thread = threads[run["thread_id"]]
            try:
                value = GraphResult.model_validate(run["result"])
            except ValidationError:
                require(False, "COMPLETED_RUN_RESULT_MISSING", run["id"])
                continue
            require(
                value.request_id == run["request_id"]
                and value.thread_id == run["thread_id"]
                and run["finished_at"] is not None
                and run["pending_confirmation"] is None
                and run["worker_token"] is None,
                "COMPLETED_RUN_METADATA",
                run["id"],
            )
            refs = value.model_dump(mode="json")["entity_refs"]
            intent = uuid5(run["id"], "business")
            origins = {intent, uuid5(intent, "return")}
            for p in proposals.values():
                if p["origin_request_id"] in origins and p["status"] == "EXECUTED":
                    receipt = receipts.get(p["id"])
                    kind = "order" if p["action_type"] == "CHECKOUT" else "case"
                    resource = (receipt or {}).get("result") or {}
                    require(
                        any(
                            r["kind"] == kind and r["id"] == resource.get("resource_id")
                            for r in refs
                        ),
                        "RUN_COMMITTED_RECEIPT_MISSING",
                        run["id"],
                    )
            for ref in refs:
                if ref["kind"] in {"order", "case", "ticket"}:
                    table = {
                        "order": "orders",
                        "case": "aftersales_cases",
                        "ticket": "support_tickets",
                    }[ref["kind"]]
                    found = next((r for r in tables[table] if str(r["id"]) == ref["id"]), None)
                    require(
                        found
                        and (found["user_id"], found["store_id"])
                        == (thread["user_id"], thread["store_id"]),
                        "RUN_RESULT_READABLE",
                        run["id"],
                    )
    require(all(c["convalidated"] for c in constraints), "VALIDATED_CONSTRAINTS")
    return {
        "database": metadata,
        "counts": {t: len(rows) for t, rows in tables.items()},
        "inventory": {
            str(pid): {"on_hand": p["on_hand"], "reserved": p["reserved"], "sold": sold[pid]}
            for pid, p in products.items()
        },
        "orders": [
            {k: r[k] for k in ("id", "user_id", "store_id", "status", "total_cents")}
            for r in orders.values()
        ],
        "cases": [{k: r[k] for k in ("id", "order_id", "status")} for r in cases.values()],
        "refunds": [
            {k: r[k] for k in ("id", "payment_id", "amount_cents", "case_id")}
            for r in tables["refunds"]
        ],
        "confirmations": [
            {k: r[k] for k in ("id", "proposal_id", "consumed_at", "result_ref")}
            for r in confirmations.values()
        ],
        "runs": [
            {k: r[k] for k in ("id", "thread_id", "status", "epoch", "event_seq", "budget")}
            for r in tables["agent_runs"]
        ],
        "constraints": constraints,
        "violations": violations,
    }
