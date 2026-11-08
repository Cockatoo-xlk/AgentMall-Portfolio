"""Frozen Expanded benchmark: real local models, original owned fixtures and domain services."""

import argparse
import asyncio
import hashlib
import json
import math
import platform
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from agentmall.catalog.models import Product
from agentmall.catalog_operations import service as operations
from agentmall.catalog_operations.schemas import (
    Approve,
    Command,
    DraftCreate,
    DraftEdit,
    ProductData,
    VersionCommand,
)
from agentmall.identity.models import User
from agentmall.identity.service import actor_for
from agentmall.retrieval.embedding import ROOT, LocalEncoder
from agentmall.retrieval.ingest import (
    PRODUCT_INDEX_VERSION,
    digest,
    index_products,
    product_text,
)
from agentmall.retrieval.models import ProductSearch
from agentmall.retrieval.ranking import reranked_products
from agentmall.retrieval.reranker import LocalReranker, verify_files
from agentmall.retrieval.schemas import ProductQuery
from agentmall.retrieval.search import CONFIG, retrieve_products
from agentmall.seed import seed
from sqlalchemy import select, text

from evals.retrieval import snapshot
from evals.retrieval_quality import category_metrics, per_query, summarize

DATA = ROOT / "evals/data/expanded-retrieval-v1"
PIPELINES = ["lexical", "dense", "hybrid", "hybrid_reranker"]


class CountingEncoder:
    def __init__(self, inner):
        self.inner = inner
        self.model_id = inner.model_id
        self.revision = inner.revision
        self.dimension = inner.dimension
        self.calls = 0
        self.batches = 0
        self.ms = 0

    def encode(self, texts, *, query=False):
        self.calls += 1
        self.batches += math.ceil(len(texts) / 16)
        start = time.perf_counter()
        try:
            return self.inner.encode(texts, query=query)
        finally:
            self.ms += (time.perf_counter() - start) * 1000


def load_dataset():
    manifest = json.loads((DATA / "manifest.json").read_text())
    result = {}
    if (
        hashlib.sha256(
            (ROOT / "backend/src/agentmall/catalog/data/expanded-v1.json").read_bytes()
        ).hexdigest()
        != manifest["catalog_sha256"]
    ):
        raise ValueError("Catalog mismatch")
    for split in ["dev", "test"]:
        blob = (DATA / (split + ".jsonl")).read_bytes()
        if hashlib.sha256(blob).hexdigest() != manifest["splits"][split]:
            raise ValueError("Frozen query hash mismatch")
        rows = [json.loads(line) for line in blob.decode().splitlines()]
        if len(rows) != manifest["planned_queries"][split] or len(
            {r["id"] for r in rows}
        ) != len(rows):
            raise ValueError("Incomplete planned split")
        for r in rows:
            ProductQuery(query=r["query"], **r["filters"])
            if r["expected_no_answer"] != (not bool(r["judgments"])):
                raise ValueError("Judgment mismatch")
            keys = [j["product_key"] for j in r["judgments"]]
            if len(keys) != len(set(keys)) or any(
                type(j["grade"]) is not int
                or not 1 <= j["grade"] <= 3
                or not j["rationale"]
                for j in r["judgments"]
            ):
                raise ValueError("Invalid grades")
        result[split] = rows
    return manifest, result


def source_identity(git_sha):
    paths = sorted(
        [
            *ROOT.glob("backend/src/agentmall/retrieval/*.py"),
            *ROOT.glob("backend/src/agentmall/catalog/*.py"),
            ROOT / "backend/src/agentmall/seed.py",
            ROOT / "evals/expanded_retrieval.py",
            ROOT / "evals/retrieval_quality.py",
            ROOT / "evals/data/reranker_manifest.json",
            ROOT / "evals/data/embedding_manifest.json",
            *DATA.glob("*"),
            ROOT / "backend/src/agentmall/catalog/data/expanded-v1.json",
        ]
    )
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    return {
        "git_base_sha": git_sha,
        "worktree_dirty": True,
        "source_tree_sha256": digest(hashes),
        "source_files": hashes,
        "binding": "Experiment ran modified worktree; base SHA is NOT the modified-source commit. Containing delivery commit preserves these exact files.",
    }


