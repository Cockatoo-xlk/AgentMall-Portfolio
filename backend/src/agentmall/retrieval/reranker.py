"""Pinned, offline CPU Cross-Encoder with a killable, bounded worker; no remote inference."""

import hashlib
import json
import math
import multiprocessing
import threading
import time
from pathlib import Path

from agentmall.retrieval.embedding import ROOT

MODEL = "BAAI/bge-reranker-base"
REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"
MAX_CANDIDATES = 20
MAX_LENGTH = 256
BATCH_SIZE = 4


class RerankError(Exception):
    pass


def verify_files(directory):
    manifest = json.loads((ROOT / "evals/data/reranker_manifest.json").read_text())
    if (manifest["model_id"], manifest["revision"], manifest["license"]) != (
        MODEL,
        REVISION,
        "MIT",
    ):
        raise RerankError("MODEL_MANIFEST_MISMATCH")
    for name, data in manifest["files"].items():
        if Path(name).name != name:
            raise RerankError("INVALID_MODEL_FILE")
        path = directory / name
        if not path.is_file() or path.stat().st_size != data["size_bytes"]:
            raise RerankError("MODEL_FILE_MISSING")
        h = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                h.update(block)
        if h.hexdigest() != data["sha256"]:
            raise RerankError("MODEL_HASH_MISMATCH")
    return manifest


def _worker(pipe, directory):
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(2)
        tokenizer = AutoTokenizer.from_pretrained(
            directory, local_files_only=True, trust_remote_code=False, token=False
        )
        model = (
            AutoModelForSequenceClassification.from_pretrained(
                directory,
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
                token=False,
            )
            .to("cpu")
            .float()
            .eval()
        )
        pipe.send({"ready": True})
        while (request := pipe.recv()) is not None:
            query, docs = request
            scores = []
            with torch.inference_mode():
                for start in range(0, len(docs), BATCH_SIZE):
                    pairs = [[query, d] for d in docs[start : start + BATCH_SIZE]]
                    inputs = tokenizer(
                        pairs,
                        padding=True,
                        truncation=True,
                        max_length=MAX_LENGTH,
                        return_tensors="pt",
                    )
                    scores.extend(model(**inputs).logits.reshape(-1).float().tolist())
            pipe.send({"scores": scores})
    except (Exception, EOFError):
        try:
            pipe.send({"error": "MODEL_WORKER_FAILED"})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        pipe.close()


class LocalReranker:
    model_id, revision = MODEL, REVISION
    batch_size = BATCH_SIZE

    def __init__(self, directory=None, *, timeout_seconds=10, load_timeout_seconds=60):
        if not 0 < timeout_seconds <= 30 or not 0 < load_timeout_seconds <= 90:
            raise ValueError("Bounded timeout required")
        started = time.perf_counter()
        directory = Path(directory or ROOT / ".models" / REVISION).resolve()
        verify_files(directory)
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._broken = False
        self.calls = 0
        self.batches = 0
        parent, child = multiprocessing.get_context("spawn").Pipe()
        self._pipe = parent
        self._process = multiprocessing.get_context("spawn").Process(
            target=_worker, args=(child, str(directory)), daemon=True
        )
        self._process.start()
        child.close()
        if not parent.poll(load_timeout_seconds):
            self.close()
            raise RerankError("MODEL_LOAD_TIMEOUT")
        try:
            ready = parent.recv()
        except (EOFError, OSError) as error:
            self.close()
            raise RerankError("MODEL_UNAVAILABLE") from error
        if ready != {"ready": True}:
            self.close()
            raise RerankError("MODEL_UNAVAILABLE")
        self.load_ms = (time.perf_counter() - started) * 1000

    def score(self, query, documents):
        if (
            not isinstance(query, str)
            or not 1 <= len(query) <= 500
            or not 1 <= len(documents) <= MAX_CANDIDATES
            or any(not isinstance(d, str) or not d or len(d) > 8000 for d in documents)
        ):
            raise RerankError("INVALID_RERANK_INPUT")
        if not self._lock.acquire(timeout=self.timeout_seconds):
            raise RerankError("MODEL_BUSY")
        try:
            if self._broken or not self._process.is_alive():
                raise RerankError("MODEL_UNAVAILABLE")
            self.calls += 1
            self._pipe.send((query, documents))
            if not self._pipe.poll(self.timeout_seconds):
                self.close()
                raise RerankError("MODEL_INFERENCE_TIMEOUT")
            value = self._pipe.recv()
            scores = value.get("scores")
            if (
                not isinstance(scores, list)
                or len(scores) != len(documents)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in scores)
            ):
                self.close()
                raise RerankError("INVALID_MODEL_SCORES")
            self.batches += math.ceil(len(documents) / BATCH_SIZE)
            return scores
        except (OSError, EOFError) as error:
            self.close()
            raise RerankError("MODEL_WORKER_FAILED") from error
        finally:
            self._lock.release()

    def close(self):
        self._broken = True
        if hasattr(self, "_process"):
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=2)
        if hasattr(self, "_pipe"):
            self._pipe.close()
