"""Original domain reads and explicit privacy projections in a read-only snapshot."""

import hashlib
import json
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder

from agentmall.aftersales import service as cases
from agentmall.catalog.models import Product
from agentmall.catalog_operations import service as catalog
from agentmall.catalog_operations.models import CatalogIndexJob
from agentmall.catalog_operations.schemas import Filters
from agentmall.identity.service import require_merchant
from agentmall.infra.errors import DomainError
from agentmall.mcp_gateway import contracts as mcp
from agentmall.mcp_gateway.domain import read_domain
from agentmall.orders import service as orders
from agentmall.orders.lifecycle import owned_order
from agentmall.orders.schemas import OrderFilters
from agentmall.retrieval.public_policy import get_public_return_policy

from .contracts import CaseID, OrderID, PageArgs, PolicyArgs


def fingerprint(kind, ident, status, version, facts):
    return hashlib.sha256(
        json.dumps(
            jsonable_encoder([kind, ident, status, version, facts]),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def evidence(kind, ident, status, version, facts, read_at):
    facts = jsonable_encoder(facts)
    return {
        "key": f"{kind}:{ident}",
        "kind": kind,
        "id": str(ident),
        "status": status,
        "version": version,
        "read_at": read_at,
        "facts": facts,
        "fingerprint": fingerprint(kind, ident, status, version, facts),
    }


def order_facts(order):
    return {
        k: getattr(order, k)
        for k in [
            "total_cents",
            "currency",
            "created_at",
            "paid_at",
            "shipped_at",
            "delivered_at",
            "policy_version",
        ]
    } | {
        "items": [
            {
                k: getattr(i, k)
                for k in ["product_id", "name_snapshot", "unit_price_cents", "quantity"]
            }
            for i in order.items
        ]
    }


def case_facts(case):
    return {
        k: getattr(case, k)
        for k in [
            "order_id",
            "reason_code",
            "policy_version",
            "created_at",
            "reviewed_at",
            "received_at",
            "refunded_at",
        ]
    } | {
        "eligibility_at_request": case.eligibility_snapshot.model_dump(mode="json"),
        "has_review_note": bool(case.review_reason),
    }


class DomainReader:
    def __init__(self, app, session, actor, *, max_pages=2, adapter=None):
        require_merchant(actor)
        self.app, self.session, self.actor = app, session, actor
        self.max_pages, self.adapter = max_pages, adapter
        self.remaining = 200
        self.page_reads = 0
        self.scopes = {}
        self.read_at = datetime.now(UTC).isoformat()

    async def shared(self, name, args):
        if self.adapter:
            return await self.adapter.read(self.app, self.session, self.actor, name, args)
        return await read_domain(self.app, self.session, self.actor, name, args)

    async def list_page(self, name, args):
        if name == "list_merchant_orders":
            page = await orders.list_merchant_orders(self.session, self.actor, OrderFilters(**args))
            return page.items, page.next_cursor
        if name in ["list_merchant_after_sales", "list_merchant_products"]:
            tool, schema = (
                ("list_merchant_after_sales", mcp.Cases)
                if name.endswith("after_sales")
                else ("list_merchant_catalog", mcp.MerchantCatalog)
            )
            page = await self.shared(tool, schema(**args))
            return page["items"], page["next_cursor"]
        if args["status"] and args["status"] not in [
            "PENDING",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "STALE",
        ]:
            raise ValueError("Invalid job status")
        return await catalog.list_rows(self.session, self.actor, CatalogIndexJob, Filters(**args))

    async def project(self, name, row):
        if name == "list_merchant_orders":
            return evidence(
                "order", row.id, row.status, row.version, order_facts(row), self.read_at
            )
        if name == "list_merchant_after_sales":
            # The shared MCP summary intentionally omits buyer text and eligibility.
            ident = row.id if hasattr(row, "id") else row["id"]
            return await self.detail("case", ident)
        if name == "list_merchant_products":
            v = jsonable_encoder(row)
            facts = {
                k: v[k]
                for k in [
                    "name",
                    "category",
                    "price_cents",
                    "on_hand",
                    "reserved",
                    "available",
                    "active",
                    "index_status",
                ]
            }
            return evidence(
                "product",
                v["id"],
                "ACTIVE" if v["active"] else "INACTIVE",
                v["catalog_version"],
                facts,
                self.read_at,
            )
        value = await catalog.job_view(self.session, self.actor, row)
        return evidence(
            "index_job",
            row.id,
            value["effective_status"],
            row.requested_version,
            value,
            self.read_at,
        )

    async def detail(self, kind, ident):
        if kind == "order":
            row = await orders.order_view(
                self.session, await owned_order(self.session, self.actor, ident, merchant=True)
            )
            return evidence(kind, row.id, row.status, row.version, order_facts(row), self.read_at)
        if kind == "case":
            row = await cases.get_case(self.session, self.actor, ident, merchant=True)
            return evidence(kind, row.id, row.status, row.version, case_facts(row), self.read_at)
        model = Product if kind == "product" else CatalogIndexJob
        row = await catalog.owned(self.session, model, self.actor, ident)
        if kind == "product":
            return await self.project(
                "list_merchant_products",
                await catalog.product_view(self.session, row, self.app.state.retrieval_encoder),
            )
        if kind == "index_job":
            return await self.project("list_catalog_index_jobs", row)
        raise ValueError("Unsupported evidence kind")

    async def policy(self, args):
        version, eligibility, order_id = "demo-v1", None, None
        if args.case_id:
            case = await cases.owned_case(self.session, self.actor, args.case_id, merchant=True)
            order = await owned_order(self.session, self.actor, case.order_id, merchant=True)
            if order.policy_version != case.policy_version:
                raise DomainError(409, "POLICY_VERSION_CHANGED", "政策版本不一致，不能草拟审核说明")
            version, order_id = case.policy_version, order.id
            eligibility = (
                await cases.eligibility_for(self.session, order, case.reason_code)
            ).model_dump(mode="json")
        policy = await get_public_return_policy(self.session, self.actor, policy_version=version)
        # Group policy sections by document ID to preserve one stable reference per document.
        documents = {}
        for item in policy["items"]:
            doc = documents.setdefault(
                str(item["document_id"]),
                {
                    "policy_version": version,
                    "sections": [],
                    "order_id": order_id,
                    "case_id": args.case_id,
                    "current_new_request_eligibility": eligibility,
                },
            )
            doc["sections"].append({k: item[k] for k in ["title", "text", "source_uri"]})
        return [
            evidence("policy", ident, "PUBLIC_EFFECTIVE", version, value, self.read_at)
            for ident, value in documents.items()
        ]

    async def read(self, call):
        require_merchant(self.actor)
        if call.name == "get_applicable_policy":
            return await self.policy(PolicyArgs.model_validate(call.arguments))
        if call.name in ["get_merchant_order", "get_merchant_after_sales"]:
            args = (OrderID if call.name.endswith("order") else CaseID).model_validate(
                call.arguments
            )
            return [
                await self.detail(
                    "order" if isinstance(args, OrderID) else "case",
                    args.order_id if isinstance(args, OrderID) else args.case_id,
                )
            ]
        args = PageArgs.model_validate(call.arguments).model_dump()
        cursor = args["cursor"]
        items, complete = [], False
        for _ in range(self.max_pages):
            if self.remaining == 0:
                break
            args.update(cursor=cursor, limit=min(args["limit"], self.remaining))
            rows, cursor = await self.list_page(call.name, args)
            self.page_reads += 1
            self.remaining -= len(rows)
            items.extend([await self.project(call.name, row) for row in rows])
            if cursor is None:
                complete = True
                break
        key = call.name + ":" + (args["status"] or "ALL")
        self.scopes[key] = {
            "tool": call.name,
            "status_filter": args["status"],
            "scanned": len(items),
            "complete": complete,
            "next_cursor": str(cursor) if cursor else None,
            "started_cursor": str(call.arguments.get("cursor"))
            if call.arguments.get("cursor")
            else None,
        }
        # Starting mid-pagination is never a complete Store/filter count.
        if self.scopes[key]["started_cursor"]:
            self.scopes[key]["complete"] = False
        return items
