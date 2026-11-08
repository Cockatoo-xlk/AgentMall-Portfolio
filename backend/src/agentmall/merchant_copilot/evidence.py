"""Deterministic claims and priority. Model prose cannot become a business fact."""

from .tools import fingerprint

ACTIONS = {
    "SHIP": "进入订单管理，核对后手动发货",
    "REVIEW": "进入售后管理，由商家独立批准或拒绝",
    "RESTOCK": "核对商品与实际库存，按原商品流程处理",
    "CHECK_INDEX": "查看商品索引任务，由商家手动检查或重试",
}


def permitted(e):
    if e["kind"] == "order" and e["status"] == "PAID":
        return "SHIP"
    if e["kind"] == "case" and e["status"] == "REQUESTED":
        return "REVIEW"
    if e["kind"] == "product" and e["status"] == "ACTIVE" and e["facts"]["available"] <= 5:
        return "RESTOCK"
    if e["kind"] == "index_job" and e["status"] in ["FAILED", "PENDING", "RUNNING", "STALE"]:
        return "CHECK_INDEX"
    return None


def priority(e):
    rule = (
        0
        if permitted(e) == "REVIEW"
        else 1
        if e["kind"] == "index_job" and e["status"] == "FAILED"
        else 2
        if permitted(e) == "SHIP"
        else 3
        if e["kind"] == "product" and e["facts"]["available"] == 0
        else 4
    )
    return rule, str(e["facts"].get("created_at", "")), e["key"]


def summarize(facts, scopes):
    rows = list(facts.values())

    def read(tool):
        return any(s["tool"] == tool for s in scopes.values())

    return {
        "paid_orders": sum(e["kind"] == "order" and e["status"] == "PAID" for e in rows)
        if read("list_merchant_orders")
        else None,
        "requested_cases": sum(e["kind"] == "case" and e["status"] == "REQUESTED" for e in rows)
        if read("list_merchant_after_sales")
        else None,
        "out_of_stock": sum(
            e["kind"] == "product" and e["status"] == "ACTIVE" and e["facts"]["available"] == 0
            for e in rows
        )
        if read("list_merchant_products")
        else None,
        "low_stock": sum(
            e["kind"] == "product" and e["status"] == "ACTIVE" and 0 < e["facts"]["available"] <= 5
            for e in rows
        )
        if read("list_merchant_products")
        else None,
        "index_pending": sum(
            e["kind"] == "index_job" and e["status"] in ["PENDING", "RUNNING", "FAILED", "STALE"]
            for e in rows
        )
        if read("list_catalog_index_jobs")
        else None,
        "by_status": {
            kind: {
                status: sum(e["kind"] == kind and e["status"] == status for e in rows)
                for status in sorted({e["status"] for e in rows if e["kind"] == kind})
            }
            for kind in ["order", "case", "product", "index_job"]
        },
        "coverage": list(scopes.values()),
        "scope": "OBSERVED_RECORDS_ONLY",
        "low_stock_threshold": 5,
    }


def validate_advice(advice, facts, case_id):
    seen = set()
    suggestions = []
    for selected in advice.selections:
        e = facts.get(selected.evidence_id)
        if e is None or permitted(e) != selected.action or selected.evidence_id in seen:
            raise ValueError("UNSUPPORTED_EVIDENCE")
        seen.add(selected.evidence_id)
        if e["fingerprint"] != fingerprint(
            e["kind"], e["id"], e["status"], e["version"], e["facts"]
        ):
            raise ValueError("CORRUPT_EVIDENCE")
        if e["kind"] == "order":
            claim = f"订单处于PAID，金额{e['facts']['total_cents']}分；可以核对后发货。"
        elif e["kind"] == "case":
            claim = f"售后处于REQUESTED，原因代码{e['facts']['reason_code']}；尚未审核。"
        elif e["kind"] == "product":
            claim = f"商品可用库存{e['facts']['available']}，低库存阈值5；不是自动补货授权。"
        else:
            claim = f"索引任务有效状态{e['status']}，请求商品版本{e['version']}；没有自动执行。"
        suggestions.append(
            {
                "type": selected.action,
                "content": claim,
                "evidence_key": e["key"],
                "record_id": e["id"],
                "status": e["status"],
                "version": e["version"],
                "read_at": e["read_at"],
                "action": ACTIONS[selected.action],
                "risk": "只读建议；记录可能变化，实际操作需重新核对",
                "priority_rule": (
                    "待审核Case优先，再失败索引、已支付待发货、缺货及低库存；同类按创建时间/ID排序"
                ),
            }
        )
    suggestions.sort(key=lambda s: priority(facts[s["evidence_key"]]))
    draft = None
    case = facts.get("case:" + str(case_id)) if case_id else None
    policies = [
        e for e in facts.values() if e["kind"] == "policy" and e["facts"]["case_id"] == str(case_id)
    ]
    if case and case["status"] == "REQUESTED" and policies:
        if any(p["facts"]["policy_version"] != case["facts"]["policy_version"] for p in policies):
            raise ValueError("UNSUPPORTED_POLICY")
        prefix = (
            "感谢您反馈商品情况。" if advice.draft_tone == "EMPATHETIC" else "已查看本次退货申请。"
        )
        draft = {
            "case_id": case["id"],
            "case_version": case["version"],
            "policy_version": case["facts"]["policy_version"],
            "evidence_keys": [case["key"], *[p["key"] for p in policies]],
            "text": prefix
            + (
                f"当前状态{case['status']}，原因代码{case['facts']['reason_code']}；"
                f"参考公开政策{case['facts']['policy_version']}，仍需核验实物与申请材料。"
                "此为AI审核说明草稿，未经商家执行；不表示已批准或拒绝。"
            ),
        }
    return suggestions, draft
