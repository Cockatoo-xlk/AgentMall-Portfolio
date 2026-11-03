"""Allowlisted public status and owner-encrypted raw CI evidence."""

import hashlib
import json
import os
import re
import subprocess
import tarfile


def write_json(path, data):
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    path.with_suffix(path.suffix + ".sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def bundle(raw, output, *, limit=100_000_000):
    files = []
    total = 0
    for path in sorted(raw.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("UNSAFE_EVIDENCE_ENTRY")
        if path.is_file():
            total += path.stat().st_size
            if total > limit:
                raise ValueError("EVIDENCE_SIZE_LIMIT")
            files.append(path)
    manifest = [
        {
            "path": str(p.relative_to(raw)),
            "size": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in files
    ]
    write_json(raw / "raw-inventory.json", manifest)
    with tarfile.open(output, "x:gz") as archive:
        for path in files + [
            raw / "raw-inventory.json",
            raw / "raw-inventory.json.sha256",
        ]:
            archive.add(path, arcname=str(path.relative_to(raw)), recursive=False)


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
    proof = result.get("verified") is True and clock.get("runtime_passed") is True
    value = {
        "phase": phase,
        "result": "PASS" if success and proof else "BLOCKED" if success else "FAIL",
        "exit_code": result.get("exit_code"),
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


def core_proof(app):
    records = {}
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
        path = app / ".t13/outputs" / (name + ".json")
        receipt = json.loads(path.read_text())
        log = app / receipt["log"]
        if (
            receipt["exit_code"] != 0
            or hashlib.sha256(log.read_bytes()).hexdigest() != receipt["log_sha256"]
        ):
            raise ValueError("CORE_RECEIPT_FAILED")
        records[name] = receipt
    pytest = (app / ".t13/outputs/pytest.txt").read_text()
    vitest = (app / ".t13/outputs/vitest.txt").read_text()
    playwright = (app / ".t13/outputs/playwright.txt").read_text()
    passed = re.findall(r"(\d+) passed", pytest)
    skipped = re.findall(r"(\d+) skipped", pytest)
    units = re.findall(r"Tests\s+(\d+) passed", vitest)
    browser = re.findall(r"(\d+) passed", playwright)
    if (
        not passed
        or int(passed[-1]) < 823
        or not skipped
        or int(skipped[-1]) != 14
        or not units
        or int(units[-1]) != 85
        or not browser
        or int(browser[-1]) != 96
    ):
        raise ValueError("CORE_COUNTS_OUTSIDE_CONTRACT")
    return {
        "pytest_passed": int(passed[-1]),
        "pytest_skipped": int(skipped[-1]),
        "vitest_passed": int(units[-1]),
        "playwright_passed": int(browser[-1]),
    }


def bge_proof(raw):
    path = raw / "verification/business-oracle.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.with_suffix(".json.sha256").read_text().strip() != digest:
        raise ValueError("ORACLE_SHA_MISMATCH")
    result = json.loads((raw / "verification/result.json").read_text())
    if (
        result["status"] != "T16_A3_TARGETED_OFFLINE_VERIFIED"
        or result["retrieval_cases"] != 14
        or result["payments"] != 0
        or result["order_status"] != "PENDING_PAYMENT"
        or result["oracle_sha256"] != digest
        or not result["owned_schemas_cleaned_after_evidence"]
    ):
        raise ValueError("BGE_RESULT_INCOMPLETE")
    # Frozen verifier validates and rereads the independent oracle before DROP.
    return result
