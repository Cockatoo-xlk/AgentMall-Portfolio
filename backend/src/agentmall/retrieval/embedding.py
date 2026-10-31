"""Offline-only BGE encoder. Downloads are an explicit evals/embed.py operation."""

import hashlib
import json
import math
from pathlib import Path

MODEL = "BAAI/bge-small-zh-v1.5"
REVISION = "7999e1d3359715c523056ef9478215996d62a620"
DIMENSION = 512
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
ROOT = Path(__file__).resolve().parents[4]
SUPPORTED = {(MODEL, REVISION), ("agentmall/fixture", "unit-v1")}


def identity(encoder):
    pair = (encoder.model_id, encoder.revision)
    if pair not in SUPPORTED or encoder.dimension != DIMENSION:
        raise ValueError("Unsupported embedding model/revision/dimension")
    return pair


def validate_vectors(encoder, vectors, count):
    identity(encoder)
    if len(vectors) != count:
        raise ValueError("Incomplete embedding batch")
    for vector in vectors:
        if len(vector) != DIMENSION or not all(math.isfinite(float(x)) for x in vector):
            raise ValueError("Embedding dimension or finite-value violation")
        if abs(math.sqrt(sum(float(x) ** 2 for x in vector)) - 1) > 1e-4:
            raise ValueError("Embedding must be L2-normalized")
    return vectors


class LocalEncoder:
    model_id, revision, dimension = MODEL, REVISION, DIMENSION

    def __init__(self, directory=None):
        import torch
        from transformers import AutoModel, AutoTokenizer

        directory = Path(directory or ROOT / ".models" / REVISION)
        manifest = json.loads((ROOT / "evals/data/embedding_manifest.json").read_text())
        if (manifest["model_id"], manifest["revision"], manifest["dimension"]) != (
            MODEL,
            REVISION,
            DIMENSION,
        ):
            raise ValueError("Model manifest mismatch")
        for name, data in manifest["files"].items():
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != data["sha256"]:
                raise ValueError(f"Model file checksum mismatch: {name}")
        torch.set_num_threads(2)
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False
        )
        self.model = AutoModel.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False, use_safetensors=True
        )
        self.model.eval()
        if self.model.config.hidden_size != DIMENSION:
            raise ValueError("Model dimension mismatch")

    def encode(self, texts, *, query=False):
        result = []
        for start in range(0, len(texts), 16):
            batch = [(QUERY_PREFIX if query else "") + t for t in texts[start : start + 16]]
            inputs = self.tokenizer(
                batch, padding=True, truncation=True, max_length=512, return_tensors="pt"
            )
            with self.torch.inference_mode():
                output = self.model(**inputs)[0][:, 0]
                result.extend(self.torch.nn.functional.normalize(output, p=2, dim=1).tolist())
        return validate_vectors(self, result, len(texts))
