"""Explicit public-model download and offline compatibility probe; never a paid API."""

import argparse
import hashlib
import json
import platform
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from agentmall.retrieval.embedding import (
    DIMENSION,
    MODEL,
    QUERY_PREFIX,
    REVISION,
    ROOT,
    LocalEncoder,
)

FILES = [
    "config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
]


def download():
    directory = ROOT / ".models" / REVISION
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / "evals/data/embedding_manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    files = {}
    for name in FILES:
        target = directory / name
        if not target.exists():
            temporary = target.with_suffix(target.suffix + ".part")
            with (
                urllib.request.urlopen(
                    f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}",
                    timeout=60,
                ) as response,
                temporary.open("wb") as out,
            ):
                while block := response.read(1024 * 1024):
                    out.write(block)
            temporary.replace(target)
        files[name] = {
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "size_bytes": target.stat().st_size,
        }
        if existing and files[name] != existing["files"][name]:
            raise ValueError(f"Download checksum mismatch: {name}")
    manifest = {
        "model_id": MODEL,
        "revision": REVISION,
        "dimension": DIMENSION,
        "license": "MIT",
        "source": f"https://huggingface.co/{MODEL}/tree/{REVISION}",
        "files": files,
        "query_prefix": QUERY_PREFIX,
        "document_prefix": "",
        "pooling": "CLS",
        "normalization": "L2",
        "max_length": 512,
        "device": "cpu",
        "dtype": "float32",
    }
    if not existing:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evals/evidence/t07/embedding-probe.json"
    )
    args = parser.parse_args()
    if args.download:
        download()
    started = time.perf_counter()
    encoder = LocalEncoder()
    load_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    vectors = encoder.encode(["宿舍静音机械键盘", "质量问题签收七日内退货"], query=True)
    import importlib.metadata

    result = {
        "status": "RAG_REAL_EMBEDDING",
        "model_id": MODEL,
        "revision": REVISION,
        "dimension": len(vectors[0]),
        "norms": [sum(x * x for x in v) ** 0.5 for v in vectors],
        "load_ms": load_ms,
        "batch_two_ms": (time.perf_counter() - started) * 1000,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "packages": {
            p: importlib.metadata.version(p)
            for p in ("torch", "transformers", "numpy", "pgvector", "jieba")
        },
        "executed_at": datetime.now(UTC).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