async def publish_dynamic(env):
    app = env[2]
    async with app.state.sessions.begin() as s:
        user = await s.get(User, uuid5(env[3].storefront_id, "merchant"))
        merchant = actor_for(user, env[3])
    data = ProductData(
        name="宁阅 N27 动态上架显示器",
        category="monitor",
        description="合成演示商品。27英寸2560×1440 IPS显示器，USB-C和HDMI接口，100Hz，用于办公阅读。",
        attributes={
            "screen_inches": "27",
            "resolution": "2560×1440",
            "panel": "IPS",
            "ports": "USB-C / HDMI",
            "refresh_rate": "100Hz",
            "usage": "办公阅读",
        },
        price_cents=109900,
        on_hand=12,
    )
    draft, _ = await operations.create_draft(
        app, merchant, DraftCreate(request_id=uuid4(), data=data)
    )
    for op in ["submit", "approve", "publish"]:
        command = (
            Approve(
                request_id=uuid4(), expected_version=draft["version"], reviewed=True
            )
            if op == "approve"
            else VersionCommand(request_id=uuid4(), expected_version=draft["version"])
        )
        draft, _ = await operations.change_draft(
            app, merchant, UUID(draft["id"]), op, command
        )
    assert draft["status"] == "PUBLISHED"
    job, _ = await operations.run_index(
        app,
        merchant,
        UUID(draft["index_job_id"]),
        Command(request_id=uuid4()),
    )
    assert job["status"] == "SUCCEEDED", job
    return merchant, draft


async def prepare(env, encoder):
    app = env[2]
    app.state.retrieval_encoder = encoder
    async with app.state.sessions.begin() as s:
        await seed(s, env[3], profile="expanded")
        for n in range(1, 8):
            s.add(
                Product(
                    id=uuid5(env[3].storefront_id, "v210-sentinel:" + str(n)),
                    store_id=UUID(int=901) if n == 1 else env[3].storefront_id,
                    name=f"隔离 Z90{n} 手机",
                    category="smartphone",
                    description=f"合成检索安全探针 Z90{n}，不是可购买业务演示。",
                    attributes={"storage": "128GB", "usage": "检索安全"},
                    price_cents=100000,
                    on_hand=0 if n == 3 else 5,
                    reserved=0,
                    active=n != 2,
                    catalog_version=1,
                )
            )
        await s.flush()
        await index_products(s, env[3].storefront_id, encoder)
        await index_products(s, UUID(int=901), encoder)
        for n in [4, 5, 6, 7]:
            product = await s.get(
                Product, uuid5(env[3].storefront_id, "v210-sentinel:" + str(n))
            )
            entry = await s.get(ProductSearch, product.id)
            if n == 4:
                product.catalog_version += 1
            elif n == 5:
                product.description += " 修改后未重建内容"
            elif n == 6:
                entry.embedding_model, entry.embedding_revision = (
                    "agentmall/fixture",
                    "unit-v1",
                )
            elif n == 7:
                entry.tokenizer_version = "stale-tokenizer-for-safety-test"
    return await publish_dynamic(env)


async def audit_hits(session, actor, filters, hits):
    violations = []
    for hit in hits:
        row = (
            await session.execute(
                select(Product, ProductSearch)
                .join(ProductSearch)
                .where(Product.id == hit.id)
            )
        ).first()
        if row is None:
            violations.append("STALE_INDEX")
        elif (
            row[0].store_id != actor.store_id
            or not row[0].active
            or (filters.in_stock and row[0].on_hand <= row[0].reserved)
            or (filters.category and row[0].category != filters.category)
            or (
                filters.max_price_cents is not None
                and row[0].price_cents > filters.max_price_cents
            )
        ) or not independent_attributes(row[0], filters):
            violations.append("ACL_STOCK_OR_FILTER")
        elif (
            row[1].source_version != row[0].catalog_version
            or row[1].content_hash != digest(product_text(row[0]))
            or row[1].tokenizer_version != PRODUCT_INDEX_VERSION
        ):
            violations.append("STALE_INDEX")
        elif (
            row[1].embedding_model != "BAAI/bge-small-zh-v1.5"
            or row[1].embedding_revision != encoder_revision()
        ):
            violations.append("STALE_MODEL")
    return violations


