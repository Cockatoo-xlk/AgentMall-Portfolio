"""Explicit public pinned-weight download/probe; never a hosted inference API."""

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

from agentmall.retrieval.embedding import ROOT
from agentmall.retrieval.reranker import MODEL, REVISION, LocalReranker, verify_files


def download(directory):
    manifest = json.loads((ROOT / "evals/data/reranker_manifest.json").read_text())
    directory.mkdir(parents=True, exist_ok=True)
    for name, entry in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("Invalid pinned model file")
        dest = directory / name
        if dest.exists():
            continue
        temporary = directory / (name + ".part")
        started = time.monotonic()
        total = 0
        digest = hashlib.sha256()
        with (
            urllib.request.urlopen(
                f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}", timeout=60
            ) as response,
            temporary.open("xb") as out,
        ):
            while block := response.read(1024 * 1024):
                if time.monotonic() - started > 1200:
                    raise TimeoutError("Bounded public download")
                total += len(block)
                if total > entry["size_bytes"]:
                    raise ValueError("Oversized model file")
                out.write(block)
                digest.update(block)
        if total != entry["size_bytes"] or digest.hexdigest() != entry["sha256"]:
            raise ValueError("Incomplete model; partial retained, no automatic retry")
        temporary.rename(dest)
    verify_files(directory)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, default=ROOT / ".models" / REVISION)
    p.add_argument("--download", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose new evidence output")
    if args.download:
        download(args.directory)
    scorer = LocalReranker(args.directory)
    try:
        start = time.perf_counter()
        scores = scorer.score(
            "办公显示器", ["27英寸IPS办公显示器，HDMI接口。", "公路车骑行头盔，240克。"]
        )
        result = {
            "evidence_class": "REAL_LOCAL_CROSS_ENCODER",
            "model_id": MODEL,
            "revision": REVISION,
            "device": "cpu",
            "load_ms": scorer.load_ms,
            "warm_pair_ms": (time.perf_counter() - start) * 1000,
            "scores": scores,
            "batches": scorer.batches,
            "files": verify_files(args.directory)["files"],
            "provider_requests": 0,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "files"}))
    finally:
        scorer.close()


if __name__ == "__main__":
    main()
