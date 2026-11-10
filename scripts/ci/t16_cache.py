"""Private, per-execution Jieba runtime; no product or tokenizer changes."""

import argparse
import hashlib
import importlib
import json
import os
import re
import runpy
import shutil
import stat
import sys
from pathlib import Path

DIRECTORIES = ("home", "cache", "tmp", "ml-cache")


def marker(owner, uid, gid):
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", owner):
        raise ValueError("INVALID_RUNTIME_OWNER")
    return {"owner": owner, "uid": uid, "gid": gid}


def private_entry(path, uid, gid, directory):
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected(info.st_mode)
        or (info.st_uid, info.st_gid) != (uid, gid)
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not directory and info.st_nlink != 1)
    ):
        raise ValueError("PRIVATE_RUNTIME_ENTRY_MISMATCH")


def create_runtime(root, owner):
    """Create exclusively as the real host identity used for the nonroot Guest."""
    uid, gid = os.geteuid(), os.getegid()
    value = marker(owner, uid, gid)
    root.mkdir(mode=0o700, exist_ok=False)
    root.chmod(0o700)
    for directory in DIRECTORIES:
        (root / directory).mkdir(mode=0o700)
        (root / directory).chmod(0o700)
    for path in (root / ".owner.json", root / "ml-cache/.owner.json"):
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True)
    validate_runtime(root, owner, uid, gid)
    return root


def validate_runtime(root, owner, uid, gid):
    private_entry(root, uid, gid, True)
    for name in DIRECTORIES:
        private_entry(root / name, uid, gid, True)
    for path in (root / ".owner.json", root / "ml-cache/.owner.json"):
        private_entry(path, uid, gid, False)
        if json.loads(path.read_text()) != marker(owner, uid, gid):
            raise ValueError("RUNTIME_OWNERSHIP_MARKER_MISMATCH")

    # os.walk with an explicit onerror is fail-closed, including unreadable subtrees.
    def unreadable(error):
        raise error

    for parent, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
        for name in dirs + files:
            path = Path(parent) / name
            private_entry(path, uid, gid, name in dirs)


def cleanup_runtime(root, owner):
    """Remove only this invocation's validated runtime, after container removal."""
    validate_runtime(root, owner, os.geteuid(), os.getegid())
    shutil.rmtree(root)
    if root.exists() or root.is_symlink():
        raise RuntimeError("RUNTIME_REMOVAL_UNVERIFIED")
    return {"verified_absent": True, "scope": "OWNED_GUEST_RUNTIME"}


def validate_mount(root, runtime, owner, uid, gid):
    if uid <= 0 or gid <= 0 or (os.geteuid(), os.getegid()) != (uid, gid):
        raise ValueError("NONROOT_GUEST_IDENTITY_MISMATCH")
    validate_runtime(runtime, owner, uid, gid)
    cache = root / ".ml-cache"
    private_entry(cache, uid, gid, True)
    mounted = [
        line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()
    ]
    if not any(
        fields[4] == str(cache) and "rw" in fields[5].split(",") for fields in mounted
    ):
        raise ValueError("DEDICATED_CACHE_BIND_MOUNT_REQUIRED")
    if not os.path.samestat(cache.stat(), (runtime / "ml-cache").stat()):
        raise ValueError("CACHE_BIND_SOURCE_MISMATCH")
    if json.loads((cache / ".owner.json").read_text()) != marker(owner, uid, gid):
        raise ValueError("CACHE_BIND_OWNER_MISMATCH")
    for path in (root, root / "scripts", root / "backend", root / ".models"):
        if os.access(path, os.W_OK):
            raise ValueError("PUBLIC_SOURCE_MUST_NOT_BE_WRITABLE")
    probe = cache / ".write-probe"
    with probe.open("xb") as stream:
        os.chmod(probe, 0o600)
        stream.write(b"isolated cache")
    if probe.read_bytes() != b"isolated cache":
        raise ValueError("CACHE_READBACK_MISMATCH")
    probe.unlink()
    return cache


