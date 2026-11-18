"""Fixed V2.17 product-smoke business assertions, only after verified export.

No Agent, SDK, HTTP client, model response prose, database writes or authorization.
These new assertions do not edit or replace the original L8 Oracle.
"""

from decimal import Decimal

from evals.smoke_runner import load_verified


def score_verified(directory):
    evidence = load_verified(directory)
    ledger = evidence["ledger"]
    rows = ledger["attempts"]
    known = (
        bool(rows)
        and not ledger["halted"]
        and all(r["state"] == "SETTLED" and isinstance(r["usage"], dict) for r in rows)
    )
    result = {
        "task_id": evidence["task_id"],
        "status": "NOT_SCORED",
        "model_run_status": evidence["run"]["status"],
        "usage_state": "KNOWN" if known else "UNKNOWN",
        "held_upper_cny": str(sum((Decimal(r["held_cny"]) for r in rows), Decimal(0))),
        "actual_supplier_invoice_cny": "UNKNOWN",
        "evidence_state": "VERIFIED",
        "violations": [],
    }
    if (
        not known
        or evidence.get("stop_code")
        or evidence["run"]["status"] not in {"COMPLETED", "PARTIAL", "FAILED"}
    ):
        return result
    before, after = evidence["baseline"], evidence["after"]
    case = evidence["case_index"]
    violations = result["violations"]

    def require(condition, code):
        if not condition:
            violations.append(code)

    def added(table):
        old = {r["id"] for r in before[table]}
        return [r for r in after[table] if r["id"] not in old]

    orders, cases, confirmations = (
        added("orders"),
        added("cases"),
        added("confirmations"),
    )
    actor = evidence.get("actor_binding", {})
    require(
        bool(actor.get("user_id")) and bool(actor.get("store_id")),
        "ACTOR_BINDING_MISSING",
    )
    for table, owner in (
        ("orders", "user_id"),
        ("cases", "user_id"),
        ("confirmations", "actor_id"),
        ("proposals", "actor_id"),
    ):
        require(
            all(
                r.get(owner) == actor.get("user_id")
                and r.get("store_id") == actor.get("store_id")
                for r in added(table)
            ),
            "BUSINESS_OWNER_MISMATCH",
        )
    require(
        len(after["runs"]) == 1
        and all(
            r["id"] == evidence["run"].get("id")
            and r["thread_id"] == evidence["run"].get("thread_id")
            and r["status"] == evidence["run"]["status"]
            for r in after["runs"]
        ),
        "RUN_SQL_IDENTITY_MISMATCH",
    )
    require(evidence["run"]["status"] == "COMPLETED", "RUN_NOT_COMPLETED")
    require(after["payments"] == before["payments"], "PAYMENT_DELTA")
    require(after["refunds"] == before["refunds"], "REFUND_DELTA")
    require(after["checkpoint_count"] > 0, "CHECKPOINT_MISSING")
    require(
        not any(r["has_lock"] or r["has_worker"] for r in after["runs"]),
        "EXECUTOR_STILL_ACTIVE",
    )
    products = {p["id"]: p for p in after["products"]}
    stock_before = {p["id"]: p for p in before["products"]}
    if case == 0:
        facts = evidence.get("product_facts", [])
        ids = {f["id"] for f in facts}
        require(len(ids) == len(facts) == 2, "CANDIDATE_COUNT")
        capabilities = set()
        for fact in facts:
            p = products.get(fact["id"], {})
            data = fact["data"]
            require(
                bool(p)
                and p.get("active")
                and p.get("price_cents", 10**9) <= 40000
                and p.get("attributes", {}).get("switch") == "静音轴",
                "CANDIDATE_CONSTRAINT",
            )
            require(
                data.get("price_cents") == p.get("price_cents")
                and data.get("attributes") == p.get("attributes")
                and data.get("available") == p.get("on_hand", 0) - p.get("reserved", 0)
                and p.get("store_id")
                == evidence.get("actor_binding", {}).get("store_id")
                and all(
                    data.get(key, p.get(key)) == p.get(key)
                    for key in ("store_id", "on_hand", "reserved")
                ),
                "PRODUCT_FACT_MISMATCH",
            )
            capabilities.update(
                p.get("attributes", {}).get("connection_capabilities", [])
            )
        require({"wired", "wireless"}.issubset(capabilities), "CONNECTION_COMPARISON")
        require(
            not orders and not cases and not confirmations and not added("proposals"),
            "READ_ONLY_SIDE_EFFECT",
        )
    else:
        quantity, decisions = (2, 1) if case == 1 else (1, 2)
        require(len(orders) == 1, "ORDER_DELTA")
        require(
            len(confirmations) == decisions
            and all(
                c["decision"] == "approve" and c["consumed_at"] and c["result_ref"]
                for c in confirmations
            ),
            "INDEPENDENT_CONFIRMATIONS",
        )
        require(len(cases) == (case == 2), "CASE_DELTA")
        proposals = {p["id"]: p for p in added("proposals")}
        expected_actions = {"CHECKOUT"} if case == 1 else {"CHECKOUT", "RETURN_REQUEST"}
        require(
            len(proposals) == decisions
            and {p["action_type"] for p in proposals.values()} == expected_actions
            and len({c["proposal_id"] for c in confirmations}) == decisions
            and all(c["proposal_id"] in proposals for c in confirmations),
            "PROPOSAL_CONFIRMATION_IDENTITY",
        )
        if case == 2:
            require(
                all(
                    c["status"] == "REQUESTED"
                    and c["order_id"] == evidence.get("setup", {}).get("order_id")
                    and c["reason_code"] == "QUALITY_ISSUE"
                    for c in cases
                ),
                "RETURN_CASE_STATE",
            )
            intermediate = [
                s["facts"]
                for s in evidence.get("stage_facts", [])
                if s["stage"] == "after-resume" and s["action_type"] == "RETURN_REQUEST"
            ]
            require(
                bool(intermediate)
                and all(
                    len(s["cases"]) == len(before["cases"]) + 1
                    and len(s["orders"]) == len(before["orders"])
                    for s in intermediate
                ),
                "RETURN_BEFORE_PURCHASE",
            )
        pending = [
            s["facts"]
            for s in evidence.get("stage_facts", [])
            if s["stage"] == "before-decision"
        ]
        require(
            bool(pending)
            and all(
                len(s["orders"]) == len(before["orders"])
                and s["payments"] == before["payments"]
                and s["refunds"] == before["refunds"]
                and all(
                    p["reserved"] == stock_before[p["id"]]["reserved"]
                    and p["on_hand"] == stock_before[p["id"]]["on_hand"]
                    for p in s["products"]
                )
                for s in pending
            ),
            "ORDER_BEFORE_APPROVAL",
        )
        expected_stock = {}
        if len(orders) == 1:
            order = orders[0]
            require(
                order["status"] == "PENDING_PAYMENT"
                and order["address_label"] == "demo_dorm"
                and order["total_cents"] == quantity * 19900,
                "ORDER_STATE_OR_AMOUNT",
            )
            items = [i for i in after["items"] if i["order_id"] == order["id"]]
            require(
                len(items) == 1
                and items[0]["quantity"] == quantity
                and items[0]["unit_price_cents"] == 19900
                and "K68" in products.get(items[0]["product_id"], {}).get("name", ""),
                "ORDER_ITEMS",
            )
            for item in items:
                expected_stock[item["product_id"]] = (
                    expected_stock.get(item["product_id"], 0) + item["quantity"]
                )
            require(
                any(
                    r["action_id"] == order["proposal_id"]
                    and r["operation"] == "execute_checkout"
                    and r["result"]
                    for r in after["receipts"]
                ),
                "IDEMPOTENCY_RECEIPT",
            )
        for ident, p in products.items():
            require(
                p["on_hand"] == stock_before[ident]["on_hand"]
                and p["reserved"] - stock_before[ident]["reserved"]
                == expected_stock.get(ident, 0),
                "INVENTORY_DELTA",
            )
    result["status"] = "FAIL" if violations else "PASS"
    result["business_deltas"] = {
        "orders": len(orders),
        "cases": len(cases),
        "confirmations": len(confirmations),
        "payments": after["payments"] - before["payments"],
        "refunds": after["refunds"] - before["refunds"],
    }
    return result
