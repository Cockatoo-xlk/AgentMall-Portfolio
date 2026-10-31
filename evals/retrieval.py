"""Fixed-label, isolated PostgreSQL retrieval evaluation. No chat/remote embedding calls."""

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from agentmall.catalog.models import Product
from agentmall.identity.service import ActorContext
from agentmall.infra.config import Settings
from agentmall.infra.errors import DomainError
from agentmall.main import create_app
from agentmall.retrieval.embedding import ROOT, LocalEncoder
from agentmall.retrieval.ingest import (
    digest,
    index_policies,
    index_products,
    load_policies,
)
from agentmall.retrieval.schemas import ProductQuery
from agentmall.retrieval.search import CONFIG, retrieve_policies, retrieve_products
from agentmall.retrieval.tokenize import TOKENIZER_VERSION
from agentmall.seed import DEMO_PASSWORD, seed
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


class FixtureEncoder:
    """Non-semantic constant vectors. Scores are pipeline evidence only."""

    model_id, revision, dimension = "agentmall/fixture", "unit-v1", 512

    def encode(self, texts, *, query=False):
        return [[1.0] + [0.0] * 511 for _ in texts]


def freeze_identity():
    paths = [
        "evals/data/retrieval_dev.jsonl",
        "evals/data/retrieval_test.jsonl",
        "evals/data/embedding_manifest.json",
    ]
    paths += [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "fixtures/policies").glob("*.json"))
    ]
    paths += ["backend/src/agentmall/seed.py", "backend/uv.lock", "evals/retrieval.py"]
    paths += [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "backend/src/agentmall/retrieval").glob("*.py"))
    ]
    return {
        "dataset_version": "t07-v1.1",
        "tokenizer": TOKENIZER_VERSION,
        "config": asdict(CONFIG),
        "corpus": "seed-12-skus + 10-policies + ACL/stale/inactive distractors; low stock SKU01=1",
        "hashes": {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths
        },
    }


def metrics(cases):
    answer = [c for c in cases if c["relevant_ids"]]
    no_answer = [c for c in cases if not c["relevant_ids"]]

    def recall(c):
        return len(set(c["result_ids"]) & set(c["relevant_ids"])) / len(
            c["relevant_ids"]
        )

    def reciprocal(c):
        return next(
            (
                1 / (i + 1)
                for i, x in enumerate(c["result_ids"])
                if x in c["relevant_ids"]
            ),
            0,
        )

    latencies = sorted(c["latency_ms"] for c in cases)
    return {
        "queries": len(cases),
        "answer_queries": len(answer),
        "no_answer_queries": len(no_answer),
        "recall_at_5": statistics.mean(map(recall, answer)) if answer else None,
        "mrr_at_5": statistics.mean(map(reciprocal, answer)) if answer else None,
        "no_answer_correct": sum(
            not c["result_ids"] and c["error"] == c["expected_error"] for c in no_answer
        ),
        "acl_or_version_or_filter_leaks": sum(c["violations"] for c in cases),
        "unexpected_errors": sum(c["error"] != c["expected_error"] for c in cases),
        "citation_resolved": sum(c["citation_resolved"] for c in cases),
        "total_hits": sum(len(c["result_ids"]) for c in cases),
        "latency_median_ms": statistics.median(latencies),
        "latency_p95_ms": latencies[max(0, int(len(latencies) * 0.95 + 0.999) - 1)],
    }


async def create_order(client, headers, product):
    proposal = await client.post(
        "/api/v1/checkout/proposals",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "request_id": str(uuid4()),
            "proposal_slot": "checkout",
            "address_label": "demo_dorm",
            "items": [{"product_id": str(product), "quantity": 1}],
        },
    )
    assert proposal.status_code == 201, proposal.text
    proposal = proposal.json()
    confirmation = await client.post(
        f"/api/v1/proposals/{proposal['proposal_id']}/confirmations",
        headers=headers,
        json={"decision": "approve"},
    )
    assert confirmation.status_code == 201, confirmation.text
    order = await client.post(
        "/api/v1/orders",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation.json()["confirmation_id"],
        },
    )
    assert order.status_code == 201, order.text
    return order.json()["order_id"]


def snapshot(db):
    with db.connect() as c:
        return digest(
            {
                table: [
                    str(r[0])
                    for r in c.execute(
                        text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id")
                    )
                ]
                for table in (
                    "orders",
                    "order_items",
                    "products",
                    "payments",
                    "refunds",
                    "aftersales_cases",
                    "business_events",
                )
            }
        )


