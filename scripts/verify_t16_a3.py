"""Explicit offline real-BGE/PG verification; never a Live service or paid admission."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/tests"))
from web_e2e_server import offline_boundary


async def verify(output, state, boundary, progress):
    from agentmall.infra.db import database
    from agentmall.playground.environment import initialize_environment, private_write
    from agentmall.playground.policy import source_fingerprint
    from agentmall.retrieval.embedding import REVISION, LocalEncoder
    from agentmall.retrieval.ingest import index_policies, index_products, load_policies
    from t16_a3_oracle import export, save_then_cleanup
    from t16_a3_retrieval_checks import verify as verify_retrieval
    from t16_a3_scenario import run

    settings, environment_id = await initialize_environment(
        state, os.environ["AGENTMALL_TEST_DATABASE_URL"]
    )
    progress.update(
        environment_id=str(environment_id),
        schemas=[settings.db_schema, settings.checkpoint_schema],
        schema_state="OWNED",
    )
    private_write(output / "ownership.json", progress)
    model_dir = ROOT / ".models" / REVISION
    manifest = json.loads((ROOT / "evals/data/embedding_manifest.json").read_text())
    files = []
    for name, ref in manifest["files"].items():
        data = (model_dir / name).read_bytes()
        assert (
            len(data) == ref["size_bytes"]
            and hashlib.sha256(data).hexdigest() == ref["sha256"]
        )
        files.append({"file": name, **ref})
    encoder = LocalEncoder()
    vectors = encoder.encode(["键盘", "无线静音键盘"], query=True)
    assert [len(v) for v in vectors] == [512, 512]
    assert str(next(encoder.model.parameters()).device) == "cpu"
    export(
        output / "model.json",
        {
            "model_id": encoder.model_id,
            "revision": REVISION,
            "files": files,
            "dimension": 512,
            "device": "cpu",
        },
    )
    engine, sessions = database(settings)
    try:
        async with sessions.begin() as session:
            await index_products(session, settings.storefront_id, encoder)
            await index_policies(session, load_policies(), encoder)
    finally:
        await engine.dispose()
    retrieval = await verify_retrieval(settings, encoder)
    export(output / "retrieval.json", retrieval)
    oracle = await run(settings, environment_id, encoder, state)
    assert boundary.blocked_external_attempts == 0
    oracle["offline_boundary"] = {
        "external_attempts": 0,
        "real_provider_requests": 0,
        "real_key_read": False,
    }
    oracle["memory"] = {
        k: int((Path("/sys/fs/cgroup") / k).read_text())
        for k in ["memory.current", "memory.peak", "memory.max"]
    }
    oracle["verifier_files"] = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__),
            ROOT / "backend/tests/t16_a3_oracle.py",
            ROOT / "backend/tests/t16_a3_scenario.py",
            ROOT / "backend/tests/t16_a3_retrieval_checks.py",
        ]
    }
    # Save, fsync, hash, reread and validate before any DROP. Errors retain schemas.
    sha = save_then_cleanup(
        settings,
        environment_id,
        oracle,
        output / "business-oracle.json",
        before_drop=lambda: progress.update(schema_state="UNKNOWN"),
    )
    progress["schema_state"] = "DROPPED"
    private_write(
        output / "result.json",
        {
            "status": "T16_A3_TARGETED_OFFLINE_VERIFIED",
            "source_fingerprint": source_fingerprint(),
            "environment_id": str(environment_id),
            "retrieval_cases": len(retrieval["cases"]),
            "three_turn_candidates": [
                len(stage["context"]["candidate_sets"][0]["items"])
                for stage in oracle["stages"]
            ],
            "order_id": oracle["observed"]["orders"][0]["id"],
            "order_status": "PENDING_PAYMENT",
            "payments": 0,
            "oracle_sha256": sha,
            "owned_schemas_cleaned_after_evidence": True,
            "real_provider_requests": 0,
            "live_authorization_created": False,
        },
    )
    print(json.dumps(json.loads((output / "result.json").read_text())), flush=True)


def claim_paths(output, state):
    if output.exists():
        raise FileExistsError("FRESH_OUTPUT_REQUIRED")
    # Atomic creation rejects old state before any database access.
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)


def failure_record(progress, error):
    return {
        **progress,
        "status": "BLOCKED",
        "error_type": type(error).__name__,
        "schemas_retained": {"OWNED": True, "DROPPED": False}.get(
            progress.get("schema_state")
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    claim_paths(args.output, args.state_dir)
    progress = {
        "mode": "OFFLINE_MOCK_TRANSPORT_ONLY",
        "real_provider_requests": 0,
        "real_key_read": False,
        "schema_state": "UNKNOWN",
    }
    try:
        with offline_boundary() as boundary:
            asyncio.run(verify(args.output, args.state_dir, boundary, progress))
    except Exception as exc:
        # Preserve owned state/schema and originals. Do not include DSN/exception text.
        from agentmall.playground.environment import private_write

        private_write(
            args.output / "failure.json",
            failure_record(progress, exc),
        )
        raise


if __name__ == "__main__":
    main()
