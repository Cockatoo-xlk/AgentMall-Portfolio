import json
from argparse import Namespace
from pathlib import Path

import pytest
from evals import manifest
from evals.run import execute
from evals.schema import canonical


def test_freeze_rejects_oracle_data_and_source_drift(tmp_path, monkeypatch):
    hashes = {"evals/oracles.py": "original"}
    monkeypatch.setattr(manifest, "source_hashes", lambda: hashes.copy())
    path = tmp_path / "frozen.yaml"
    path.write_text(
        json.dumps(
            {
                "source_hashes": hashes,
                "source_bundle_hash": manifest.digest(canonical(hashes).encode()),
                "sdk_versions": {},
            }
        )
    )
    assert manifest.validate_manifest(path)[0]["source_hashes"] == hashes
    hashes["evals/oracles.py"] = "edited"
    with pytest.raises(ValueError, match="CHANGED"):
        manifest.validate_manifest(path)


def test_one_sealed_claim_survives_new_run_label(tmp_path):
    path = tmp_path / "claim.json"
    manifest.claim_sealed("a" * 64, "original", path=path)
    with pytest.raises(FileExistsError):
        manifest.claim_sealed("a" * 64, "new-label", path=path)
    assert json.loads(path.read_text())["run_id"] == "original"


async def test_live_default_missing_flags_cannot_read_key_or_send(monkeypatch):
    from agentmall.infra import llm

    monkeypatch.setattr(llm, "load_live_key", lambda: pytest.fail("key boundary crossed"))
    monkeypatch.setattr(manifest, "FROZEN", Path("missing-test-manifest"))
    args = Namespace(
        mode="live",
        split="dev",
        pilot=True,
        repeats=1,
        confirm_live=False,
        max_model_calls=None,
        max_cost_cny=None,
        max_wall_seconds=None,
        run_id="never-created",
    )
    with pytest.raises(ValueError, match="FROZEN_DEV"):
        await execute(args)