def probe(owner, uid, gid):
    """Run before indexing. Network and writes elsewhere in /work are denied."""
    os.umask(0o077)
    root, runtime = Path("/work"), Path("/runtime")
    cache = validate_mount(root, runtime, owner, uid, gid)
    events = {"network_attempts": 0, "forbidden_source_writes": 0}

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            events["network_attempts"] += 1
            raise PermissionError("CACHE_PREFLIGHT_NETWORK_DISABLED")
        paths = []
        if event == "open":
            path, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            ):
                paths = [path]
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod"}:
            paths = [args[0]]
        elif event in {"os.rename", "os.link", "os.symlink"}:
            paths = list(args[:2])
        for path in paths:
            if isinstance(path, (str, bytes, os.PathLike)):
                resolved = Path(os.fsdecode(path)).resolve()
                if resolved.is_relative_to(root) and not resolved.is_relative_to(cache):
                    events["forbidden_source_writes"] += 1
                    raise PermissionError("CACHE_PREFLIGHT_SOURCE_WRITE_DENIED")

    sys.addaudithook(audit)
    entry = root / "scripts/verify_t16_a3.py"
    namespace = runpy.run_path(str(entry), run_name="cache_access_probe")
    with namespace["offline_boundary"]() as boundary:
        for module in (
            "sqlalchemy",
            "psycopg",
            "pgvector",
            "langgraph.checkpoint.postgres",
            "t16_a3_oracle",
            "t16_a3_scenario",
            "t16_a3_retrieval_checks",
        ):
            importlib.import_module(module)
        manifest = json.loads((root / "evals/data/embedding_manifest.json").read_text())
        if len(manifest["files"]) != 6:
            raise ValueError("SIX_PINNED_MODEL_FILES_REQUIRED")
        for name, ref in manifest["files"].items():
            data = (root / ".models" / manifest["revision"] / name).read_bytes()
            if (
                len(data) != ref["size_bytes"]
                or hashlib.sha256(data).hexdigest() != ref["sha256"]
            ):
                raise ValueError("PINNED_MODEL_FILE_MISMATCH")
        from agentmall.retrieval.embedding import LocalEncoder
        from agentmall.retrieval.tokenize import document_tokens, tokenizer

        encoder = LocalEncoder()
        vector = encoder.encode(["无线静音键盘"], query=True)[0]
        if len(vector) != 512 or str(next(encoder.model.parameters()).device) != "cpu":
            raise ValueError("CPU_512_REQUIRED")
        text = "无线静音键盘"
        first = document_tokens(text)
        cache_file = cache / "jieba.cache"
        private_entry(cache_file, uid, gid, False)
        before = (
            hashlib.sha256(cache_file.read_bytes()).hexdigest(),
            cache_file.stat().st_mtime_ns,
        )
        second = document_tokens(text)
        tokenizer.cache_clear()
        reloaded = document_tokens(
            text
        )  # New Jieba instance reads the persisted cache.
        after = (
            hashlib.sha256(cache_file.read_bytes()).hexdigest(),
            cache_file.stat().st_mtime_ns,
        )
        if not first or first != second or first != reloaded or before != after:
            raise ValueError("TOKENIZER_CACHE_RELOAD_MISMATCH")
        validate_runtime(runtime, owner, uid, gid)
        if boundary.blocked_external_attempts or any(events.values()):
            raise ValueError("CACHE_PREFLIGHT_BOUNDARY_VIOLATION")
    return {
        "status": "NONROOT_CACHE_PREFLIGHT_PASSED",
        "uid": uid,
        "gid": gid,
        "model_files": 6,
        "model_revision": manifest["revision"],
        "dimension": 512,
        "device": "cpu",
        "cache_sha256": before[0],
        "cache_mode": "0600",
        "cache_directory_mode": "0700",
        "repeat_tokens_equal": True,
        "persisted_cache_reload": True,
        "dedicated_bind_verified": True,
        **events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.owner, args.uid, args.gid)))
    except Exception as exc:  # noqa: BLE001 - Every preflight failure returns redacted error/exit 2.
        code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if not re.fullmatch(r"[A-Z_]{1,100}", code):
            code = type(exc).__name__
        print(
            json.dumps(
                {
                    "status": "NONROOT_CACHE_PREFLIGHT_FAILED",
                    "error_type": type(exc).__name__,
                    "error_code": code,
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