def independent_attributes(product, filters):
    # Deliberately inspect fetched facts, not retrieval's SQL predicate builder.
    from agentmall.catalog.capabilities import connection_matches
    from agentmall.catalog.categories import KIND_ATTRIBUTES

    a = product.attributes
    if product.id in filters.exclude_product_ids:
        return False
    if filters.noise_preference and a.get("noise") != "较安静":
        return False
    if filters.screen_inches and a.get("screen_inches") != filters.screen_inches:
        return False
    if filters.layout and a.get("size") != filters.layout:
        return False
    if filters.usage and filters.usage not in a.get("usage", ""):
        return False
    if filters.activity and a.get("usage") != "公路车骑行":
        return False
    if not connection_matches(a, filters.connection, filters.excluded_connections):
        return False
    if filters.keyboard_type:
        switches = (
            ["薄膜"]
            if filters.keyboard_type == "membrane"
            else ["静音轴", "线性轴", "段落轴", "青轴", "茶轴", "红轴"]
        )
        if a.get("switch") not in switches:
            return False
    if filters.product_kind:
        category, field, term = KIND_ATTRIBUTES[filters.product_kind]
        if product.category != category or term not in a.get(field, ""):
            return False
    return True


def encoder_revision():
    from agentmall.retrieval.embedding import REVISION

    return REVISION


async def execute_case(env, actor, case, arm, encoder, reranker, dynamic):
    grades = {j["product_id"] or dynamic: j["grade"] for j in case["judgments"]}
    mode = {"dense": "vector", "hybrid_reranker": "hybrid"}.get(arm, arm)
    filters = ProductQuery(query=case["query"], mode=mode, **case["filters"])
    calls, batches, embed_ms, rerank_calls, rerank_batches = (
        encoder.calls,
        encoder.batches,
        encoder.ms,
        reranker.calls,
        reranker.batches,
    )
    start = time.perf_counter()
    status = "OK"
    error = None
    hits = []
    pool = []
    rank_ms = None
    retrieval_ms = None
    try:
        async with env[2].state.sessions.begin() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout=10000"))
            if arm == "hybrid_reranker":
                result = await reranked_products(
                    session, actor, case["query"], filters, encoder, reranker
                )
                hits = result["items"]
                pool = result["candidate_ids"]
                rank_ms = result["rerank_ms"]
                retrieval_ms = result["retrieval_ms"]
            else:
                full = await retrieve_products(
                    session,
                    actor,
                    case["query"],
                    filters,
                    encoder,
                    replace(CONFIG, top_k=20),
                )
                pool = [str(h.id) for h in full]
                hits = full[:5]
                retrieval_ms = (time.perf_counter() - start) * 1000
            violations = await audit_hits(session, actor, filters, hits)
    except Exception as exc:  # noqa: BLE001 - retain every planned query failure, never drop it.
        status = "ERROR"
        error = getattr(exc, "code", type(exc).__name__)
        violations = []
    row = {
        "id": case["id"],
        "query": case["query"],
        "category": case["category"],
        "tags": case["tags"],
        "filters": case["filters"],
        "architecture": arm,
        "status": status,
        "error": error,
        "grades": grades,
        "annotation_basis": case["annotation_basis"],
        "result_ids": [str(h.id) for h in hits] if status == "OK" else None,
        "candidate_ids": pool if status == "OK" else None,
        "top5": [
            {
                "id": str(h.id),
                "name": h.product.name,
                "category": h.product.category,
                "price_cents": h.product.price_cents,
                "catalog_version": h.source_version,
            }
            for h in hits
        ]
        if status == "OK"
        else [],
        "pipeline_ms": (time.perf_counter() - start) * 1000 if status == "OK" else None,
        "retrieval_ms": retrieval_ms if status == "OK" else None,
        "query_embedding_ms": encoder.ms - embed_ms if status == "OK" else None,
        "rerank_ms": rank_ms if status == "OK" else None,
        "embedding_calls": encoder.calls - calls if status == "OK" else None,
        "embedding_forward_batches": encoder.batches - batches
        if status == "OK"
        else None,
        "reranker_calls": reranker.calls - rerank_calls if status == "OK" else None,
        "reranker_forward_batches": reranker.batches - rerank_batches
        if status == "OK"
        else None,
        "violations": violations,
    }
    row["metrics"] = per_query(row)
    return row


