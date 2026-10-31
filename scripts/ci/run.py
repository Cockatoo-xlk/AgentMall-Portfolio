"""Run the offline CI command set in the disposable Linux image, with receipts."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".t13/outputs"


def record(name, argv, *, timeout=1200, cwd=ROOT, environment=None):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    log = OUTPUT / f"{name}.txt"
    if log.exists():
        raise FileExistsError(f"Preserve previous receipt: {log}")
    start = time.time()
    with log.open("xb") as stream:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Stop only the process group created by this call; retain the log.
            import signal

            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            code = 124
    receipt = {
        "name": name,
        "command": argv,
        "cwd": str(cwd),
        "exit_code": code,
        "started_unix": start,
        "elapsed_seconds": round(time.time() - start, 3),
        "log": str(log.relative_to(ROOT)),
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    }
    (OUTPUT / f"{name}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return code


def main():
    if record(
        "bootstrap", [sys.executable, "scripts/ci/bootstrap.py", "--port", "55433"]
    ):
        return 1
    from dotenv import dotenv_values

    os.environ.update(dotenv_values(ROOT / ".env.rag"))
    commands = [
        ("ruff", ["ruff", "check", "backend", "evals", "scripts"]),
        ("format", ["ruff", "format", "--check", "backend", "evals", "scripts"]),
        (
            "pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "--ci-offline-core",
                "--strict-markers",
                "-ra",
            ],
        ),
        ("typecheck", ["npm", "--prefix", "frontend", "run", "typecheck"]),
        ("lint", ["npm", "--prefix", "frontend", "run", "lint"]),
        ("vitest", ["npm", "--prefix", "frontend", "test"]),
        ("build", ["npm", "--prefix", "frontend", "run", "build"]),
        ("playwright", ["npm", "--prefix", "frontend", "run", "test:e2e"]),
    ]
    failed = [name for name, argv in commands if record(name, argv)]
    print(
        json.dumps(
            {
                "mode": "LOCAL_CI_EQUIVALENT",
                "failed_commands": failed,
                "paid_requests": 0,
                "real_bge": "NOT_RUN",
            }
        )
    )
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
