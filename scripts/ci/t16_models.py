"""Download only six manifest-pinned public BGE files; never reads HF/API tokens."""

import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    root = Path("/work")
    manifest = json.loads((root / "evals/data/embedding_manifest.json").read_text())
    model = root / ".models" / manifest["revision"]
    model.mkdir(parents=True, exist_ok=False)
    for name, reference in manifest["files"].items():
        url = f"https://huggingface.co/{manifest['model_id']}/resolve/{manifest['revision']}/{name}"
        with urllib.request.urlopen(url, timeout=120) as response:
            payload = response.read(reference["size_bytes"] + 1)
        if (
            len(payload) != reference["size_bytes"]
            or hashlib.sha256(payload).hexdigest() != reference["sha256"]
        ):
            raise ValueError("PINNED_BGE_FILE_MISMATCH")
        (model / name).write_bytes(payload)


if __name__ == "__main__":
    main()