async def lifecycle_check(env, merchant, draft, encoder):
    ident = UUID(draft["published_product_id"])
    from agentmall.identity.service import ActorContext

    actor = ActorContext(
        uuid5(env[3].storefront_id, "buyer1"), "buyer", env[3].storefront_id
    )

    async def contains():
        async with env[2].state.sessions.begin() as s:
            hits = await retrieve_products(
                s,
                actor,
                "宁阅 N27",
                ProductQuery(query="宁阅 N27", category="monitor"),
                encoder,
            )
            return ident in {h.id for h in hits}

    assert await contains()
    revised, _ = await operations.create_draft(
        env[2],
        merchant,
        VersionCommand(request_id=uuid4(), expected_version=1),
        target_id=ident,
    )
    changed_data = ProductData.model_validate(revised["data"])
    old_price = changed_data.price_cents
    changed_data.price_cents += 100
    revised, _ = await operations.change_draft(
        env[2],
        merchant,
        UUID(revised["id"]),
        "edit",
        DraftEdit(
            request_id=uuid4(), expected_version=revised["version"], data=changed_data
        ),
    )
    for op in ["submit", "approve", "publish"]:
        body = (
            Approve(
                request_id=uuid4(), expected_version=revised["version"], reviewed=True
            )
            if op == "approve"
            else VersionCommand(request_id=uuid4(), expected_version=revised["version"])
        )
        revised, _ = await operations.change_draft(
            env[2], merchant, UUID(revised["id"]), op, body
        )
    assert not await contains()
    job, _ = await operations.run_index(
        env[2],
        merchant,
        UUID(revised["index_job_id"]),
        Command(request_id=uuid4()),
    )
    assert job["status"] == "SUCCEEDED"
    assert await contains()
    async with env[2].state.sessions.begin() as s:
        assert (await s.get(Product, ident)).price_cents == old_price + 100
        version = (await s.get(Product, ident)).catalog_version
    await operations.deactivate(
        env[2],
        merchant,
        ident,
        VersionCommand(request_id=uuid4(), expected_version=version),
    )
    assert not await contains()
    async with env[2].state.sessions.begin() as session:
        version = (await session.get(Product, ident)).catalog_version
    republish, _ = await operations.create_draft(
        env[2],
        merchant,
        VersionCommand(request_id=uuid4(), expected_version=version),
        target_id=ident,
    )
    for operation in ["submit", "approve", "publish"]:
        payload = (
            Approve(
                request_id=uuid4(), expected_version=republish["version"], reviewed=True
            )
            if operation == "approve"
            else VersionCommand(
                request_id=uuid4(), expected_version=republish["version"]
            )
        )
        republish, _ = await operations.change_draft(
            env[2], merchant, UUID(republish["id"]), operation, payload
        )
    assert not await contains()
    job, _ = await operations.run_index(
        env[2], merchant, UUID(republish["index_job_id"]), Command(request_id=uuid4())
    )
    assert job["status"] == "SUCCEEDED" and await contains()
    return {
        "new_dynamic_published_indexed": True,
        "version_change_old_index_hidden": True,
        "explicit_reindex_current_visible": True,
        "deactivated_hidden": True,
        "price_change_versioned": True,
        "republished_requires_fresh_index": True,
    }


