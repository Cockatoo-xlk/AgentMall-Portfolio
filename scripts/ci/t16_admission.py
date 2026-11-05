"""One-shot CI admission harness. No Live provider or authorization entry point."""

import argparse
import ast
import hashlib
import json
import os
import platform
import secrets
import shutil
import signal
import stat
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath

from t16_cache import cleanup_runtime, create_runtime
from t16_clock import Monitor
from t16_evidence import (
    bge_proof,
    bundle,
    core_proof,
    encrypt,
    public_summary,
    schema_report,
    validate_certificate,
    write_json,
)

SOURCE = "77b215878edbce50ce107c6e77e31de4d2044ff9"
FINGERPRINT = "1e54c1f0d0b76ff0a975fbcc9938008336febbf1a1c8c5564253a23f4a901e27"
PG = (
    "pgvector/pgvector:0.8.7-pg17-bookworm@sha256:"
    "ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
)
PYTHON = (
    "python:3.12.10-slim-bookworm@sha256:"
    "fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db"
)


def identity(environment, approved):
    required = {
        "GITHUB_REPOSITORY": "Cockatoo-xlk/AgentMall-Portfolio",
        "GITHUB_REF": "refs/heads/codex/t16-a3-ci-verify",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": approved,
    }
    if len(approved) != 40 or any(c not in "0123456789abcdef" for c in approved):
        raise ValueError("APPROVED_SHA_REQUIRED")
    if any(environment.get(k) != v for k, v in required.items()):
        raise ValueError("EXECUTION_IDENTITY_MISMATCH")


def safe_environment(environment):
    # Select names before reading values. Provider/proxy/Actions credentials excluded.
    allowed = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "RUNNER_TEMP"}
    result = {k: environment[k] for k in allowed if k in environment}
    return result | {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "CI": "true",
    }


def fingerprint(app):
    tree = ast.parse((app / "backend/src/agentmall/playground/policy.py").read_text())
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "source_fingerprint"
    )
    scope = {"ROOT": app, "hashlib": hashlib, "json": json}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "fingerprint", "exec"),
        scope,
    )
    return scope["source_fingerprint"]()


def stop_tree(pid):
    """Freeze descendants before termination, including setsid children from core CI."""
    targets = {pid}
    try:
        os.kill(pid, signal.SIGSTOP)
    except ProcessLookupError:
        pass
    stable = 0
    for _ in range(64):
        previous = len(targets)
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = path.read_text().rsplit(")", 1)[1].split()
                if int(fields[1]) in targets:
                    targets.add(int(path.parent.name))
            except (OSError, ValueError, IndexError):
                continue
        for target in targets:
            try:
                os.kill(target, signal.SIGSTOP)
            except ProcessLookupError:
                pass
        stable = stable + 1 if len(targets) == previous else 0
        if stable >= 2:
            break
    else:
        raise RuntimeError("DESCENDANT_DISCOVERY_DID_NOT_CONVERGE")
    for target in targets:
        try:
            os.kill(target, signal.SIGKILL)
        except ProcessLookupError:
            pass


def guest_identity(uid, gid):
    if any(type(value) is not int or not 0 < value < 2**31 for value in (uid, gid)):
        raise ValueError("NONROOT_HOST_IDENTITY_REQUIRED")
    return f"{uid}:{gid}"


def stage_public_helpers(source, destination):
    """Docker COPY makes these public code files root-owned; guest still needs read access."""
    destination.mkdir(mode=0o755)
    destination.chmod(0o755)
    for name in ("t16_clock.py", "t16_models.py", "t16_cache.py", "T16Bge.Dockerfile"):
        target = destination / name
        shutil.copyfile(source / name, target)
        target.chmod(0o644)  # Nonsecret reviewed source only, never private evidence/state.


def stage_public_source(archive, destination):
    """Stage only the frozen public Git archive, never evidence or a pre-existing tree.

    tar's data filter leaves directory modes to mkdir/umask. With our private 077
    umask that means 0700, which Docker COPY preserves under root ownership.
    Normalize this disposable public copy before COPY; keep its private parent,
    archive, runtime state and all evidence untouched.
    """
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if any(
            not (entry.isfile() or entry.isdir())
            or PurePosixPath(entry.name).is_absolute()
            or ".." in PurePosixPath(entry.name).parts
            for entry in members
        ):
            raise ValueError("UNSAFE_PUBLIC_SOURCE_ARCHIVE")
        destination.mkdir(mode=0o755, exist_ok=False)
        source.extractall(destination, members=members, filter="data")
    destination.chmod(0o755)
    for path in destination.rglob("*"):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            path.chmod(0o755)
        elif stat.S_ISREG(info.st_mode):
            path.chmod(0o755 if info.st_mode & 0o111 else 0o644)
        else:
            raise ValueError("UNSAFE_PUBLIC_SOURCE_ENTRY")