async def evaluate(args):
    identity = freeze_identity()
    freeze_path = ROOT / "evals/data/retrieval-freeze.json"
    if args.freeze:
        if args.split != "dev":
            raise ValueError("Freeze only after dev, before held-out test")
        freeze_path.open("x").write(
            json.dumps(
                dict(frozen_at=datetime.now(UTC).isoformat(), **identity),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    if args.split == "test":
        frozen = json.loads(freeze_path.read_text())
        assert {k: v for k, v in frozen.items() if k != "frozen_at"} == identity, (
            "Frozen configuration/dataset mismatch"
        )
    output = (
        args.output or ROOT / f"evals/evidence/t07/{args.split}-{args.embedding}.json"
    )
    if output.exists():
        raise FileExistsError("Retain previous evidence; choose a new --output")
    settings = Settings()
    url = settings.test_database_url.get_secret_value()
    parsed = make_url(url)
    if (
        parsed.drivername,
        parsed.host,
        parsed.port,
        parsed.database,
        parsed.username,
    ) != (
        "postgresql+psycopg",
        "127.0.0.1",
        55433,
        "agentmall_test",
        "agentmall",
    ) or parsed.query:
        raise ValueError(
            "Evaluation is confined to the isolated T07 database at 127.0.0.1:55433"
        )
    encoder = LocalEncoder() if args.embedding == "real" else FixtureEncoder()
    schema = "test_" + uuid4().hex
    admin = create_engine(url)
    db = create_engine(
        url, connect_args={"options": f"-csearch_path={schema},extensions"}
    )
    app = create_app(
        settings.model_copy(
            update={"database_url": settings.test_database_url, "db_schema": schema}
        )
    )
    started = time.perf_counter()
    report = {
        "status": "RAG_REAL_EMBEDDING"
        if args.embedding == "real"
        else "RAG_FIXTURE_VECTOR",
        "executed_at": datetime.now(UTC).isoformat(),
        "split": args.split,
        "modes": args.modes.split(","),
        "embedding": {
            "model_id": encoder.model_id,
            "revision": encoder.revision,
            "dimension": encoder.dimension,
        },
        "manifest": identity,
        "parameters": vars(args) | {"output": str(output)},
        "schema": schema,
        "cases": [],
        "summaries": {},
    }
    created = False
    try:
        with admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        cfg = Config(str(ROOT / "backend/alembic.ini"))
        with db.begin() as c:
            cfg.attributes["connection"] = c
            command.upgrade(cfg, "head")
            command.check(cfg)
            report["database"] = {
                "postgres": c.scalar(text("SHOW server_version")),
                "pgvector": c.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                ),
                "search_path": c.scalar(text("SHOW search_path")),
                "migration": "0005",
            }
        store = settings.storefront_id
        foreign = UUID("00000000-0000-0000-0000-000000000002")
        async with app.state.sessions.begin() as session:
            await seed(session, settings)
            for kind in ("foreign", "inactive", "stale", "soldout"):
                session.add(
                    Product(
                        id=uuid5(store, "distractor:" + kind),
                        store_id=foreign if kind == "foreign" else store,
                        name="静音机械键盘 专供",
                        category="keyboard",
                        attributes={"noise": "安静"},
                        description="静音低噪声宿舍机械键盘",
                        price_cents=1,
                        active=kind != "inactive",
                        on_hand=0 if kind == "soldout" else 20,
                        reserved=0,
                        catalog_version=1,
                    )
                )
            await session.flush()
            index_start = time.perf_counter()
            report["indexed_products"] = await index_products(session, store, encoder)
            await index_products(session, foreign, encoder)
            report["indexed_chunks"] = await index_policies(
                session, load_policies(), encoder
            )
            report["index_ms"] = (time.perf_counter() - index_start) * 1000
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"login": "buyer1", "password": DEMO_PASSWORD},
            )
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            orders = {
                alias: await create_order(
                    client, headers, uuid5(store, "synthetic-sku-02")
                )
                for alias in ("owned-order", "unknown-policy-order")
            }
        with db.begin() as c:
            c.execute(text("ALTER TABLE orders DISABLE TRIGGER immutable_snapshot"))
            c.execute(
                text("UPDATE orders SET policy_version='unknown' WHERE id=:id"),
                {"id": orders["unknown-policy-order"]},
            )
            c.execute(text("ALTER TABLE orders ENABLE TRIGGER immutable_snapshot"))
            c.execute(
                text("UPDATE products SET catalog_version=2 WHERE id=:id"),
                {"id": uuid5(store, "distractor:stale")},
            )
            c.execute(
                text("UPDATE products SET on_hand=1 WHERE id=:id"),
                {"id": uuid5(store, "synthetic-sku-01")},
            )
        report["order_aliases"] = orders
        before = snapshot(db)
        cases = [
            json.loads(line)
            for line in (ROOT / f"evals/data/retrieval_{args.split}.jsonl")
            .read_text()
            .splitlines()
        ]
        for mode in report["modes"]:
            if mode not in {"lexical", "vector", "hybrid"}:
                raise ValueError("Unknown mode")
            results = []
            for case in cases:
                result = {
                    **case,
                    "mode": mode,
                    "result_ids": [],
                    "hits": [],
                    "error": None,
                    "violations": 0,
                    "citation_resolved": 0,
                }
                actor = ActorContext(
                    uuid5(store, case["actor"]), "buyer", UUID(case["store_id"])
                )
                query_start = time.perf_counter()
                try:
                    async with app.state.sessions.begin() as session:
                        if case["kind"] == "product":
                            filters = ProductQuery(
                                query=case["query"],
                                mode=mode,
                                **case["required_filters"],
                            )
                            hits = await retrieve_products(
                                session, actor, case["query"], filters, encoder
                            )
                        else:
                            hits = await retrieve_policies(
                                session,
                                actor,
                                UUID(orders[case["order_id"]]),
                                case["query"],
                                mode,
                                encoder,
                            )
                        result["hits"] = [h.model_dump(mode="json") for h in hits]
                        result["result_ids"] = [str(h.id) for h in hits]
                except DomainError as exc:
                    result["error"] = exc.code
                result["latency_ms"] = (time.perf_counter() - query_start) * 1000
                result["violations"] = len(
                    set(result["result_ids"]) & set(case["forbidden_result_ids"])
                )
                with db.connect() as c:
                    for h in result["hits"]:
                        if case["kind"] == "product":
                            row = (
                                c.execute(
                                    text(
                                        "SELECT p.*,s.source_version FROM products p JOIN product_search s ON s.product_id=p.id WHERE p.id=:id"
                                    ),
                                    {"id": h["id"]},
                                )
                                .mappings()
                                .one()
                            )
                            invalid = (
                                str(row["store_id"]) != case["store_id"]
                                or not row["active"]
                                or row["catalog_version"] != row["source_version"]
                                or row["on_hand"] <= row["reserved"]
                                or (
                                    "category" in case["required_filters"]
                                    and row["category"]
                                    != case["required_filters"]["category"]
                                )
                                or (
                                    "max_price_cents" in case["required_filters"]
                                    and row["price_cents"]
                                    > case["required_filters"]["max_price_cents"]
                                )
                            )
                            result["violations"] += bool(invalid)
                            result["citation_resolved"] += (
                                h["source_uri"] == f"/api/v1/products/{h['id']}"
                            )
                        else:
                            row = (
                                c.execute(
                                    text(
                                        "SELECT d.*,k.section_id,k.text FROM knowledge_chunks k JOIN knowledge_documents d ON k.document_id=d.id WHERE k.id=:id"
                                    ),
                                    {"id": h["id"]},
                                )
                                .mappings()
                                .one()
                            )
                            result["violations"] += bool(
                                str(row["store_id"]) != case["store_id"]
                                or row["visibility"] != "public"
                                or row["version"] != "demo-v1"
                                or case["actor"] != "buyer1"
                            )
                            result["citation_resolved"] += (
                                h["source_uri"]
                                == row["source_uri"] + "#" + row["section_id"]
                                and h["text"] == row["text"]
                            )
                results.append(result)
            report["cases"].extend(results)
            report["summaries"][mode] = metrics(results)
        report["business_state_unchanged"] = snapshot(db) == before
        assert report["business_state_unchanged"]
        report["elapsed_seconds"] = time.perf_counter() - started
        output.parent.mkdir(parents=True, exist_ok=True)
        output.open("x").write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "summaries": report["summaries"],
                    "output": str(output),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await app.state.engine.dispose()
        db.dispose()
        if created:
            with admin.begin() as c:
                c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--modes", default="lexical,vector,hybrid")
    parser.add_argument("--embedding", choices=["fixture", "real"], required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--output", type=Path)
    asyncio.run(evaluate(parser.parse_args()))


if __name__ == "__main__":
    main()
