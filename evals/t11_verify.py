"""Record exact local verification commands without persisting the environment's secrets."""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "evals/evidence/t11"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+", args.label) or not args.command:
        parser.error("Use a simple label and an explicit argv command")
    DEST.mkdir(parents=True, exist_ok=True)
    log = DEST / (args.label + ".txt")
    metadata = DEST / (args.label + ".command.json")
    if log.exists() or metadata.exists():
        parser.error(
            "Evidence already exists; choose a new label, never overwrite an attempt"
        )
    started = datetime.now(UTC).isoformat()
    begin = time.monotonic()
    process = subprocess.Popen(
        args.command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        timed_out = True
        # Only our newly created process group. Give fixture shutdown a chance to unwind.
        for sig, seconds in [
            (signal.SIGINT, 15),
            (signal.SIGTERM, 5),
            (signal.SIGKILL, 5),
        ]:
            os.killpg(process.pid, sig)
            try:
                output, _ = process.communicate(timeout=seconds)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            raise RuntimeError("Owned verification process did not terminate") from None
    output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
    # Preserve every failure and statistic; normalize only presentation whitespace.
    output = "\n".join(line.rstrip() for line in output.splitlines()).strip() + "\n"
    log.write_text(output)
    code = 124 if timed_out else process.returncode
    result = {
        "argv": args.command,
        "cwd": str(ROOT),
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(time.monotonic() - begin, 3),
        "exit_code": code,
        "timed_out": timed_out,
        "environment": {
            k: os.environ[k]
            for k in (
                "AGENTMALL_T11_EVIDENCE_DIR",
                "AGENTMALL_EVIDENCE_DIR",
                "AGENTMALL_WORKFLOW_EVIDENCE_DIR",
            )
            if k in os.environ
        },
        "log": str(log.relative_to(ROOT)),
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "reported_pass_counts": re.findall(r"(\d+) passed", output),
    }
    metadata.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    print(output[-4000:], flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
