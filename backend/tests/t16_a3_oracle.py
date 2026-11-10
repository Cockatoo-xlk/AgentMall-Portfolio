"""Offline verification only: independent reads and fail-closed evidence cleanup."""

import hashlib
import json
import os
from pathlib import Path

from psycopg import sql
from psycopg.rows import dict_row

from agentmall.agents.persistence import checkpoint_config, checkpoint_saver, connection_info
from agentmall.playground.environment import verify_owned


def capture(settings):
    """New physical connection, one read-only repeatable snapshot; no ORM state."""
    import psycopg

    with psycopg.connect(
        connection_info(settings),
        row_factory=dict_row,
        options=f"-csearch_path={settings.db_schema},extensions -cstatement_timeout=10000",
        application_name="agentmall:t16-a3-independent-oracle",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        metadata = conn.execute(
            "SELECT pg_backend_pid() oracle_pid, clock_timestamp() observed_at, "
            "current_schema() schema, current_setting('transaction_read_only') read_only, "
            "current_setting('transaction_isolation') isolation"
        ).fetchone()
        result = {"metadata": metadata}
        tables = [
            "orders",
            "order_items",
            "action_proposals",
            "confirmations",
            "idempotency_requests",
            "business_events",
            "payments",
            "aftersales_cases",
            "refunds",
            "support_tickets",
            "agent_threads",
            "run_events",
        ]
        for table in tables:
            result[table] = conn.execute(
                sql.SQL("SELECT * FROM {} ORDER BY id").format(sql.Identifier(table))
            ).fetchall()
        result["products"] = conn.execute(
            "SELECT id,store_id,name,category,price_cents,attributes,on_hand,reserved,"
            "active,catalog_version "
            "FROM products ORDER BY id"
        ).fetchall()
        result["agent_runs"] = conn.execute(
            "SELECT id,thread_id,request_id,status,event_seq,epoch,budget,result,finished_at,"
            "pending_confirmation,worker_token IS NULL worker_released FROM agent_runs ORDER BY id"
        ).fetchall()
        result["advisory_locks"] = conn.execute(
            "SELECT count(*) n FROM pg_locks WHERE locktype='advisory'"
        ).fetchone()["n"]
    return json.loads(json.dumps(result, default=str))


async def checkpoints(settings, thread_id, run_ids):
    """Official deserializer on a distinct explicitly read-only connection."""
    from uuid import UUID

    result = []
    async with checkpoint_saver(settings) as saver:
        async with saver.conn.transaction():
            await saver.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            row = await (await saver.conn.execute("SHOW transaction_read_only")).fetchone()
            for run_id in run_ids:
                cp = await saver.aget_tuple(checkpoint_config(UUID(thread_id), UUID(run_id)))
                if cp is None:
                    raise ValueError("CHECKPOINT_MISSING")
                result.append(
                    {
                        "run_id": run_id,
                        "next": cp.checkpoint["channel_values"]["next"],
                        "pending_writes": len(cp.pending_writes or []),
                        "read_only": row["transaction_read_only"],
                    }
                )
            count = await (
                await saver.conn.execute("SELECT count(*) n FROM checkpoints")
            ).fetchone()
    return result, count["n"]


def validate(data, expected, cp):
    violations = []

    def require(condition, rule):
        if not condition and rule not in violations:
            violations.append(rule)

    require(
        data["metadata"]["read_only"] == "on"
        and data["metadata"]["isolation"] == "repeatable read",
        "READ_ONLY",
    )
    require(len(data["orders"]) == 1, "SINGLE_ORDER")
    require(
        len(data["order_items"])
        == len(data["action_proposals"])
        == len(data["confirmations"])
        == 1,
        "SINGLE_ACTION",
    )
    require(
        all(not data[t] for t in ["payments", "aftersales_cases", "refunds", "support_tickets"]),
        "NO_OTHER_BUSINESS",
    )
    if (
        not data["orders"]
        or not data["order_items"]
        or not data["action_proposals"]
        or not data["confirmations"]
    ):
        return violations
    order, item, proposal, confirmation = [
        data[t][0] for t in ["orders", "order_items", "action_proposals", "confirmations"]
    ]
    require(
        order["status"] == "PENDING_PAYMENT"
        and order["proposal_id"] == expected["proposal_id"] == proposal["id"],
        "ORDER_PROPOSAL",
    )
    require(
        item["order_id"] == order["id"]
        and item["product_id"] == expected["product_id"]
        and item["quantity"] == expected["quantity"]
        and item["unit_price_cents"] == expected["price_cents"]
        and order["total_cents"] == item["quantity"] * item["unit_price_cents"],
        "ORDER_ITEM",
    )
    require(
        proposal["action_type"] == "CHECKOUT" and proposal["status"] == "EXECUTED",
        "PROPOSAL_EXECUTED",
    )
    quote = proposal["canonical_payload"]
    canonical = json.dumps(
        quote, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    require(
        proposal["payload_hash"] == hashlib.sha256(canonical.encode()).hexdigest(), "PROPOSAL_HASH"
    )
    original = expected["proposal_snapshot"]
    require(
        all(proposal.get(k) == v for k, v in original.items() if k not in {"status", "updated_at"}),
        "IMMUTABLE_PROPOSAL",
    )
    require(
        order["address_label"] == quote["address_label"] == expected["address_label"]
        and order["currency"] == quote["currency"] == "CNY"
        and order["policy_version"] == quote["policy_version"]
        and order["total_cents"] == quote["total_cents"],
        "ORDER_QUOTE",
    )
    require(len(quote["items"]) == 1, "QUOTE_ITEMS")
    if quote["items"]:
        quoted = quote["items"][0]
        require(
            quoted["product_id"] == item["product_id"] == expected["product_id"]
            and quoted["quantity"] == item["quantity"] == expected["quantity"]
            and quoted["unit_price_cents"] == item["unit_price_cents"] == expected["price_cents"]
            and quoted["name_snapshot"] == item["name_snapshot"]
            and quoted["attributes_snapshot"] == item["attributes_snapshot"],
            "QUOTE_ITEMS",
        )
    require(
        confirmation["id"] == expected["confirmation_id"]
        and confirmation["proposal_id"] == proposal["id"]
        and confirmation["decision"] == "approve"
        and bool(confirmation["consumed_at"])
        and confirmation["result_ref"] == order["id"],
        "CONFIRMATION",
    )
    require(
        order["user_id"] == proposal["actor_id"] == confirmation["actor_id"] == expected["user_id"]
        and order["store_id"]
        == item["store_id"]
        == proposal["store_id"]
        == confirmation["store_id"]
        == expected["store_id"],
        "SCOPE",
    )
    products = {p["id"]: p for p in data["products"]}
    require(set(products) == set(expected["inventory"]), "INVENTORY_IDENTITIES")
    for pid, p in products.items():
        original = expected["inventory"].get(pid, {})
        reserved = sum(i["quantity"] for i in data["order_items"] if i["product_id"] == pid)
        require(0 <= p["reserved"] <= p["on_hand"] and p["reserved"] == reserved, "RESERVATION")
        if pid == expected["product_id"]:
            require(
                p["price_cents"] == expected["price_cents"]
                and p["catalog_version"] == quote["items"][0]["catalog_version"]
                and p["name"] == item["name_snapshot"]
                and p["attributes"] == item["attributes_snapshot"],
                "QUOTED_PRODUCT",
            )
            require(
                p["on_hand"] == original.get("on_hand") and p["reserved"] == expected["quantity"],
                "TARGET_STOCK",
            )
            require(p.get("store_id", expected["store_id"]) == expected["store_id"], "SCOPE")
        else:
            require(
                p["on_hand"] == original.get("on_hand")
                and p["reserved"] == original.get("reserved"),
                "NON_TARGET_STOCK",
            )
    receipts = [r for r in data["idempotency_requests"] if r["operation"] == "execute_checkout"]
    require(len(receipts) == 1, "SINGLE_RECEIPT")
    if receipts:
        receipt = receipts[0]
        require(
            receipt["action_id"] == proposal["id"]
            and bool(receipt["completed_at"])
            and receipt["result"]["resource_id"] == order["id"],
            "RECEIPT_RESULT",
        )
    require(
        all(
            r["actor_id"] == expected["user_id"]
            and r["store_id"] == expected["store_id"]
            and r["completed_at"]
            and r["result"]
            for r in data["idempotency_requests"]
        ),
        "RECEIPT_SCOPE",
    )
    events = [e for e in data["business_events"] if e["event_type"] == "ORDER_CREATED"]
    require(
        len(events) == 1
        and events[0]["aggregate_id"] == order["id"]
        and events[0]["action_id"] == proposal["id"],
        "BUSINESS_EVENT",
    )
    require(
        len(data["agent_threads"]) == 1
        and data["agent_threads"][0]["id"] == expected["thread_id"]
        and data["agent_threads"][0]["user_id"] == expected["user_id"]
        and data["agent_threads"][0]["store_id"] == expected["store_id"],
        "THREAD_SCOPE",
    )
    runs = {r["id"]: r for r in data["agent_runs"]}
    require(set(runs) == set(expected["run_ids"]), "RUN_IDENTITIES")
    for rid, run in runs.items():
        require(
            run["status"] == "COMPLETED" and run["thread_id"] == expected["thread_id"],
            "RUN_COMPLETE",
        )
        seqs = sorted(e["seq"] for e in data["run_events"] if e["run_id"] == rid)
        require(seqs == list(range(1, run["event_seq"] + 1)), "EVENT_SEQUENCE")
    require(all(e["run_id"] in runs for e in data["run_events"]), "EVENT_SCOPE")
    require(
        len(cp) == len(runs)
        and {c["run_id"] for c in cp} == set(runs)
        and all(
            c["next"] == "done" and c["pending_writes"] == 0 and c["read_only"] == "on" for c in cp
        ),
        "CHECKPOINT",
    )
    return violations


def export(path, payload):
    """Never overwrite evidence; fsync raw JSON and its SHA before allowing cleanup."""
    path = Path(path)
    content = (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    sha = hashlib.sha256(content).hexdigest()
    with os.fdopen(
        os.open(str(path) + ".sha256", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        stream.write(sha + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    # File fsync does not persist directory entries, including newly created
    # output directories. Fail closed if any directory synchronization fails.
    for directory in [path.parent, *path.parent.parents]:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("EVIDENCE_HASH_MISMATCH")
    return sha


def drop_owned(settings, environment_id):
    import psycopg

    verify_owned(settings, environment_id)
    with psycopg.connect(connection_info(settings)) as conn:
        for schema in [settings.checkpoint_schema, settings.db_schema]:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def cleanup_from_verified(settings, environment_id, path, sha, before_drop=None):
    path = Path(path)
    content = path.read_bytes()
    if (
        hashlib.sha256(content).hexdigest() != sha
        or Path(str(path) + ".sha256").read_text().strip() != sha
    ):
        raise ValueError("EVIDENCE_HASH_MISMATCH")
    data = json.loads(content)
    if (
        data["status"] != "PASS"
        or data["violations"]
        or validate(data["observed"], data["expected"], data["checkpoints"])
    ):
        raise ValueError("ORACLE_NOT_PASSED")
    if data["environment_id"] != str(environment_id) or data["schemas"] != [
        settings.db_schema,
        settings.checkpoint_schema,
    ]:
        raise ValueError("ORACLE_OWNERSHIP_MISMATCH")
    if before_drop:
        before_drop()
    drop_owned(settings, environment_id)


def save_then_cleanup(settings, environment_id, payload, path, before_drop=None):
    if (
        payload["status"] != "PASS"
        or payload["violations"]
        or validate(payload["observed"], payload["expected"], payload["checkpoints"])
    ):
        raise ValueError("ORACLE_NOT_PASSED")
    sha = export(path, payload)
    cleanup_from_verified(settings, environment_id, path, sha, before_drop)
    return sha