class Execution:
    def __init__(self, args):
        self.args = args
        self.app = args.app.resolve()
        self.harness = Path(__file__).parent
        self.root = args.output.resolve()
        self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.raw = self.root / "raw"
        self.raw.mkdir(mode=0o700)
        self.public = self.root / "publish"
        self.public.mkdir(mode=0o700)
        self.environment = safe_environment(os.environ)
        self.name = "am-t16-" + secrets.token_hex(6)
        self.pg, self.guest = self.name + "-pg", self.name + "-guest"
        self.volume = self.name + "-data"
        self.created = []
        self.monitor = None
        self.active = None
        self.workload_stopped = True
        self.guest_fenced = True
        self.sequence = 0
        self.deadline = time.monotonic() + 2400
        self.result = {"exit_code": None, "verified": False}
        self.clock = {"admission_passed": False, "runtime_passed": False}

    def command(self, argv, *, cwd=None, timeout=900, monitor=False, output=None, export=False):
        self.sequence += 1
        log = output or self.raw / f"command-{self.sequence:02d}.log"
        start = time.monotonic()
        external = monitor and self.args.phase == "bge"
        if external:
            self.guest_fenced = False
        with log.open("xb") as stream:
            self.active = subprocess.Popen(
                argv,
                cwd=cwd or self.app,
                env=self.environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.workload_stopped = False
            try:
                while self.active.poll() is None:
                    if time.monotonic() - start > timeout or (
                        not export and time.monotonic() > self.deadline
                    ):
                        raise TimeoutError("BOUNDED_COMMAND_TIMEOUT")
                    if monitor:
                        self.monitor.check()
                    time.sleep(0.01 if monitor else 0.1)
                code = self.active.returncode
                self.workload_stopped = not external or code == 0
                if self.workload_stopped:
                    self.guest_fenced = True
            except BaseException:
                # Fence owned business writes before descendant termination.
                try:
                    for container in [self.pg]:
                        try:
                            subprocess.run(
                                ["docker", "pause", container],
                                check=False,
                                capture_output=True,
                                timeout=15,
                            )
                        except (OSError, subprocess.SubprocessError):
                            pass  # Termination below must still run.
                finally:
                    if external:
                        self.guest_fenced = self.fence_guest()
                    stop_tree(self.active.pid)
                    self.active.wait(timeout=10)
                    self.workload_stopped = self.guest_fenced
                raise
            finally:
                if self.active.poll() is not None:
                    self.active = None
        write_json(
            self.raw / f"command-{self.sequence:02d}.json",
            {
                "argv": argv,
                "exit_code": code,
                "elapsed_seconds": time.monotonic() - start,
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            },
        )
        if code:
            if external:
                self.guest_fenced = self.fence_guest()
                self.workload_stopped = self.guest_fenced
            raise RuntimeError("COMMAND_FAILED")

    def fence_guest(self):
        # A dead docker exec CLI alone cannot fence the process owned by dockerd.
        for operation in ("pause", "kill"):
            try:
                result = subprocess.run(
                    ["docker", operation, self.guest], check=False, capture_output=True, timeout=15
                )
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False

    def setup(self):
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise ValueError("UBUNTU_AMD64_REQUIRED")
        release = Path("/etc/os-release").read_text()
        if 'VERSION_ID="24.04"' not in release or "ID=ubuntu" not in release:
            raise ValueError("UBUNTU_24_04_REQUIRED")
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.app, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=self.app, text=True)
        if sha != SOURCE or dirty or fingerprint(self.app) != FINGERPRINT:
            raise ValueError("FROZEN_PRODUCT_MISMATCH")
        if shutil.disk_usage(self.root).free < 8 * 1024**3:
            raise ValueError("INSUFFICIENT_DISK_NO_AUTOMATIC_CLEANUP")
        mem = int(Path("/proc/meminfo").read_text().split("MemTotal:")[1].split()[0])
        if mem < 12 * 1024**2:
            raise ValueError("INSUFFICIENT_MEMORY")
        self.cert = self.raw / "recipient.pem"
        self.cert.write_text(os.environ["RECIPIENT_CERT_PEM"])
        validate_certificate(self.cert, self.args.certificate_sha)
        write_json(
            self.raw / "identity.json",
            {
                "product_sha": sha,
                "product_fingerprint": fingerprint(self.app),
                "ci_sha": self.args.ci_commit,
                "phase": self.args.phase,
                "os_release": release,
                "architecture": platform.machine(),
                "memory_kib": mem,
                "owner": self.name,
            },
        )
        self.environment["UV_NO_CACHE"] = "1"
        if self.args.phase == "core":
            self.command(
                [
                    "uv",
                    "sync",
                    "--project",
                    "backend",
                    "--locked",
                    "--no-extra",
                    "embedding",
                ]
            )
            self.command(["npm", "--prefix", "frontend", "ci"])
            self.environment["PLAYWRIGHT_BROWSERS_PATH"] = str(
                self.app / "frontend/.cache/ms-playwright"
            )
            self.command(
                [
                    "npx",
                    "--no-install",
                    "playwright",
                    "install",
                    "--with-deps",
                    "chromium",
                ],
                cwd=self.app / "frontend",
            )
            self.command(["docker", "pull", PYTHON])
        else:
            context = self.raw / "build"
            archive = self.raw / "source.tar"
            self.command(["git", "archive", "--format=tar", SOURCE], output=archive)
            stage_public_source(archive, context)
            stage_public_helpers(self.harness, context / "ci_harness")
            self.command(
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "-f",
                    "ci_harness/T16Bge.Dockerfile",
                    "-t",
                    self.name + ":bge",
                    ".",
                ],
                cwd=context,
                timeout=1200,
            )
            shutil.rmtree(context)  # Only this invocation's disposable source copy, not evidence.
            # Retain the exact frozen source archive and its command receipt in encrypted evidence.
        self.command(["docker", "pull", PG])
        self.password = secrets.token_hex(24)
        config = self.raw / "postgres.env"
        config.write_text(
            f"POSTGRES_USER=agentmall\nPOSTGRES_DB=agentmall_test\nPOSTGRES_PASSWORD={self.password}\n"
        )
        self.command(["docker", "volume", "create", self.volume])
        self.created.append(("volume", self.volume))
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.pg,
                "--memory",
                "1g",
                "--cpus",
                "1",
                "--env-file",
                str(config),
                "-p",
                "127.0.0.1:55433:5432",
                "-v",
                self.volume + ":/var/lib/postgresql/data",
                PG,
            ]
        )
        self.created.append(("container", self.pg))
        for _ in range(60):
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.pg,
                    "pg_isready",
                    "-U",
                    "agentmall",
                    "-d",
                    "agentmall_test",
                ],
                capture_output=True,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("POSTGRES_NOT_READY")
        if self.args.phase == "bge":
            user = guest_identity(os.geteuid(), os.getegid())
            runtime = self.root / "guest-runtime"
            create_runtime(runtime, self.name)
            env_file = self.raw / "verification.env"
            env_file.write_text(
                f"AGENTMALL_TEST_DATABASE_URL=postgresql+psycopg://agentmall:{self.password}@127.0.0.1:55433/agentmall_test\n"
            )
            self.command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self.guest,
                    "--user",
                    user,
                    "-e",
                    "HOME=/runtime/home",
                    "-e",
                    "XDG_CACHE_HOME=/runtime/cache",
                    "-e",
                    "HF_HOME=/runtime/cache/huggingface",
                    "-e",
                    "TMPDIR=/runtime/tmp",
                    "-e",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "--network",
                    "host",
                    "--memory",
                    "8g",
                    "--cpus",
                    "3",
                    "--env-file",
                    str(env_file),
                    "-v",
                    str(self.raw) + ":/private",
                    "-v",
                    str(runtime) + ":/runtime",
                    "--mount",
                    f"type=bind,source={runtime / 'ml-cache'},target=/work/.ml-cache",
                    self.name + ":bge",
                    "sleep",
                    "infinity",
                ]
            )
            guest_script = "/work/ci_harness/t16_clock.py"
        else:
            self.command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self.guest,
                    "--network",
                    "none",
                    "--memory",
                    "128m",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "-v",
                    str(self.harness) + ":/ci:ro",
                    PYTHON,
                    "sleep",
                    "infinity",
                ]
            )
            guest_script = "/ci/t16_clock.py"
        self.created.append(("container", self.guest))
        if self.args.phase == "bge":
            # Check the full entry point as the actual guest, not just the clock helper.
            self.command(
                ["docker", "exec", self.guest, "python", "scripts/verify_t16_a3.py", "--help"],
                timeout=30,
            )
            self.command(
                [
                    "docker",
                    "exec",
                    self.guest,
                    "python",
                    "/work/ci_harness/t16_cache.py",
                    "--owner",
                    self.name,
                    "--uid",
                    str(os.geteuid()),
                    "--gid",
                    str(os.getegid()),
                ],
                timeout=120,
            )
        self.monitor = Monitor(self.guest, guest_script, self.raw)

    def verify(self):
        self.monitor.admit()
        self.clock["admission_passed"] = True
        runtime = time.monotonic()
        if self.args.phase == "core":
            self.environment["AGENTMALL_CI_DB_PASSWORD"] = self.password
            self.environment["PATH"] = (
                str(self.app / "backend/.venv/bin") + ":" + self.environment["PATH"]
            )
            self.command(
                [str(self.app / "backend/.venv/bin/python"), "scripts/ci/run.py"],
                timeout=1500,
                monitor=True,
            )
            self.result["counts"] = core_proof(self.app)
        else:
            self.command(
                [
                    "docker",
                    "exec",
                    self.guest,
                    "sh",
                    "-c",
                    "umask 077; exec strace -f -yy -e trace=openat,fsync,close "
                    "-o /private/fsync.strace python scripts/verify_t16_a3.py "
                    "--output /private/verification --state-dir /private/state",
                ],
                timeout=1200,
                monitor=True,
            )
            bge_proof(self.raw, self.app)
        while time.monotonic() - runtime < 900:
            self.monitor.check()
            if time.monotonic() > self.deadline:
                raise TimeoutError("RUNTIME_OBSERVATION_INCOMPLETE")
            time.sleep(0.01)
        self.monitor.check()
        self.clock["runtime_passed"] = True
        self.clock["runtime_seconds"] = time.monotonic() - runtime
        self.result.update(exit_code=0, verified=True)

    def cleanup_owned(self):
        roles = {
            ("container", self.pg): "postgres",
            ("container", self.guest): "guest",
            ("volume", self.volume): "postgres_data",
        }
        if len(set(self.created)) != len(self.created) or any(
            pair not in roles for pair in self.created
        ):
            raise ValueError("UNOWNED_CLEANUP_REFUSED")
        checks = []
        for kind, name in reversed(self.created):
            check = {
                "kind": kind,
                "role": roles[(kind, name)],
                "remove_exit": None,
                "absence_exit": None,
                "verified_absent": False,
            }
            try:
                argv = (
                    ["docker", "rm", "-f", name]
                    if kind == "container"
                    else ["docker", "volume", "rm", name]
                )
                removed = subprocess.run(argv, check=False, capture_output=True, timeout=30)
                check["remove_exit"] = removed.returncode
                if removed.returncode == 0:
                    query = (
                        ["docker", "ps", "--all", "--quiet", "--filter", f"name=^/{name}$"]
                        if kind == "container"
                        else ["docker", "volume", "ls", "--quiet", "--filter", f"name=^{name}$"]
                    )
                    observed = subprocess.run(query, check=False, capture_output=True, timeout=15)
                    check["absence_exit"] = observed.returncode
                    check["verified_absent"] = (
                        observed.returncode == 0 and not observed.stdout.strip()
                    )
            except (OSError, subprocess.SubprocessError):
                pass  # UNKNOWN is never interpreted as removed.
            checks.append(check)
        return checks

    def finish(self):
        errors = []

        def collect(name, operation):
            try:
                return True, operation()
            except Exception as exc:
                errors.append({"operation": name, "error_type": type(exc).__name__})
                return False, None

        if self.active is not None:

            def terminate():
                stop_tree(self.active.pid)
                self.active.wait(timeout=10)
                self.workload_stopped = self.guest_fenced

            collect("terminate", terminate)
        if self.monitor and not collect("close_clock", self.monitor.close)[0]:
            self.clock["runtime_passed"] = False
        if (self.app / ".t13").exists():
            collect(
                "core_logs",
                lambda: shutil.move(str(self.app / ".t13"), self.raw / "core-originals"),
            )
        if ("container", self.pg) in self.created:
            if self.workload_stopped:
                collect(
                    "unpause_db",
                    lambda: subprocess.run(
                        ["docker", "unpause", self.pg], check=False, capture_output=True, timeout=10
                    ),
                )
                collect(
                    "database_dump",
                    lambda: self.command(
                        [
                            "docker",
                            "exec",
                            self.pg,
                            "pg_dump",
                            "-U",
                            "agentmall",
                            "-d",
                            "agentmall_test",
                            "-Fc",
                        ],
                        timeout=90,
                        output=self.raw / "database.dump",
                        export=True,
                    ),
                )
            else:
                errors.append({"operation": "database_dump", "error_type": "WORKLOAD_NOT_STOPPED"})
        for kind, name in self.created:
            if kind == "container":
                collect(
                    "inspect_container",
                    lambda name=name: self.command(
                        ["docker", "inspect", name], timeout=10, export=True
                    ),
                )

        # Independent originals, not child stdout, are the cleanup prerequisite.
        schema_state = "UNKNOWN"
        if self.args.phase == "bge":
            originals_ok, _ = collect("required_originals", lambda: bge_proof(self.raw, self.app))
            if originals_ok:
                schema_state = "DROPPED_BY_FROZEN_VERIFIER_VALIDATED_ORACLE"
            else:
                schema_state = schema_report(self.raw)
        else:
            originals_ok, _ = collect(
                "required_originals",
                lambda: core_proof(self.app, outputs=self.raw / "core-originals/outputs"),
            )
        if errors:
            self.result.update(exit_code=1, verified=False)
        write_json(self.raw / "collection-errors.json", errors)
        write_json(self.raw / "clock-summary.json", self.clock)
        write_json(
            self.raw / "result.json", self.result | {"receipt_scope": "PRE_ARCHIVE_EXECUTION"}
        )
        archive = self.root / "raw.tar.gz"
        archived_ok, state = collect(
            "strict_archive", lambda: bundle(self.raw, archive, partial=bool(errors))
        )
        if not archived_ok:
            archive = self.root / "raw-incomplete.tar.gz"
            archived_ok, state = collect(
                "partial_archive", lambda: bundle(self.raw, archive, partial=True)
            )
        self.result["evidence_complete"] = bool(
            originals_ok and archived_ok and state["complete"] and not errors
        )
        self.result["cleanup_complete"] = False
        encrypted = self.public / "raw-evidence.cms.der"
        encrypted_ok = False
        if archived_ok:
            encrypted_ok, _ = collect(
                "encryption",
                lambda: encrypt(archive, self.cert, self.args.certificate_sha, encrypted),
            )
        if not encrypted_ok:
            self.result["evidence_complete"] = False
        checks = []
        runtime_cleanup = {"verified_absent": False, "state": "RETAINED_OR_NOT_CREATED"}
        if self.result["evidence_complete"] and encrypted_ok:
            clean_ok, checks = collect("cleanup", self.cleanup_owned)
            checks = checks or []
            self.result["cleanup_complete"] = bool(
                clean_ok and all(c["verified_absent"] for c in checks)
            )
            if self.result["cleanup_complete"] and self.args.phase == "bge":
                runtime_ok, runtime_cleanup = collect(
                    "runtime_cleanup",
                    lambda: cleanup_runtime(self.root / "guest-runtime", self.name),
                )
                runtime_cleanup = runtime_cleanup or {"verified_absent": False, "state": "UNKNOWN"}
                self.result["cleanup_complete"] = bool(
                    runtime_ok and runtime_cleanup["verified_absent"]
                )
            if not self.result["cleanup_complete"]:
                errors.append({"operation": "cleanup", "error_type": "REMOVAL_UNVERIFIED"})
        if errors:
            self.result.update(exit_code=1, verified=False)
        summary = public_summary(self.args.phase, self.result, self.clock)
        summary.update(
            evidence_state="COMPLETE" if self.result["evidence_complete"] else "INCOMPLETE",
            cleanup_checks=checks,
            runtime_cleanup=runtime_cleanup,
            cleanup_state="VERIFIED_ABSENT" if self.result["cleanup_complete"] else "NOT_VERIFIED",
            schema_cleanup=schema_state,
            database_recoverability="NOT_CLAIMED",
            collection_errors=errors,
            product_sha=SOURCE,
            product_fingerprint=FINGERPRINT,
            ci_sha=self.args.ci_commit,
        )
        if encrypted_ok:
            summary.update(
                ciphertext_sha256=hashlib.sha256(encrypted.read_bytes()).hexdigest(),
                originals_tar_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
        write_json(self.public / "summary.json", summary)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("core", "bge"), required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ci-commit", required=True)
    parser.add_argument("--certificate-sha", required=True)
    args = parser.parse_args()
    identity(os.environ, args.ci_commit)
    run = Execution(args)
    try:
        run.setup()
        run.verify()
    except Exception as exc:
        run.result.update(exit_code=1, error_type=type(exc).__name__)
    try:
        run.finish()
    except Exception:
        # No raw exception text, logs or arbitrary JSON is printed to public Actions logs.
        print("BLOCKED_EVIDENCE_EXPORT_OR_CLEANUP; retain this runner's private originals")
        return 2
    print(json.dumps(public_summary(args.phase, run.result, run.clock)))
    return run.result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