async def evaluate(args):
    manifest, datasets = load_dataset()
    source = source_identity(args.git_sha)
    start = time.perf_counter()
    encoder = CountingEncoder(LocalEncoder())
    embedding_load = (time.perf_counter() - start) * 1000
    reranker = LocalReranker()
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from conftest import env as fixture

    manager = fixture.__wrapped__()
    env = await anext(manager)
    report = {
        "schema_version": 1,
        "evidence_class": "REAL_LOCAL_BGE",
        "reranker_evidence": "REAL_LOCAL_CROSS_ENCODER",
        "executed_at": datetime.now(UTC).isoformat(),
        "source": source,
        "dataset": manifest,
        "environment": {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "device": "cpu",
            "threads_per_model": 2,
        },
        "models": {
            "embedding": {
                "model_id": encoder.model_id,
                "revision": encoder.revision,
                "dimension": 512,
                "cold_load_ms": embedding_load,
            },
            "reranker": {
                "model_id": reranker.model_id,
                "revision": reranker.revision,
                "cold_load_ms": reranker.load_ms,
                "max_tokens": 256,
                "batch_size": 4,
                "max_candidates": 20,
                "raw_scores": "logits, not probabilities",
            },
        },
        "splits": {},
        "provider_requests": 0,
        "key_reads": 0,
        "limitations": [
            "SINGLE_ANNOTATOR synthetic small corpus; not independent human labels or significance",
            "Reranker cannot recover a missing candidate or remove false positives without an abstention rule",
            "Git base identifies modified worktree ancestry; source contents hash identifies executed code",
        ],
    }
    try:
        merchant, draft = await prepare(env, encoder)
        dynamic = draft["published_product_id"]
        report["dynamic_binding"] = {
            "product_key": "dynamic:monitor",
            "product_id": dynamic,
            "status": "PUBLISHED",
            "index_status": "SUCCEEDED",
            "operator": "TEST_OPERATOR; separate submit/approve/publish/index through original domain services",
        }
        probe = encoder.encode(["独立512维校验"], query=True)[0]
        assert len(probe) == 512 and abs(sum(v * v for v in probe) - 1) < 1e-4
        before = snapshot(env[1])
        report["database"] = {
            "postgres": None,
            "pgvector": None,
            "catalog_products": 128,
            "reserved_before": 0,
            "read_only_snapshot_before": before,
        }
        with env[1].connect() as conn:
            report["database"].update(
                {
                    "postgres": conn.scalar(text("SHOW server_version")),
                    "pgvector": conn.scalar(
                        text(
                            "SELECT extversion FROM pg_extension WHERE extname='vector'"
                        )
                    ),
                    "catalog_products": conn.scalar(
                        text("SELECT count(*) FROM products")
                    ),
                }
            )
        for split in ["dev", "test"]:
            rows = []
            for index, case in enumerate(datasets[split]):
                order = PIPELINES[index % 4 :] + PIPELINES[: index % 4]
                for arm in order:
                    from agentmall.identity.service import ActorContext

                    row = await execute_case(
                        env,
                        ActorContext(
                            uuid5(env[3].storefront_id, "buyer1"),
                            "buyer",
                            env[3].storefront_id,
                        ),
                        case,
                        arm,
                        encoder,
                        reranker,
                        dynamic,
                    )
                    rows.append(row)
                print(
                    json.dumps(
                        {
                            "split": split,
                            "query": case["id"],
                            "arms": 4,
                            "completed": sum(r["status"] == "OK" for r in rows),
                        }
                    ),
                    flush=True,
                )
            report["splits"][split] = {
                "cases": rows,
                "summaries": {
                    arm: summarize([r for r in rows if r["architecture"] == arm])
                    for arm in PIPELINES
                },
                "per_category": {
                    arm: category_metrics([r for r in rows if r["architecture"] == arm])
                    for arm in PIPELINES
                },
            }
            for case in datasets[split]:
                c = next(
                    r
                    for r in rows
                    if r["id"] == case["id"] and r["architecture"] == "hybrid"
                )
                d = next(
                    r
                    for r in rows
                    if r["id"] == case["id"] and r["architecture"] == "hybrid_reranker"
                )
                if c["status"] == "OK" and d["status"] == "OK":
                    assert set(c["candidate_ids"]) == set(d["candidate_ids"])
        report["database"]["read_only_snapshot_after"] = snapshot(env[1])
        assert before == report["database"]["read_only_snapshot_after"]
        with env[1].connect() as conn:
            report["database"].update(
                {
                    table: conn.scalar(text("SELECT count(*) FROM " + table))
                    for table in ["orders", "payments", "action_proposals"]
                }
            )
            assert all(
                report["database"][t] == 0
                for t in ["orders", "payments", "action_proposals"]
            )
        report["lifecycle"] = await lifecycle_check(env, merchant, draft, encoder)
        report["model_integrity"] = {
            "embedding": json.loads(
                (ROOT / "evals/data/embedding_manifest.json").read_text()
            ),
            "reranker": verify_files(ROOT / ".models" / reranker.revision),
        }
        report["status"] = (
            "REAL_LOCAL_RETRIEVAL_COMPLETED"
            if all(
                r["status"] == "OK" and not r["violations"]
                for s in report["splits"].values()
                for r in s["cases"]
            )
            else "REAL_LOCAL_RETRIEVAL_FAILED"
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        assert report["status"] == "REAL_LOCAL_RETRIEVAL_COMPLETED"
    finally:
        reranker.close()
        await manager.aclose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--git-sha", required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("New output required; previous experiments immutable")
    import re

    if not re.fullmatch("[0-9a-f]{40}", args.git_sha):
        raise ValueError("Exact verified Git base required")
    from evals.fixtures import offline_boundary

    with offline_boundary():
        asyncio.run(evaluate(args))


if __name__ == "__main__":
    main()
