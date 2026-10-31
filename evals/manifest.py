"""Content-addressed, fail-closed freeze and one sealed fixture execution claim."""

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from agentmall.agents.budgets import Limits
from agentmall.agents.specialist_tools import ALLOWLISTS, SCHEMAS
from agentmall.agents.specialists.runner import PROMPTS, SINGLE_PROMPT
from agentmall.agents.supervisor import SYSTEM_PROMPT

from evals.fixtures import ROOT, settings_for_eval
from evals.schema import canonical, load_tasks

FROZEN = ROOT / "evals/config/frozen.yaml"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def source_hashes():
    paths = set()
    for pattern in (
        "backend/src/**/*.py",
        "backend/migrations/**/*.py",
        "backend/tests/*.py",
        "backend/tests/integration/*.py",
        "evals/*.py",
        "evals/data/agent_*.jsonl",
        "fixtures/policies/*.json",
        "evals/data/embedding_manifest.json",
        "backend/requirements*.txt",
        "backend/pyproject.toml",
        "backend/uv.lock",
    ):
        paths.update(ROOT.glob(pattern))
    return {
        str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in sorted(paths)
        if p.is_file()
    }


def build_manifest():
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(
        settings_for_eval().database_url.get_secret_value(), poolclass=NullPool
    )
    try:
        with engine.connect() as connection:
            database = dict(
                connection.execute(
                    text(
                        "SELECT current_database() AS name, "
                        "current_setting('server_version') AS version, "
                        "(SELECT extversion FROM pg_extension WHERE extname='vector') AS pgvector"
                    )
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    price = json.loads((ROOT / "evals/evidence/t12/provider-research.json").read_text())
    tasks = {
        s: load_tasks(ROOT / f"evals/data/agent_{s}.jsonl") for s in ("dev", "test")
    }
    prompts = {"single": SINGLE_PROMPT, "supervisor": SYSTEM_PROMPT, **PROMPTS}
    sources = source_hashes()
    return {
        "version": 1,
        "frozen_at": datetime.now(UTC).isoformat(),
        "git_base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_note": "Source hashes bind uncommitted T12 implementation; final evidence commit recorded separately",
        "source_hashes": sources,
        "source_bundle_hash": digest(canonical(sources).encode()),
        "datasets": {
            s: {
                "count": len(v),
                "sha256": sources[f"evals/data/agent_{s}.jsonl"],
                "task_ids": [t.task_id for t in v],
            }
            for s, v in tasks.items()
        },
        "oracle_hash": sources["evals/oracles.py"],
        "prompt_hashes": {k: digest(v.encode()) for k, v in prompts.items()},
        "tool_union": sorted(SCHEMAS),
        "specialist_allowlists": {k: sorted(v) for k, v in ALLOWLISTS.items()},
        "tool_schema_hash": digest(
            canonical({k: s.model_json_schema() for k, s in SCHEMAS.items()}).encode()
        ),
        "provider": {
            "name": "DeepSeek",
            "model_id": "deepseek-flash",
            "model_revision": "MUTABLE_ALIAS",
            "seed": "UNSUPPORTED",
            "temperature": 0,
            "thinking": "disabled",
            "max_output_tokens": 2048,
            "hidden_retries": 0,
            "price_snapshot": price,
            "price_recheck_required_after_hours": 24,
            "actual_live_requests": 0,
        },
        "sdk_versions": {
            n: importlib.metadata.version(n)
            for n in (
                "langchain-deepseek",
                "langchain-core",
                "langchain",
                "langgraph",
                "langgraph-checkpoint-postgres",
                "openai",
                "psycopg",
                "sqlalchemy",
                "httpx",
            )
        },
        "database": database
        | {
            "host": "127.0.0.1",
            "port": 55433,
            "isolation": "fresh test_/cp_ per Episode",
        },
        "embedding": {
            "fixture": {
                "model": "agentmall/fixture",
                "revision": "unit-v1",
                "dimension": 512,
                "semantic_quality": "NOT_MEASURED",
            },
            "live": {
                "model": "BAAI/bge-small-zh-v1.5",
                "revision": "7999e1d3359715c523056ef9478215996d62a620",
                "local_files_only": True,
            },
        },
        "rag": {
            "implementation_hash": digest(
                canonical(
                    {k: v for k, v in sources.items() if "/retrieval/" in k}
                ).encode()
            ),
            "same_encoder_and_data_within_each_pair": True,
        },
        "episode_limits": asdict(Limits()),
        "transport_request_bytes_limit": 65536,
        "input_reservation_per_call": 1048576,
        "input_episode_limit": 12582912,
        "retries": "zero SDK retries; one existing schema repair counts in same durable budget; recovery uses same Run and request IDs",
        "time_basis": "fixed task logical clock for business rules; real monotonic machine latency and 90s whole Episode execution cap; real PG audit timestamps",
        "pairing": {
            "unit": ["task_id", "repetition_id"],
            "order": "alternating AB/BA",
            "bootstrap_unit": "task_id",
            "bootstrap_repetitions": 2000,
            "seed": 20261029,
        },
        "sealed_fixture": {
            "repeats": 1,
            "episodes": 80,
            "claim_file": "evals/evidence/t12/sealed-fixture-claim.json",
        },
        "pilot": {
            "status": "NOT_RUN",
            "task_ids": [
                "eval_dev_A1_01",
                "eval_dev_A2_01",
                "eval_dev_B1_01",
                "eval_dev_B2_01",
                "eval_dev_B1_03",
            ],
            "requires_new_user_budget_authorization": True,
        },
        "annotation": "single Codex author, not independent multiple annotators",
        "live_ledger": "evals/live/t12-experiment-ledger.json",
    }


def validate_manifest(path=FROZEN, *, current=True):
    data = json.loads(
        path.read_text()
    )  # JSON is valid YAML 1.2, avoids implicit YAML scalar types.
    if current and data["source_hashes"] != source_hashes():
        raise ValueError("FROZEN_SOURCE_OR_DATA_CHANGED")
    if data["source_bundle_hash"] != digest(canonical(data["source_hashes"]).encode()):
        raise ValueError("FROZEN_BUNDLE_INVALID")
    for name, version in data["sdk_versions"].items() if current else ():
        if importlib.metadata.version(name) != version:
            raise ValueError("FROZEN_SDK_CHANGED")
    if current and data.get("version") == 2:
        from evals.experiments import validate_experiment

        validate_experiment(data)
        prompts = {"single": SINGLE_PROMPT, "supervisor": SYSTEM_PROMPT, **PROMPTS}
        provider = data["provider"]
        if (
            data["prompt_hashes"] != {k: digest(v.encode()) for k, v in prompts.items()}
            or data["tool_schema_hash"]
            != digest(
                canonical(
                    {k: s.model_json_schema() for k, s in SCHEMAS.items()}
                ).encode()
            )
            or data["tool_union"] != sorted(SCHEMAS)
            or data["specialist_allowlists"]
            != {k: sorted(v) for k, v in ALLOWLISTS.items()}
            or data["episode_limits"] != asdict(Limits())
            or data["oracle_hash"] != data["source_hashes"]["evals/oracles.py"]
            or any(
                provider.get(k) != v
                for k, v in {
                    "name": "DeepSeek",
                    "model_id": "deepseek-flash",
                    "temperature": 0,
                    "thinking": "disabled",
                    "max_output_tokens": 2048,
                    "hidden_retries": 0,
                }.items()
            )
        ):
            raise ValueError("FROZEN_EXECUTION_CONFIG_CHANGED")
    return data, digest(path.read_bytes())


def claim_sealed(manifest_hash, run_id, *, path=None):
    destination = path or ROOT / "evals/evidence/t12/sealed-fixture-claim.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as stream:
        json.dump(
            {
                "manifest_sha256": manifest_hash,
                "run_id": run_id,
                "claimed_at": datetime.now(UTC).isoformat(),
                "meaning": "one sealed pass, including incomplete/failed execution",
            },
            stream,
            indent=2,
        )
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "check"))
    parser.add_argument("--output", type=Path, default=FROZEN)
    parser.add_argument("--amends", type=Path)
    parser.add_argument("--experiment", choices=("t12-live-retest-01",))
    parser.add_argument("--price-snapshot", type=Path)
    parser.add_argument(
        "--historical",
        action="store_true",
        help="Archive integrity only; never grants current execution",
    )
    args = parser.parse_args()
    target = args.output.resolve()
    if target.parent != (ROOT / "evals/config").resolve():
        raise ValueError("Manifest must remain inside evals/config")
    if args.action == "freeze":
        if args.historical:
            parser.error("--historical only applies to check")
        data = build_manifest()
        if args.amends:
            original = json.loads(args.amends.read_text())
            if data["datasets"] != original["datasets"]:
                raise ValueError(
                    "Post-sealed repair must preserve original task labels"
                )
            data["amendment"] = {
                "original_path": str(args.amends),
                "original_sha256": digest(args.amends.read_bytes()),
                "test_set_participated_in_development": True,
                "sealed_results_replaced": False,
                "disclosure": "evals/evidence/t12/sealed-development-disclosure.json",
            }
        if args.experiment:
            from evals.experiments import DEFINITION, policy_for

            if (
                not args.amends
                or digest(args.amends.read_bytes())
                != DEFINITION["parent_manifest_sha256"]
                or not args.price_snapshot
            ):
                parser.error(
                    "Retest freeze requires original L3 parent and new explicit price snapshot"
                )
            data.update(
                version=2,
                experiment=json.loads(json.dumps(DEFINITION)),
                live_ledger=DEFINITION["ledger"],
            )
            data["provider"]["price_snapshot"] = json.loads(
                args.price_snapshot.read_text()
            )
            data["price_snapshot_sha256"] = digest(args.price_snapshot.read_bytes())
            data["retries"] = (
                "Zero SDK retries; original schema repair plus one shared orchestration repair per Run; all requests charged within unchanged limits"
            )
            policy_for(
                data, "0" * 64
            )  # preflight only, never create authority or ledger
        elif args.price_snapshot:
            parser.error("Explicit prices require a registered experiment")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    _, value = validate_manifest(target, current=not args.historical)
    print(
        json.dumps(
            {
                "manifest": str(target.relative_to(ROOT)),
                "sha256": value,
                "status": "ARCHIVE_INTEGRITY_ONLY" if args.historical else "FROZEN",
            }
        )
    )


if __name__ == "__main__":
    main()
