"""Allowlisted public status and owner-encrypted raw CI evidence."""

import ast
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
from pathlib import PurePosixPath


def write_json(path, data):
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    sidecar = path.with_suffix(path.suffix + ".sha256")
    with os.fdopen(os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(hashlib.sha256(payload).hexdigest() + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _snapshot(raw, limit, partial=False):
    files, errors = {}, []
    total = 0

    def problem(path, error):
        if not partial:
            raise error
        errors.append({"path": path, "error_type": type(error).__name__})

    def walk(fd, prefix=""):
        nonlocal total
        try:
            names = sorted(entry.name for entry in os.scandir(fd))
        except OSError as exc:
            problem(prefix, exc)
            return
        for name in names:
            path = prefix + name
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or not (
                    stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
                ):
                    raise ValueError("UNSAFE_EVIDENCE_ENTRY")
                private = info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o077
                if not private:
                    problem(path, ValueError("PRIVATE_OWNER_REQUIRED"))
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        walk(child, path + "/")
                    finally:
                        os.close(child)
                else:
                    if info.st_nlink != 1 or path in {
                        "raw-inventory.json",
                        "raw-inventory.json.sha256",
                        "evidence-status.json",
                    }:
                        raise ValueError("UNSAFE_EVIDENCE_ENTRY")
                    if info.st_size + total > limit:
                        raise ValueError("EVIDENCE_SIZE_LIMIT")
                    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(file_fd, "rb") as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                            raise ValueError("UNSAFE_EVIDENCE_ENTRY")
                        if before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) & 0o077:
                            problem(path, ValueError("PRIVATE_OWNER_REQUIRED"))
                        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
                            raise ValueError("EVIDENCE_CHANGED")
                        data = stream.read(limit - total + 1)
                        after = os.fstat(stream.fileno())
                    if (
                        len(data) != info.st_size
                        or before.st_mtime_ns != after.st_mtime_ns
                        or after.st_nlink != 1
                        or before.st_mode != after.st_mode
                        or before.st_uid != after.st_uid
                    ):
                        raise ValueError("EVIDENCE_CHANGED")
                    files[path] = data
                    total += len(data)
            except (OSError, ValueError) as exc:
                problem(path, exc)

    fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            problem(".", ValueError("PRIVATE_OWNER_REQUIRED"))
        walk(fd)
    finally:
        os.close(fd)
    return files, errors


def verify_bundle(path, *, limit=100_000_000):
    with tarfile.open(path) as archive:
        values = {}
        total = 0
        for entry in archive:
            name = PurePosixPath(entry.name)
            if (
                not entry.isfile()
                or entry.mode != 0o600
                or name.is_absolute()
                or ".." in name.parts
                or entry.name in values
            ):
                raise ValueError("UNSAFE_ARCHIVE_ENTRY")
            total += entry.size
            if total > limit:
                raise ValueError("EVIDENCE_SIZE_LIMIT")
            values[entry.name] = archive.extractfile(entry).read()
    inventory = values.pop("raw-inventory.json")
    if (
        values.pop("raw-inventory.json.sha256").decode().strip()
        != hashlib.sha256(inventory).hexdigest()
    ):
        raise ValueError("ARCHIVE_INVENTORY_HASH")
    refs = json.loads(inventory)
    if len(refs) != len(values) or {r["path"] for r in refs} != set(values):
        raise ValueError("ARCHIVE_INVENTORY_MISMATCH")
    for ref in refs:
        data = values[ref["path"]]
        if len(data) != ref["size"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("ARCHIVE_FILE_HASH")
    return json.loads(values["evidence-status.json"])


def bundle(raw, output, *, limit=100_000_000, partial=False):
    files, errors = _snapshot(raw, limit, partial)
    while True:
        status = {
            "complete": not partial and not errors,
            "state": "INCOMPLETE" if partial or errors else "COMPLETE",
            "errors": errors,
        }
        packed = files | {"evidence-status.json": (json.dumps(status, indent=2) + "\n").encode()}
        refs = [
            {"path": p, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for p, data in sorted(packed.items())
        ]
        inventory = (json.dumps(refs, indent=2) + "\n").encode()
        packed["raw-inventory.json"] = inventory
        packed["raw-inventory.json.sha256"] = (
            hashlib.sha256(inventory).hexdigest() + "\n"
        ).encode()
        if sum(map(len, packed.values())) <= limit:
            break
        if not partial or not files:
            raise ValueError("EVIDENCE_SIZE_LIMIT")
        # Preserve a bounded encrypted failure rather than spend the cap before metadata fits.
        dropped = max(files, key=lambda p: len(files[p]))
        del files[dropped]
        errors.append({"path": dropped, "error_type": "EVIDENCE_SIZE_LIMIT"})
    files = packed
    fd, name = tempfile.mkstemp(prefix=".evidence-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                for path, data in sorted(files.items()):
                    entry = tarfile.TarInfo(path)
                    entry.size, entry.mode = len(data), 0o600
                    archive.addfile(entry, io.BytesIO(data))
            stream.flush()
            os.fsync(stream.fileno())
        verified = verify_bundle(name, limit=limit)
        os.link(name, output)  # Atomic no-overwrite publication, never replace old evidence.
        return verified
    finally:
        os.unlink(name)


def validate_certificate(cert, digest):
    data = cert.read_bytes()
    if (
        len(data) > 8192
        or b"PRIVATE KEY" in data
        or data.count(b"BEGIN CERTIFICATE") != 1
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or hashlib.sha256(data).hexdigest() != digest
    ):
        raise ValueError("CERTIFICATE_BINDING_INVALID")
    subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-checkend", "7200", "-noout"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    public = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout
    subprocess.run(
        ["openssl", "rsa", "-pubin", "-noout"],
        input=public,
        check=True,
        capture_output=True,
        timeout=10,
    )


def encrypt(raw, cert, digest, output):
    validate_certificate(cert, digest)
    if output.exists():
        raise ValueError("NO_OVERWRITE")
    subprocess.run(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-gcm",
            "-in",
            str(raw),
            "-outform",
            "DER",
            "-out",
            str(output),
            "-recip",
            str(cert),
            "-keyopt",
            "rsa_padding_mode:oaep",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def public_summary(phase, result, clock):
    success = result.get("exit_code") == 0
    proof = (
        result.get("verified") is True
        and clock.get("runtime_passed") is True
        and result.get("evidence_complete") is True
        and result.get("cleanup_complete") is True
    )
    value = {
        "phase": phase,
        "result": "PASS" if success and proof else "BLOCKED" if success else "FAIL",
        "exit_code": result.get("exit_code"),
        "evidence_complete": result.get("evidence_complete") is True,
        "cleanup_complete": result.get("cleanup_complete") is True,
        "clock_admission_passed": clock.get("admission_passed") is True,
        "clock_runtime_passed": clock.get("runtime_passed") is True,
        "real_provider_requests": 0,
        "live_verified": "NOT_RUN",
    }
    counts = result.get("counts", {})
    value["counts"] = {
        k: v
        for k, v in counts.items()
        if k in {"pytest_passed", "pytest_skipped", "vitest_passed", "playwright_passed"}
        and type(v) is int
        and v >= 0
    }
    return value


def _vitest_passed(output):
    # SGR changes presentation only. Cursor/erase/other controls are not colors.
    plain = re.sub(r"\x1b\[[0-9;:]*m", "", output).replace("\r\n", "\n")
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", plain):
        raise ValueError("VITEST_UNSUPPORTED_CONTROL")
    lines = [line for line in plain.split("\n") if line.strip()]
    summaries = [
        (index, line)
        for index, line in enumerate(lines)
        if re.match(r"[ \t]*(?:Test Files|Tests)\b", line)
    ]
    if len(summaries) != 2 or summaries[1][0] != summaries[0][0] + 1:
        raise ValueError("VITEST_SUMMARY_MISSING_OR_AMBIGUOUS")
    counts = []
    for (_, line), label in zip(summaries, ("Test Files", "Tests"), strict=True):
        match = re.fullmatch(
            rf"[ \t]*{label}[ \t]+([1-9][0-9]*) passed[ \t]+\(([1-9][0-9]*)\)[ \t]*",
            line,
        )
        if match is None or match[1] != match[2]:
            raise ValueError("VITEST_SUMMARY_INCONSISTENT")
        counts.append(int(match[1]))
    if counts[0] > counts[1]:
        raise ValueError("VITEST_SUMMARY_INCONSISTENT")
    return counts[1]


def core_proof(app, *, outputs=None):
    verified_logs = {}
    for name in (
        "bootstrap",
        "ruff",
        "format",
        "pytest",
        "typecheck",
        "lint",
        "vitest",
        "build",
        "playwright",
    ):
        folder = outputs if outputs is not None else app / ".t13/outputs"
        path = folder / (name + ".json")
        receipt = json.loads(path.read_text())
        expected_log = f".t13/outputs/{name}.txt"
        if receipt["log"] != expected_log:
            raise ValueError("CORE_RECEIPT_FAILED")
        data = (folder / (name + ".txt")).read_bytes()
        if (
            type(receipt["exit_code"]) is not int
            or receipt["exit_code"] != 0
            or hashlib.sha256(data).hexdigest() != receipt["log_sha256"]
        ):
            raise ValueError("CORE_RECEIPT_FAILED")
        verified_logs[name] = data
    # Parse only the bytes already verified, after ALL nine receipts pass.
    pytest = verified_logs["pytest"].decode("utf-8")
    vitest = verified_logs["vitest"].decode("utf-8")
    playwright = verified_logs["playwright"].decode("utf-8")
    passed = re.findall(r"(\d+) passed", pytest)
    skipped = re.findall(r"(\d+) skipped", pytest)
    units = _vitest_passed(vitest)
    browser = re.findall(r"(\d+) passed", playwright)
    if (
        not passed
        or int(passed[-1]) < 823
        or not skipped
        or int(skipped[-1]) != 14
        or units != 85
        or not browser
        or int(browser[-1]) != 96
    ):
        raise ValueError("CORE_COUNTS_OUTSIDE_CONTRACT")
    return {
        "pytest_passed": int(passed[-1]),
        "pytest_skipped": int(skipped[-1]),
        "vitest_passed": units,
        "playwright_passed": int(browser[-1]),
    }


def schema_report(raw):
    """Report the verifier's own cleanup claim without promising database recovery."""
    try:
        files, _ = _snapshot(raw, 100_000_000, partial=True)
        if "verification/result.json" in files:
            result = json.loads(files["verification/result.json"])
            if result.get("owned_schemas_cleaned_after_evidence") is True:
                return "REPORTED_DROPPED_ORACLE_NOT_VERIFIED"
        if "verification/failure.json" in files:
            state = json.loads(files["verification/failure.json"]).get("schema_state")
            return {"DROPPED": "REPORTED_DROPPED", "OWNED": "REPORTED_RETAINED"}.get(
                state, "UNKNOWN"
            )
    except (OSError, ValueError):
        pass
    return "UNKNOWN"


def bge_proof(raw, app):
    files, _ = _snapshot(raw, 100_000_000)

    def document(name, sidecar=False):
        if name not in files:
            raise ValueError("REQUIRED_EVIDENCE_MISSING")
        data = files[name]
        if (
            sidecar
            and files.get(name + ".sha256", b"").decode().strip()
            != hashlib.sha256(data).hexdigest()
        ):
            raise ValueError("ORIGINAL_SIDECAR_MISMATCH")
        return json.loads(data)

    result = document("verification/result.json")  # private_write has no sidecar.
    identity = document("identity.json")
    oracle = document("verification/business-oracle.json", True)
    model = document("verification/model.json", True)
    retrieval = document("verification/retrieval.json", True)
    ownership = document("verification/ownership.json")
    environment = document("state/environment.json")
    policy = document("state/mock-policy.json")
    ledger = document("state/ledger.json")
    if "state/ledger.json.lock" not in files:
        raise ValueError("REQUIRED_EVIDENCE_MISSING")
    digest = hashlib.sha256(files["verification/business-oracle.json"]).hexdigest()
    if (
        result["status"] != "T16_A3_TARGETED_OFFLINE_VERIFIED"
        or result["retrieval_cases"] != 14
        or result["payments"] != 0
        or result["order_status"] != "PENDING_PAYMENT"
        or result["oracle_sha256"] != digest
        or result["owned_schemas_cleaned_after_evidence"] is not True
        or result["real_provider_requests"] != 0
        or result["live_authorization_created"] is not False
        or result["source_fingerprint"] != oracle["source_fingerprint"]
        or identity["product_fingerprint"] != result["source_fingerprint"]
        or identity["phase"] != "bge"
    ):
        raise ValueError("BGE_RESULT_INCOMPLETE")
    ident = result["environment_id"]
    if (
        ownership["environment_id"] != ident
        or environment["environment_id"] != ident
        or oracle["environment_id"] != ident
        or policy["environment_id"] != ident
        or environment["state"] != "READY"
        or ownership["schema_state"] != "OWNED"
        or ownership["schemas"] != oracle["schemas"]
        or oracle["schemas"]
        != [environment["settings"]["db_schema"], environment["settings"]["checkpoint_schema"]]
        or policy["evidence_mode"] != "MOCK_TRANSPORT"
        or policy["source_sha256"] != oracle["source_fingerprint"]
    ):
        raise ValueError("BGE_OWNERSHIP_MISMATCH")
    binding = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        binding != ledger["binding"]
        or binding != oracle["mock_policy_sha256"]
        or len(ledger["attempts"]) != oracle["mock_requests"]
        or {a["run_id"] for a in ledger["attempts"]} != set(oracle["expected"]["run_ids"])
    ):
        raise ValueError("MOCK_LEDGER_MISMATCH")
    stages = oracle["stages"]
    before = oracle["before_confirmation"]
    messages = [
        "推荐300元以内的静音键盘，不要购买。",
        "我改主意了，要支持无线连接的，预算提高到400元。",
        "就买刚才推荐的第二款，一件，送演示宿舍。",
    ]
    if (
        len(stages) != 3
        or [s["run_id"] for s in stages] != oracle["expected"]["run_ids"]
        or [s["input"] for s in stages] != messages
        or any(before[t] for t in ("orders", "confirmations", "payments"))
        or len(before["action_proposals"]) != 1
        or before["action_proposals"][0]["id"] != oracle["expected"]["proposal_id"]
        or oracle["repeat_added_model_requests"] != 0
        or set(oracle["shared_ledger_runs"]) != set(oracle["expected"]["run_ids"])
        or oracle["mock_session_id"] != policy["session_id"]
        or oracle["checkpoint_rows"] < 3
    ):
        raise ValueError("THREE_TURN_EVIDENCE_INCOMPLETE")
    lists = [s["context"]["candidate_sets"][0]["items"] for s in stages]
    if (
        len(lists[0]) < 1
        or len(lists[1]) < 2
        or result["three_turn_candidates"] != [len(items) for items in lists]
        or lists[1][1]["id"] != oracle["expected"]["product_id"]
        or stages[0]["context"]["preferences"]["max_price_cents"] != 30000
        or stages[1]["context"]["preferences"]["max_price_cents"] != 40000
    ):
        raise ValueError("CANDIDATE_BINDING_MISMATCH")
    manifest = json.loads((app / "evals/data/embedding_manifest.json").read_text())
    if (
        model["model_id"] != manifest["model_id"]
        or model["revision"] != manifest["revision"]
        or model["dimension"] != 512
        or model["device"] != "cpu"
        or len(model["files"]) != 6
        or {v["file"]: {k: v[k] for k in ("sha256", "size_bytes")} for v in model["files"]}
        != manifest["files"]
        or len(retrieval["cases"]) != 14
        or retrieval["filters_before_limit"] is not True
        or retrieval["min_similarity"] != 0.45
        or retrieval["dimensions"] != [512]
    ):
        raise ValueError("MODEL_OR_RETRIEVAL_INCOMPLETE")
    expected_files = [
        "scripts/verify_t16_a3.py",
        "backend/tests/t16_a3_oracle.py",
        "backend/tests/t16_a3_scenario.py",
        "backend/tests/t16_a3_retrieval_checks.py",
    ]
    if oracle["verifier_files"] != {
        p: hashlib.sha256((app / p).read_bytes()).hexdigest() for p in expected_files
    }:
        raise ValueError("FROZEN_VERIFIER_MISMATCH")
    # Only execute the already source-bound pure validator, never checkpoint deserialization.
    tree = ast.parse((app / "backend/tests/t16_a3_oracle.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validate")
    scope = {"json": json, "hashlib": hashlib}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "frozen-oracle", "exec"), scope)
    if (
        oracle["status"] != "PASS"
        or oracle["violations"]
        or oracle["general_oracle"]["violations"]
        or scope["validate"](oracle["observed"], oracle["expected"], oracle["checkpoints"])
        or result["order_id"] != oracle["observed"]["orders"][0]["id"]
        or oracle["offline_boundary"]["external_attempts"] != 0
        or oracle["offline_boundary"]["real_provider_requests"] != 0
        or oracle["offline_boundary"]["real_key_read"] is not False
    ):
        raise ValueError("ORACLE_NOT_PASSED")
    return result
