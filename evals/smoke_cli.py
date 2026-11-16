"""Explicit local product-smoke console. Default preparation never reads a key.

Run with a minimal process environment. Native operation requires a separate,
exact-binding Owner receipt; no command issues approval or consumes fees itself.
"""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from agentmall.playground.environment import private_write

from evals.product_smoke import freeze_proposal
from evals.smoke_assertions import score_verified
from evals.smoke_runner import (
    FdCredential,
    SmokeBatch,
    SmokeStopped,
    digest,
    static_admission,
    validate_price,
)
from evals.smoke_session import SmokeSession

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_SHA = "4dd539b51bc1b3162825a3721bb3e99c59d264ad9794d49db6107603fa620230"
PROTOCOL_SHA = "bd5a7a44a16b5f8e2a112a42ae2c647364b97eec407ae186250369031758d96e"


def git(*args):
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "LANG": "C", "LC_ALL": "C"},
        text=True,
    ).strip()


def prepare(proposal, protocol, price_path):
    if (
        hashlib.sha256(Path(proposal).read_bytes()).hexdigest() != PROPOSAL_SHA
        or hashlib.sha256(Path(protocol).read_bytes()).hexdigest() != PROTOCOL_SHA
    ):
        raise SmokeStopped("ORIGINAL_SMOKE_IDENTITY_REQUIRED")
    if git("status", "--porcelain=v1"):
        raise SmokeStopped("CLEAN_SOURCE_REQUIRED")
    source, tree = git("rev-parse", "HEAD", "HEAD^{tree}").splitlines()
    binding = freeze_proposal(proposal, source_commit=source, source_tree=tree)
    price = json.loads(Path(price_path).read_bytes())
    validate_price(price)
    files = git("ls-files").splitlines()
    binding.update(
        protocol_sha256=hashlib.sha256(Path(protocol).read_bytes()).hexdigest(),
        price=price,
        price_sha256=hashlib.sha256(Path(price_path).read_bytes()).hexdigest(),
        source_files={
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in files
        },
        proposal=json.loads(Path(proposal).read_bytes()),
        operator="TEST_OPERATOR_CODEX",
        authorization_state="OWNER_APPROVAL_REQUIRED",
        actual_supplier_invoice="UNKNOWN_REPORTED_SEPARATELY_FROM_SETTLED_USAGE",
        runtime="FORMAL_FASTAPI_ASGI_AND_NATIVE_CHATDEEPSEEK_HTTPS",
        admission=static_admission(json.loads(Path(proposal).read_bytes())),
    )
    return binding


def validate_binding(binding):
    if (
        git("status", "--porcelain=v1")
        or git("rev-parse", "HEAD") != binding["source_commit"]
        or git("rev-parse", "HEAD^{tree}") != binding["source_tree"]
    ):
        raise SmokeStopped("SOURCE_BINDING_MISMATCH")
    original = ROOT / "evals/proposals/v217-product-smoke.json"
    protocol = ROOT / "docs/V217_LIVE_SMOKE.md"
    if (
        hashlib.sha256(original.read_bytes()).hexdigest() != PROPOSAL_SHA
        or hashlib.sha256(protocol.read_bytes()).hexdigest() != PROTOCOL_SHA
        or json.loads(original.read_bytes()) != binding["proposal"]
        or set(binding["source_files"]) != set(git("ls-files").splitlines())
    ):
        raise SmokeStopped("FROZEN_SMOKE_MISMATCH")
    for name, expected in binding["source_files"].items():
        path = ROOT / name
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(ROOT.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise SmokeStopped("SOURCE_FILE_MISMATCH")
    validate_price(binding["price"])
    if static_admission(binding["proposal"])["codes"]:
        raise SmokeStopped("FROZEN_TASK_CONTRACT_INCOMPATIBLE")


class ConsoleInput:
    """Nonblocking pipe/TTY bytes; partial lines cannot suspend either deadline."""

    def __init__(self, fd):
        self.fd, self.buffer, self.eof = fd, bytearray(), False

    def pop_line(self):
        end = self.buffer.find(b"\n")
        if end < 0 and not self.eof:
            return None
        end = end + 1 if end >= 0 else len(self.buffer)
        raw = bytes(self.buffer[:end])
        del self.buffer[:end]
        try:
            return raw.decode()
        except UnicodeError:
            raise SmokeStopped("COMMAND_ENCODING_INVALID") from None

    async def line(self, seconds=None):
        buffered = self.pop_line()
        if buffered is not None:
            return buffered
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        blocking = os.get_blocking(self.fd)
        os.set_blocking(self.fd, False)

        def readable():
            if ready.done():
                return
            try:
                data = os.read(self.fd, 4096)
                self.eof = not data
                self.buffer.extend(data)
                if len(self.buffer) > 16384:
                    raise SmokeStopped("COMMAND_TOO_LARGE")
                line = self.pop_line()
                if line is not None:
                    ready.set_result(line)
            except BlockingIOError:
                return
            except (OSError, SmokeStopped) as exc:
                ready.set_exception(exc)

        loop.add_reader(self.fd, readable)
        try:
            async with asyncio.timeout(seconds):
                return await ready
        finally:
            loop.remove_reader(self.fd)
            os.set_blocking(self.fd, blocking)


async def operate(args):
    binding = json.loads(args.binding.read_bytes())
    validate_binding(binding)
    args.state_dir.mkdir(mode=0o700)  # Never attach/restart an old execution.
    gate = SmokeBatch(
        args.state_dir / "batch.json",
        binding["proposal"],
        digest(binding),
        mode="LIVE_DEEPSEEK",
        approval=args.owner_receipt,
        verify_source=lambda: validate_binding(binding),
    )
    config = json.loads(args.database_config.read_bytes())
    session, inspection = None, None
    console_input = ConsoleInput(sys.stdin.fileno())
    try:
        while True:
            gate.check()
            line = await console_input.line(
                gate.remaining()
                if gate.read()["tasks"]
                and gate.read()["tasks"][-1]["state"] != "VERIFIED"
                else None
            )
            if not line:
                break
            command = json.loads(line)
            op = command.pop("op")
            if op == "arm" and set(command) == {"task_id"}:
                if session and (
                    session.provider is not None or session.client is not None
                ):
                    raise SmokeStopped("CLOSE_PREVIOUS_TASK_FIRST")
                validate_binding(binding)
                row = gate.arm(command["task_id"])
                session = SmokeSession(gate, args.state_dir / row["execution_id"])
                result = row
            elif op == "initialize" and session and set(command) == {"credential_fd"}:
                fd = command["credential_fd"]
                if type(fd) is not int or fd <= 2:
                    raise SmokeStopped("SEPARATE_ANONYMOUS_FD_REQUIRED")
                await session.initialize(
                    config["database_url"],
                    binding["price"],
                    key_source=FdCredential(fd),
                )
                result = {"phase": "READY", "thread_id": session.thread_id}
            elif op == "start" and session and not command:
                result = await session.start()
            elif op == "inspect" and session and not command:
                inspection = await session.inspect()
                result = {
                    "inspection_sha256": digest(inspection),
                    "run_id": inspection["run"]["id"],
                    "thread_id": session.thread_id,
                    "proposal": inspection["proposal"],
                    "budget": inspection["run"]["budget"],
                }
            elif (
                op in {"approve", "reject"}
                and session
                and set(command) == {"inspection_sha256"}
            ):
                if inspection is None or command["inspection_sha256"] != digest(
                    inspection
                ):
                    raise SmokeStopped("INSPECT_PROPOSAL_FIRST")
                result = await session.decide(
                    inspection, op, operator="TEST_OPERATOR_CODEX"
                )
            elif (
                op == "resume"
                and session
                and inspection
                and set(command) == {"confirmation_id", "request_id"}
            ):
                result = await session.resume(
                    inspection, command["confirmation_id"], command["request_id"]
                )
            elif op == "freeze" and session and not command:
                value, _ = await session.freeze_export_verify()
                result = {"evidence_sha256": value, "phase": "VERIFIED"}
            elif op == "score" and session and not command:
                result = score_verified(session.directory)
                private_write(session.directory / "score.json", result)
                if result["status"] == "NOT_SCORED":
                    gate.stop("EVIDENCE_OR_USAGE_UNRESOLVED")
                else:
                    value = json.loads(
                        (session.directory / "verified.json").read_bytes()
                    )["sha256"]
                    gate.verified(value)
            elif (
                op == "cleanup"
                and session
                and set(command) == {"owner_cleanup_reference"}
            ):
                await session.close()
                await session.cleanup(command["owner_cleanup_reference"])
                result = {"phase": "OWNED_SCHEMAS_REMOVED"}
            elif op == "close" and session and not command:
                await session.close()
                result = {"phase": "MODEL_CLIENTS_CLOSED", "resources": "PRESERVED"}
            else:
                raise SmokeStopped("COMMAND_OR_FIELDS_INVALID")
            # Do not print full Run messages, JWTs, private runtime state or Provider payloads.
            if (
                isinstance(result, dict)
                and "thread_id" in result
                and "request_id" in result
            ):
                result = {
                    k: result.get(k)
                    for k in (
                        "id",
                        "thread_id",
                        "request_id",
                        "status",
                        "budget",
                        "pending_confirmation",
                        "last_error",
                    )
                }
            print(json.dumps(result, ensure_ascii=False), flush=True)
    except BaseException as exc:  # noqa: BLE001 - fail closed and suppress private exception text
        code = (
            str(exc) if isinstance(exc, SmokeStopped) else "OPERATOR_OR_RUNTIME_STOPPED"
        )
        gate.stop(code)
        forensic = "NOT_AVAILABLE"
        if session and session.client and session.start_request_id:
            try:
                # Only GET/SQL SELECT/export remain reachable; no re-ARM,
                # settlement, approval, Resume or cleanup is attempted here.
                async with asyncio.timeout(10):
                    value, _ = await session.freeze_export_verify()
                forensic = {"state": "READ_ONLY_VERIFIED", "sha256": value}
            except BaseException:  # noqa: BLE001 - fail closed and suppress private exception text
                forensic = "EXPORT_UNAVAILABLE_RESOURCES_PRESERVED"
        print(
            json.dumps(
                {
                    "state": "STOPPED",
                    "code": code,
                    "resources": "PRESERVED",
                    "forensic": forensic,
                }
            ),
            flush=True,
        )
        return 1
    finally:
        if session:
            await session.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepared = sub.add_parser("prepare")
    prepared.add_argument("--proposal", type=Path, required=True)
    prepared.add_argument("--protocol", type=Path, required=True)
    prepared.add_argument("--price", type=Path, required=True)
    prepared.add_argument("--output", type=Path, required=True)
    console = sub.add_parser("operate")
    for name in ("binding", "owner-receipt", "database-config", "state-dir"):
        console.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            binding = prepare(args.proposal, args.protocol, args.price)
            fd = os.open(
                args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "w") as stream:
                json.dump(binding, stream, indent=2, ensure_ascii=False)
            print(
                json.dumps(
                    {
                        "state": "ADMISSION_BLOCKED"
                        if binding["admission"]["codes"]
                        else "PREPARED_UNAUTHORIZED",
                        "binding_sha256": digest(binding),
                        "episodes": 0,
                        "provider_requests": 0,
                        "key_reads": 0,
                    }
                )
            )
            return 1 if binding["admission"]["codes"] else 0
        return asyncio.run(operate(args))
    except (OSError, ValueError, KeyError):
        print(
            json.dumps(
                {"state": "ADMISSION_BLOCKED", "code": "BINDING_OR_OWNER_REQUIRED"}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
