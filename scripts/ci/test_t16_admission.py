"""Synthetic, no-network tests for the CI harness, not product acceptance."""

import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class PublicSourceTests(unittest.TestCase):
    def source_archive(self, root):
        import io
        import tarfile

        archive = root / "source.tar"
        with tarfile.open(archive, "w") as stream:
            for name in ("scripts", "backend", "backend/src"):
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o775
                stream.addfile(entry)
            for name, mode, data in [
                ("scripts/verify_t16_a3.py", 0o664, b"print('verified entry')\n"),
                ("backend/src/public.py", 0o664, b"VALUE = 42\n"),
                ("scripts/executable", 0o775, b"#!/bin/sh\nexit 0\n"),
            ]:
                entry = tarfile.TarInfo(name)
                entry.mode, entry.size = mode, len(data)
                stream.addfile(entry, io.BytesIO(data))
        return archive

    def test_complete_public_source_is_traversable_under_private_umask(self):
        import t16_admission

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.source_archive(root)
            before = archive.read_bytes()
            private = root / "raw"
            private.mkdir(mode=0o700)
            (private / "oracle.json").write_bytes(b"synthetic private oracle")
            (private / "oracle.json").chmod(0o600)
            previous = os.umask(0o077)
            try:
                t16_admission.stage_public_source(archive, private / "build")
            finally:
                os.umask(previous)
            context = private / "build"
            for name in (".", "scripts", "backend", "backend/src"):
                self.assertEqual((context / name).stat().st_mode & 0o777, 0o755)
            self.assertEqual(
                (context / "scripts/verify_t16_a3.py").read_bytes(),
                b"print('verified entry')\n",
            )
            self.assertEqual(
                (context / "scripts/verify_t16_a3.py").stat().st_mode & 0o777, 0o644
            )
            self.assertEqual(
                (context / "scripts/executable").stat().st_mode & 0o777, 0o755
            )
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
            self.assertEqual((private / "oracle.json").stat().st_mode & 0o777, 0o600)

    def test_existing_destination_is_never_normalized(self):
        from t16_admission import stage_public_source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self.source_archive(root)
            private = root / "existing"
            private.mkdir(mode=0o700)
            with self.assertRaises(FileExistsError):
                stage_public_source(archive, private)
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)

    def test_source_archive_rejects_links_special_types_and_escape(self):
        import tarfile

        from t16_admission import stage_public_source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, (name, kind) in enumerate(
                [
                    ("../escape", tarfile.REGTYPE),
                    ("/absolute", tarfile.REGTYPE),
                    ("symlink", tarfile.SYMTYPE),
                    ("hardlink", tarfile.LNKTYPE),
                    ("fifo", tarfile.FIFOTYPE),
                ]
            ):
                archive = root / f"unsafe-{index}.tar"
                with tarfile.open(archive, "w") as stream:
                    entry = tarfile.TarInfo(name)
                    entry.type, entry.linkname = kind, "../private"
                    stream.addfile(entry)
                with self.subTest(name=name), self.assertRaises(ValueError):
                    stage_public_source(archive, root / f"build-{index}")
                self.assertFalse((root / f"build-{index}").exists())


class CacheRuntimeTests(unittest.TestCase):
    def test_exclusive_private_runtime_and_safe_cleanup(self):
        from t16_cache import cleanup_runtime, create_runtime, validate_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "guest-runtime"
            create_runtime(root, "synthetic-cache-owner")
            validate_runtime(root, "synthetic-cache-owner", os.geteuid(), os.getegid())
            for entry in root.rglob("*"):
                self.assertEqual(
                    entry.stat().st_mode & 0o777, 0o700 if entry.is_dir() else 0o600
                )
            with self.assertRaises(FileExistsError):
                create_runtime(root, "synthetic-cache-owner")
            (root / "ml-cache/jieba.cache").write_bytes(b"synthetic cache")
            (root / "ml-cache/jieba.cache").chmod(0o600)
            self.assertTrue(
                cleanup_runtime(root, "synthetic-cache-owner")["verified_absent"]
            )
            self.assertFalse(root.exists())

    def test_runtime_rejects_wrong_owner_mode_links_and_missing_cache(self):
        from t16_cache import create_runtime, validate_runtime

        with tempfile.TemporaryDirectory() as tmp:
            for index, failure in enumerate(
                ("owner", "mode", "symlink", "hardlink", "missing", "fifo")
            ):
                root = Path(tmp) / str(index)
                create_runtime(root, "synthetic-cache-owner")
                if failure == "owner":
                    (root / "ml-cache/.owner.json").write_text("{}")
                elif failure == "mode":
                    (root / "ml-cache").chmod(0o755)
                elif failure == "symlink":
                    (root / "ml-cache/escape").symlink_to(tmp)
                elif failure == "hardlink":
                    os.link(root / "ml-cache/.owner.json", root / "ml-cache/linked")
                elif failure == "missing":
                    (root / "ml-cache/.owner.json").unlink()
                    (root / "ml-cache").rmdir()
                else:
                    os.mkfifo(root / "ml-cache/fifo", 0o600)
                with (
                    self.subTest(failure=failure),
                    self.assertRaises((ValueError, OSError)),
                ):
                    validate_runtime(
                        root, "synthetic-cache-owner", os.geteuid(), os.getegid()
                    )

    def test_cleanup_refuses_mismatched_identity_and_retains_runtime(self):
        from t16_cache import cleanup_runtime, create_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "guest-runtime"
            create_runtime(root, "synthetic-cache-owner")
            with self.assertRaises(ValueError):
                cleanup_runtime(root, "different-owner")
            self.assertTrue(root.is_dir())

    def test_runtime_cleanup_failure_cannot_report_complete_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _ = synthetic_pipeline(Path(tmp))
            with patch("t16_admission.cleanup_runtime", side_effect=PermissionError):
                run.finish()
            summary = json.loads((run.public / "summary.json").read_text())
            self.assertFalse(summary["cleanup_complete"])
            self.assertEqual(summary["runtime_cleanup"]["state"], "UNKNOWN")
            self.assertEqual(summary["result"], "FAIL")
            self.assertTrue((run.root / "guest-runtime/ml-cache").is_dir())

    def test_cleanup_failure_is_not_absence(self):
        from t16_cache import cleanup_runtime, create_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "guest-runtime"
            create_runtime(root, "synthetic-cache-owner")
            with (
                patch("t16_cache.shutil.rmtree", side_effect=PermissionError),
                self.assertRaises(PermissionError),
            ):
                cleanup_runtime(root, "synthetic-cache-owner")
            self.assertTrue(root.exists())


class ClockTests(unittest.TestCase):
    def test_host_log_failure_is_a_fatal_clock_event(self):
        from t16_clock import ClockGate, Monitor

        with tempfile.TemporaryDirectory() as tmp:
            monitor = Monitor.__new__(Monitor)
            monitor.output = Path(tmp) / "missing"
            monitor.host = ClockGate()
            monitor.stop = threading.Event()
            monitor.events = queue.Queue()
            monitor._host()
            self.assertFalse(monitor.events.empty())
            self.assertEqual(monitor.events.get(), "HOST_SAMPLER_ERROR")

    def test_required_guard_exists(self):
        import t16_clock

        self.assertTrue(callable(getattr(t16_clock, "ClockGate", None)))

    def test_clock_boundaries(self):
        from t16_clock import ClockGate

        for wall, mono, expected in [
            (10_000_000, 10_000_000, None),
            (-1_000_001, 10_000_000, "WALL_ROLLBACK"),
            (10_000_000, 0, "MONOTONIC_NOT_ADVANCING"),
            (110_000_001, 10_000_000, "CLOCK_RESIDUAL"),
            (-1_000_000, 10_000_000, None),
            (110_000_000, 10_000_000, None),
        ]:
            with self.subTest(wall=wall, mono=mono):
                gate = ClockGate()
                gate.sample(1_000_000_000, 1_000_000_000)
                self.assertEqual(
                    gate.sample(1_000_000_000 + wall, 1_000_000_000 + mono), expected
                )

    def test_offset_uses_bounded_round_trip_and_rejects_shift(self):
        from t16_clock import ClockGate

        gate = ClockGate()
        self.assertIsNone(gate.offset(0, 20, 10))
        self.assertIsNone(gate.offset(0, 200_000_000, 500_000_000))
        self.assertEqual(gate.offset(0, 20, 100_000_010), "HOST_GUEST_OFFSET")


class SafetyTests(unittest.TestCase):
    def test_pause_timeout_still_terminates_the_actual_workload(self):
        from t16_admission import Execution

        with tempfile.TemporaryDirectory() as tmp:
            run = Execution(
                SimpleNamespace(app=Path(tmp), output=Path(tmp) / "run", phase="core")
            )
            run.monitor = SimpleNamespace(
                check=lambda: (_ for _ in ()).throw(RuntimeError("WALL_ROLLBACK"))
            )
            processes = []
            real_popen = subprocess.Popen

            def start(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process

            try:
                with (
                    patch("t16_admission.subprocess.Popen", side_effect=start),
                    patch(
                        "t16_admission.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("synthetic pause", 1),
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    run.command(
                        [sys.executable, "-c", "import time; time.sleep(20)"],
                        monitor=True,
                    )
                self.assertIsNotNone(processes[0].poll())
                # A failed Docker exec client does not prove its container process stopped.
                run.args.phase = "bge"
                with (
                    patch(
                        "t16_admission.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("synthetic pause", 1),
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    run.command(
                        [sys.executable, "-c", "import time; time.sleep(20)"],
                        monitor=True,
                    )
                self.assertFalse(run.workload_stopped)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)

    def test_dump_failure_exports_existing_encrypted_evidence_and_fails(self):
        from t16_admission import Execution

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = Execution(
                SimpleNamespace(
                    app=root, output=root / "run", phase="bge", ci_commit="a" * 40
                )
            )
            run.cert = root / "cert.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=Synthetic Export Test",
                    "-days",
                    "1",
                    "-keyout",
                    str(root / "key.pem"),
                    "-out",
                    str(run.cert),
                ],
                check=True,
                capture_output=True,
            )
            run.args.certificate_sha = hashlib.sha256(run.cert.read_bytes()).hexdigest()
            run.created = [("container", run.pg)]
            run.result["exit_code"] = 1
            (run.raw / "existing.log").write_text("synthetic failure evidence")
            real_run = subprocess.run

            def transport(argv, **kwargs):
                if argv[0] == "docker":
                    return subprocess.CompletedProcess(argv, 0)
                return real_run(argv, **kwargs)

            with (
                patch.object(
                    run, "command", side_effect=RuntimeError("SYNTHETIC_DUMP_FAILURE")
                ),
                patch("t16_admission.subprocess.run", side_effect=transport),
            ):
                run.finish()
            self.assertTrue((run.public / "raw-evidence.cms.der").is_file())
            summary = json.loads((run.public / "summary.json").read_text())
            self.assertEqual(summary["result"], "FAIL")
            self.assertFalse(summary["evidence_complete"])

    def test_deadline_does_not_prevent_evidence_export(self):
        import sys

        from t16_admission import Execution

        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(
                app=Path(tmp), output=Path(tmp) / "owned", phase="core"
            )
            run = Execution(args)
            run.deadline = 0
            with patch("t16_admission.subprocess.run"):
                run.command(
                    [sys.executable, "-c", "print('synthetic export')"], export=True
                )
            self.assertIn("synthetic export", (run.raw / "command-01.log").read_text())

    def test_failing_counts_cannot_be_hidden_by_zero_exit_receipts(self):
        from t16_evidence import core_proof

        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            folder = app / ".t13/outputs"
            folder.mkdir(parents=True)
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
                log = folder / (name + ".txt")
                log.write_text("820 passed, 15 skipped\n")
                (folder / (name + ".json")).write_text(
                    json.dumps(
                        {
                            "exit_code": 0,
                            "log": str(log.relative_to(app)),
                            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                        }
                    )
                )
            with self.assertRaises(ValueError):
                core_proof(app)

    def test_unknown_identity_stops_before_commands(self):
        from t16_admission import identity

        base = {
            "GITHUB_REPOSITORY": "Cockatoo-xlk/AgentMall-Portfolio",
            "GITHUB_REF": "refs/heads/codex/t16-a3-ci-verify",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
        }
        identity(base, "a" * 40)
        for key, value in [
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_REF", "refs/heads/main"),
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_SHA", "b" * 40),
            ("GITHUB_REPOSITORY", "someone/else"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                identity(base | {key: value}, "a" * 40)

    def test_provider_and_actions_credentials_never_reach_children(self):
        from t16_admission import safe_environment

        result = safe_environment(
            {
                "PATH": "/bin",
                "DEEPSEEK_API_KEY": "synthetic",
                "GITHUB_TOKEN": "synthetic",
                "ACTIONS_RUNTIME_TOKEN": "synthetic",
                "HTTP_PROXY": "synthetic",
                "HOME": "/tmp",
            }
        )
        self.assertEqual(
            set(result),
            {
                "PATH",
                "HOME",
                "HF_HUB_OFFLINE",
                "TRANSFORMERS_OFFLINE",
                "HF_HUB_DISABLE_TELEMETRY",
                "CI",
            },
        )

    def test_public_summary_does_not_copy_arbitrary_results(self):
        from t16_evidence import public_summary

        value = public_summary(
            "bge",
            {
                "exit_code": 1,
                "error": "synthetic password",
                "prompt": "private synthetic prompt",
            },
            {},
        )
        text = json.dumps(value)
        self.assertNotIn("synthetic", text)
        self.assertNotIn("prompt", text)
        self.assertEqual(value["result"], "FAIL")

    def test_missing_success_proof_is_not_pass(self):
        from t16_evidence import public_summary

        self.assertEqual(
            public_summary("bge", {"exit_code": 0}, {})["result"], "BLOCKED"
        )

    def test_archive_rejects_symlinks_and_oversized_originals(self):
        from t16_evidence import bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw"
            raw.mkdir()
            (raw / "link").symlink_to("/etc/hosts")
            with self.assertRaises(ValueError):
                bundle(raw, root / "a.tgz", limit=10)
            (raw / "link").unlink()
            (raw / "big").write_bytes(b"x" * 11)
            with self.assertRaises(ValueError):
                bundle(raw, root / "b.tgz", limit=10)

    def test_encryption_uses_owner_certificate_and_preserves_hash(self):
        from t16_evidence import encrypt

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert, key = root / "cert.pem", root / "key.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=Synthetic CI Test",
                    "-days",
                    "1",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                ],
                check=True,
                capture_output=True,
            )
            raw = root / "raw.tgz"
            raw.write_bytes(b"synthetic private evidence")
            encrypted = root / "encrypted.der"
            digest = hashlib.sha256(cert.read_bytes()).hexdigest()
            encrypt(raw, cert, digest, encrypted)
            decoded = subprocess.run(
                [
                    "openssl",
                    "cms",
                    "-decrypt",
                    "-binary",
                    "-inform",
                    "DER",
                    "-in",
                    str(encrypted),
                    "-recip",
                    str(cert),
                    "-inkey",
                    str(key),
                ],
                check=True,
                capture_output=True,
            ).stdout
            self.assertEqual(decoded, b"synthetic private evidence")
            self.assertNotIn(b"synthetic private evidence", encrypted.read_bytes())
            with self.assertRaises(ValueError):
                encrypt(raw, cert, "0" * 64, root / "wrong.der")
            self.assertFalse((root / "wrong.der").exists())


class CoreProofTests(unittest.TestCase):
    """Synthetic reporter output only; original runner logs must never be fixtures."""

    PLAIN = " Test Files  13 passed (13)\n      Tests  85 passed (85)\n"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Path(self.directory.name)
        self.outputs = self.app / ".t13/outputs"
        self.outputs.mkdir(parents=True)
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
            self.write_result(name, "synthetic successful command\n")
        self.write_result("pytest", "=== 834 passed, 14 skipped in 1.0s ===\n")
        self.write_result("vitest", self.PLAIN)
        self.write_result("playwright", "  96 passed (1.0m)\n")

    def write_result(self, name, text, *, code=0):
        log = self.outputs / f"{name}.txt"
        log.write_text(text)
        (self.outputs / f"{name}.json").write_text(
            json.dumps(
                {
                    "exit_code": code,
                    "log": str(log.relative_to(self.app)),
                    "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                }
            )
        )

    def proof(self):
        from t16_evidence import core_proof

        return core_proof(self.app)

    def test_plain_report_preserves_all_frozen_counts(self):
        self.assertEqual(
            self.proof(),
            {
                "pytest_passed": 834,
                "pytest_skipped": 14,
                "vitest_passed": 85,
                "playwright_passed": 96,
            },
        )

    def test_sgr_colored_summary_is_accepted(self):
        self.write_result(
            "vitest",
            "\x1b[2m Test Files \x1b[22m \x1b[1m\x1b[32m13 passed"
            "\x1b[39m\x1b[22m\x1b[90m (13)\x1b[39m\n"
            "\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m85 passed"
            "\x1b[39m\x1b[22m\x1b[90m (85)\x1b[39m\n",
        )
        self.assertEqual(self.proof()["vitest_passed"], 85)

    def test_sgr_between_label_count_and_status_is_accepted(self):
        self.write_result(
            "vitest",
            "Test Files 13 passed (13)\n"
            "Tests\x1b[22m \x1b[1m85\x1b[39m \x1b[32mpassed\x1b[m (85)\n",
        )
        self.assertEqual(self.proof()["vitest_passed"], 85)

    def test_missing_tests_summary_is_rejected(self):
        self.write_result("vitest", "synthetic output without a reporter summary\n")
        with self.assertRaises(ValueError):
            self.proof()

    def test_test_files_only_cannot_supply_the_tests_count(self):
        self.write_result("vitest", "Test Files 85 passed (85)\n")
        with self.assertRaises(ValueError):
            self.proof()

    def test_wrong_passed_count_is_rejected(self):
        self.write_result("vitest", "Test Files 13 passed (13)\nTests 84 passed (84)\n")
        with self.assertRaises(ValueError):
            self.proof()

    def test_passed_and_total_must_agree(self):
        for line in ("Tests 85 passed (86)", "Tests 85 passed (84)", "Tests 85 passed"):
            with self.subTest(summary=line):
                self.write_result("vitest", "Test Files 13 passed (13)\n" + line + "\n")
                with self.assertRaises(ValueError):
                    self.proof()

    def test_mixed_failure_or_skip_summary_is_rejected(self):
        for line in (
            "Tests 85 passed | 1 failed (86)",
            "Tests 85 passed | 1 skipped (86)",
        ):
            with self.subTest(summary=line):
                self.write_result("vitest", "Test Files 13 passed (13)\n" + line + "\n")
                with self.assertRaises(ValueError):
                    self.proof()

    def test_duplicate_or_conflicting_summaries_are_rejected(self):
        for extra in (self.PLAIN, "Tests 84 passed (84)\n"):
            with self.subTest(extra=extra):
                self.write_result("vitest", self.PLAIN + extra)
                with self.assertRaises(ValueError):
                    self.proof()

    def test_error_messages_and_unrelated_text_cannot_supply_summary(self):
        for line in (
            "Error: Tests 85 passed (85)",
            '"Tests 85 passed (85)"',
            "Tests 85 passed (85) is an example",
            "85 passed (85)",
            "Tests 85 passed (85)",
        ):
            with self.subTest(text=line):
                self.write_result("vitest", line + "\n")
                with self.assertRaises(ValueError):
                    self.proof()

    def test_terminal_rewrite_commands_are_not_treated_as_colors(self):
        self.write_result(
            "vitest", "Test Files 13 passed (13)\nError\x1b[2K\rTests 85 passed (85)\n"
        )
        with self.assertRaises(ValueError):
            self.proof()

    def test_test_files_summary_must_be_consistent(self):
        for line in (
            "Test Files 13 passed (14)",
            "Test Files 86 passed (86)",
            "Test Files 0 passed (0)",
        ):
            with self.subTest(summary=line):
                self.write_result("vitest", line + "\nTests 85 passed (85)\n")
                with self.assertRaises(ValueError):
                    self.proof()

    def test_nonzero_exit_cannot_be_overridden_by_a_valid_summary(self):
        self.write_result("vitest", self.PLAIN, code=1)
        with self.assertRaisesRegex(ValueError, "CORE_RECEIPT_FAILED"):
            self.proof()

    def test_modified_log_is_rejected_before_summary_parsing(self):
        (self.outputs / "vitest.txt").write_text("malformed replacement\n")
        with self.assertRaisesRegex(ValueError, "CORE_RECEIPT_FAILED"):
            self.proof()

    def test_later_command_receipt_is_checked_before_summary_parsing(self):
        self.write_result("vitest", "not a valid summary\n")
        self.write_result("playwright", "96 passed (1.0m)\n", code=1)
        with self.assertRaisesRegex(ValueError, "CORE_RECEIPT_FAILED"):
            self.proof()

    def test_missing_other_stage_receipt_is_rejected(self):
        (self.outputs / "build.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.proof()

    def test_pytest_contract_is_unchanged(self):
        for text in (
            "822 passed, 14 skipped",
            "834 passed, 13 skipped",
            "834 passed, 15 skipped",
        ):
            with self.subTest(summary=text):
                self.write_result("pytest", text + "\n")
                with self.assertRaises(ValueError):
                    self.proof()

    def test_playwright_contract_is_unchanged(self):
        for text in ("95 passed (1.0m)", "97 passed (1.0m)", "no tests"):
            with self.subTest(summary=text):
                self.write_result("playwright", text + "\n")
                with self.assertRaises(ValueError):
                    self.proof()

    def test_parser_uses_the_bytes_whose_hash_was_verified(self):
        read_text = Path.read_text

        def changed_read(path, *args, **kwargs):
            if path.suffix == ".txt":
                return "unverified text\n"
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", changed_read):
            self.assertEqual(self.proof()["vitest_passed"], 85)


def synthetic_bge(raw, app):
    """New synthetic pipeline fixture, never a reconstruction of any CI Oracle."""
    import ast
    from copy import deepcopy

    from t16_evidence import write_json

    tree = ast.parse((app / "backend/tests/test_t16_a3_oracle.py").read_text())
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "sample"
    )
    function.body = [
        n for n in function.body if not isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    scope = {
        "deepcopy": deepcopy,
        "payload_hash": lambda x: hashlib.sha256(
            json.dumps(
                x, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest(),
    }
    exec(  # noqa: S102 - Execute only the repository's synthetic fixture, never CI evidence.
        compile(
            ast.Module(body=[function], type_ignores=[]), "synthetic-fixture", "exec"
        ),
        scope,
    )
    expected, observed, cp = scope["sample"]()
    from t16_admission import FINGERPRINT

    environment = "00000000-0000-4000-8000-000000000005"
    schemas = ["test_synthetic_r5", "cp_synthetic_r5"]
    write_json(
        raw / "identity.json",
        {
            "phase": "bge",
            "synthetic_pipeline_fixture": True,
            "product_fingerprint": FINGERPRINT,
            "ci_sha": "a" * 40,
        },
    )
    policy = {
        "evidence_mode": "MOCK_TRANSPORT",
        "environment_id": environment,
        "session_id": "SYNTHETIC-SESSION",
        "source_sha256": FINGERPRINT,
    }
    binding = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    files = [
        "scripts/verify_t16_a3.py",
        "backend/tests/t16_a3_oracle.py",
        "backend/tests/t16_a3_scenario.py",
        "backend/tests/t16_a3_retrieval_checks.py",
    ]
    oracle = {
        "status": "PASS",
        "synthetic_pipeline_fixture": True,
        "mode": "MOCK_TRANSPORT_REAL_BGE_PG_CHECKPOINT",
        "environment_id": environment,
        "schemas": schemas,
        "source_fingerprint": FINGERPRINT,
        "expected": expected,
        "observed": observed,
        "checkpoints": cp,
        "violations": [],
        "general_oracle": {"violations": []},
        "mock_requests": 3,
        "mock_policy_sha256": binding,
        "shared_ledger_runs": expected["run_ids"],
        "real_provider_requests": 0,
        "offline_boundary": {
            "external_attempts": 0,
            "real_provider_requests": 0,
            "real_key_read": False,
        },
        "verifier_files": {
            p: hashlib.sha256((app / p).read_bytes()).hexdigest() for p in files
        },
    }
    messages = [
        "推荐300元以内的静音键盘，不要购买。",
        "我改主意了，要支持无线连接的，预算提高到400元。",
        "就买刚才推荐的第二款，一件，送演示宿舍。",
    ]
    oracle.update(
        stages=[
            {
                "run_id": rid,
                "input": message,
                "context": {
                    "preferences": {"max_price_cents": 30000 if i == 0 else 40000},
                    "candidate_sets": [{"items": [{"id": "other"}, {"id": "sku"}]}],
                },
            }
            for i, (rid, message) in enumerate(
                zip(expected["run_ids"], messages, strict=True)
            )
        ],
        before_confirmation={
            "orders": [],
            "confirmations": [],
            "payments": [],
            "action_proposals": [deepcopy(observed["action_proposals"][0])],
        },
        repeat_added_model_requests=0,
        mock_session_id=policy["session_id"],
        checkpoint_rows=3,
    )
    verification, state = raw / "verification", raw / "state"
    verification.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    write_json(
        verification / "ownership.json",
        {
            "environment_id": environment,
            "schemas": schemas,
            "schema_state": "OWNED",
            "mode": "OFFLINE_MOCK_TRANSPORT_ONLY",
            "real_provider_requests": 0,
            "real_key_read": False,
        },
    )
    manifest = json.loads((app / "evals/data/embedding_manifest.json").read_text())
    write_json(
        verification / "model.json",
        {
            "model_id": manifest["model_id"],
            "revision": manifest["revision"],
            "dimension": 512,
            "device": "cpu",
            "files": [{"file": k, **v} for k, v in manifest["files"].items()],
        },
    )
    write_json(
        verification / "retrieval.json",
        {
            "cases": [{"case": str(i)} for i in range(14)],
            "filters_before_limit": True,
            "min_similarity": 0.45,
            "dimensions": [512],
            "mode": "REAL_BGE_REAL_PGVECTOR_POSTGRES",
        },
    )
    write_json(verification / "business-oracle.json", oracle)
    digest = hashlib.sha256(
        (verification / "business-oracle.json").read_bytes()
    ).hexdigest()
    write_json(
        verification / "result.json",
        {
            "status": "T16_A3_TARGETED_OFFLINE_VERIFIED",
            "environment_id": environment,
            "source_fingerprint": FINGERPRINT,
            "retrieval_cases": 14,
            "three_turn_candidates": [2, 2, 2],
            "payments": 0,
            "order_id": "order",
            "order_status": "PENDING_PAYMENT",
            "oracle_sha256": digest,
            "owned_schemas_cleaned_after_evidence": True,
            "real_provider_requests": 0,
            "live_authorization_created": False,
        },
    )
    write_json(
        state / "environment.json",
        {
            "state": "READY",
            "environment_id": environment,
            "settings": {"db_schema": schemas[0], "checkpoint_schema": schemas[1]},
        },
    )
    write_json(state / "mock-policy.json", policy)
    write_json(
        state / "ledger.json",
        {"binding": binding, "attempts": [{"run_id": r} for r in expected["run_ids"]]},
    )
    (state / "ledger.json.lock").touch(mode=0o600)


def synthetic_pipeline(directory):
    """No DB/model execution: exercise collection and encryption with new synthetic data."""
    from t16_admission import Execution

    app = Path(__file__).resolve().parents[2]
    run = Execution(
        SimpleNamespace(
            app=app, output=directory / "run", phase="bge", ci_commit="a" * 40
        )
    )
    synthetic_bge(run.raw, app)
    from t16_cache import create_runtime

    create_runtime(run.root / "guest-runtime", run.name)
    run.cert = directory / "synthetic.cert.pem"
    key = directory / "synthetic.key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=Synthetic R5 Pipeline",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(run.cert),
        ],
        check=True,
        capture_output=True,
    )
    run.args.certificate_sha = hashlib.sha256(run.cert.read_bytes()).hexdigest()
    run.result.update(exit_code=0, verified=True)
    # Intentionally NOT a real900-second observation; no early admission PASS allowed.
    run.clock.update(admission_passed=False, runtime_passed=False)
    return run, key


def inspect_synthetic_pipeline(run, key):
    from t16_evidence import verify_bundle

    summary = json.loads((run.public / "summary.json").read_text())
    cipher = run.public / "raw-evidence.cms.der"
    assert (
        hashlib.sha256(cipher.read_bytes()).hexdigest() == summary["ciphertext_sha256"]
    )
    decoded = run.root / "decoded.tgz"
    subprocess.run(
        [
            "openssl",
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            str(cipher),
            "-recip",
            str(run.cert),
            "-inkey",
            str(key),
            "-out",
            str(decoded),
        ],
        check=True,
        capture_output=True,
    )
    assert (
        hashlib.sha256(decoded.read_bytes()).hexdigest()
        == summary["originals_tar_sha256"]
    )
    state = verify_bundle(decoded)
    assert state["complete"] == summary["evidence_complete"]
    return summary


class EvidencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.old_umask = os.umask(0o077)
        self.addCleanup(os.umask, self.old_umask)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.raw = self.root / "raw"
        self.raw.mkdir(mode=0o700)
        self.app = Path(__file__).resolve().parents[2]

    def test_valid_bge_contract_includes_state_model_and_full_oracle(self):
        from t16_evidence import bge_proof

        synthetic_bge(self.raw, self.app)
        self.assertEqual(
            bge_proof(self.raw, self.app)["status"], "T16_A3_TARGETED_OFFLINE_VERIFIED"
        )

    def test_missing_or_corrupt_required_originals_fail_closed(self):
        from t16_evidence import bge_proof

        synthetic_bge(self.raw, self.app)
        for name in [
            "verification/business-oracle.json",
            "verification/business-oracle.json.sha256",
            "verification/model.json",
            "verification/retrieval.json",
            "verification/ownership.json",
            "verification/result.json",
            "identity.json",
            "state/environment.json",
            "state/mock-policy.json",
            "state/ledger.json",
        ]:
            path = self.raw / name
            content = path.read_bytes()
            path.unlink()
            with self.subTest(missing=name), self.assertRaises((ValueError, OSError)):
                bge_proof(self.raw, self.app)
            path.write_bytes(content)
        (self.raw / "verification/business-oracle.json.sha256").write_text("0" * 64)
        with self.assertRaises(ValueError):
            bge_proof(self.raw, self.app)

    def test_valid_hash_does_not_hide_bad_confirmation_or_checkpoint(self):
        from t16_evidence import bge_proof

        synthetic_bge(self.raw, self.app)
        path = self.raw / "verification/business-oracle.json"
        value = json.loads(path.read_text())
        value["checkpoints"][0]["pending_writes"] = 1
        path.write_text(json.dumps(value))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(".json.sha256").write_text(digest)
        result = self.raw / "verification/result.json"
        v = json.loads(result.read_text())
        v["oracle_sha256"] = digest
        result.write_text(json.dumps(v))
        with self.assertRaises(ValueError):
            bge_proof(self.raw, self.app)

    def test_archive_roundtrip_and_inventory_are_verified(self):
        from t16_evidence import bundle, verify_bundle

        (self.raw / "original").write_bytes(b"synthetic evidence")
        archive = self.root / "raw.tgz"
        result = bundle(self.raw, archive)
        self.assertTrue(result["complete"])
        self.assertTrue(verify_bundle(archive)["complete"])

    def test_mid_archive_failure_never_publishes_a_complete_archive(self):
        import tarfile

        from t16_evidence import bundle

        (self.raw / "original").write_bytes(b"synthetic evidence")
        archive = self.root / "raw.tgz"
        with (
            patch.object(
                tarfile.TarFile,
                "addfile",
                side_effect=OSError("synthetic archive failure"),
            ),
            self.assertRaises(OSError),
        ):
            bundle(self.raw, archive)
        self.assertFalse(archive.exists())

    def test_links_and_special_files_cannot_escape_archive(self):
        from t16_evidence import bundle

        outside = self.root / "outside"
        outside.write_bytes(b"synthetic external evidence")
        for kind in ["symlink", "hardlink", "fifo"]:
            path = self.raw / "escape"
            if kind == "symlink":
                path.symlink_to(outside)
            elif kind == "hardlink":
                os.link(outside, path)
            else:
                os.mkfifo(path)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                bundle(self.raw, self.root / (kind + ".tgz"))
            path.unlink()

    def test_public_pass_requires_evidence_and_verified_cleanup(self):
        from t16_evidence import public_summary

        for evidence, cleanup, runtime in [
            (False, True, True),
            (True, False, True),
            (True, True, False),
        ]:
            value = public_summary(
                "bge",
                {
                    "exit_code": 0,
                    "verified": True,
                    "evidence_complete": evidence,
                    "cleanup_complete": cleanup,
                },
                {"runtime_passed": runtime},
            )
            self.assertNotEqual(value["result"], "PASS")

    def test_nonroot_identity_and_private_runtime_are_required(self):
        from t16_admission import guest_identity

        self.assertEqual(guest_identity(1001, 1001), "1001:1001")
        for pair in [(0, 1001), (1001, 0), (-1, 1001), (True, 1001)]:
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                guest_identity(*pair)

    def test_cleanup_failure_is_recorded_even_with_complete_evidence(self):
        run, key = synthetic_pipeline(self.root)
        run.created = [("container", run.guest)]
        real_run = subprocess.run

        def transport(argv, **kw):
            if argv[0] == "docker":
                return subprocess.CompletedProcess(
                    argv, 37, stdout=b"", stderr=b"synthetic cleanup failure"
                )
            return real_run(argv, **kw)

        # The collection command is a harmless stand-in; Linux permission functions are real.
        with (
            patch.object(run, "command"),
            patch("t16_admission.subprocess.run", side_effect=transport),
        ):
            run.finish()
        summary = inspect_synthetic_pipeline(run, key)
        self.assertTrue(summary["evidence_complete"])
        self.assertFalse(summary["cleanup_complete"])
        self.assertEqual(summary["cleanup_checks"][0]["remove_exit"], 37)
        self.assertEqual(summary["result"], "FAIL")

    def test_missing_oracle_retains_encrypted_incomplete_failure_evidence(self):
        run, key = synthetic_pipeline(self.root)
        (run.raw / "verification/business-oracle.json").unlink()
        run.finish()
        summary = inspect_synthetic_pipeline(run, key)
        self.assertFalse(summary["evidence_complete"])
        self.assertFalse(summary["cleanup_complete"])
        self.assertEqual(summary["result"], "FAIL")

    def test_cleanup_must_verify_absence_not_just_zero_remove_exit(self):
        from t16_admission import Execution

        run = Execution(
            SimpleNamespace(app=self.app, output=self.root / "owned", phase="bge")
        )
        run.created = [("container", run.guest)]
        with patch(
            "t16_admission.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=b""),
                subprocess.CompletedProcess([], 0, stdout=b"still-present-id\n"),
            ],
        ):
            checks = run.cleanup_owned()
        self.assertFalse(checks[0]["verified_absent"])
        run.created = [("container", "OTHER-PROJECT")]
        with self.assertRaises(ValueError):
            run.cleanup_owned()

    def test_partial_export_reserves_room_for_inventory_and_status(self):
        from t16_evidence import bundle, encrypt, verify_bundle

        (self.raw / "large").write_bytes(b"x" * 4090)
        with self.assertRaises(ValueError):
            bundle(self.raw, self.root / "strict.tgz", limit=4096)
        status = bundle(self.raw, self.root / "partial.tgz", limit=4096, partial=True)
        self.assertFalse(status["complete"])
        self.assertFalse(
            verify_bundle(self.root / "partial.tgz", limit=4096)["complete"]
        )
        run, key = synthetic_pipeline(self.root)
        cipher = self.root / "bounded.cms.der"
        encrypt(self.root / "partial.tgz", run.cert, run.args.certificate_sha, cipher)
        decoded = self.root / "bounded-decoded.tgz"
        subprocess.run(
            [
                "openssl",
                "cms",
                "-decrypt",
                "-binary",
                "-inform",
                "DER",
                "-in",
                str(cipher),
                "-recip",
                str(run.cert),
                "-inkey",
                str(key),
                "-out",
                str(decoded),
            ],
            check=True,
            capture_output=True,
        )
        self.assertFalse(verify_bundle(decoded, limit=4096)["complete"])

    def test_three_turn_originals_and_selection_are_not_optional(self):
        from copy import deepcopy

        from t16_evidence import bge_proof

        synthetic_bge(self.raw, self.app)
        path = self.raw / "verification/business-oracle.json"
        original = json.loads(path.read_text())
        for key in [
            "stages",
            "before_confirmation",
            "repeat_added_model_requests",
            "shared_ledger_runs",
        ]:
            value = deepcopy(original)
            del value[key]
            path.write_text(json.dumps(value))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            path.with_suffix(".json.sha256").write_text(digest)
            result = self.raw / "verification/result.json"
            data = json.loads(result.read_text())
            data["oracle_sha256"] = digest
            result.write_text(json.dumps(data))
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                bge_proof(self.raw, self.app)

    def test_public_build_helpers_are_readable_without_changing_evidence_modes(self):
        from t16_admission import stage_public_helpers

        target = self.root / "ci_harness"
        stage_public_helpers(self.app / "scripts/ci", target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertEqual((target / "t16_clock.py").stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.raw.stat().st_mode & 0o777, 0o700)


def linux_ownership_suite():
    """Explicit root test driver only: real Linux credentials, no permission mocks/skips."""
    import platform
    import shutil
    import textwrap

    if platform.system() != "Linux" or os.geteuid() != 0:
        raise RuntimeError("EXPLICIT_ISOLATED_LINUX_ROOT_DRIVER_REQUIRED")

    class LinuxOwnershipTests(unittest.TestCase):
        def setUp(self):
            os.umask(0o077)
            self.directory = tempfile.mkdtemp(prefix="synthetic-r5-", dir="/sandbox")
            self.root = Path(self.directory)
            os.chown(self.root, 1001, 1001)
            self.addCleanup(shutil.rmtree, self.directory)

        def child(self, code, *, uid=1001, timeout=60):
            header = (
                "import sys,os,json; from pathlib import Path; os.umask(0o077); "
                f"sys.path.insert(0,{str(Path(__file__).parent)!r}); root=Path(sys.argv[1]); "
            )
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    header + "\n" + textwrap.dedent(code),
                    str(self.root),
                ],
                check=False,
                user=uid,
                group=uid,
                extra_groups=[],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={
                    "PATH": os.environ["PATH"],
                    "HOME": str(self.root),
                    "TMPDIR": str(self.root),
                },
            )

        def expect(self, code):
            child = self.child(code)
            self.assertEqual(child.returncode, 0, child.stderr)
            if child.stdout:
                print(child.stdout.strip(), flush=True)

        def test_root_writer_is_denied_to_nonroot_reader_and_gate_refuses(self):
            raw = self.root / "raw"
            raw.mkdir(mode=0o700)
            os.chown(raw, 1001, 1001)
            blocked = raw / "verification"
            blocked.mkdir(mode=0o700)
            (blocked / "business-oracle.json").write_text("SYNTHETIC ONLY")
            self.expect("""
                from t16_evidence import bundle
                assert os.geteuid() == os.getegid() == 1001
                try:
                    (root/'raw/verification/business-oracle.json').read_bytes()
                    raise AssertionError('kernel allowed root private file')
                except PermissionError:
                    pass
                try:
                    bundle(root/'raw', root/'bad.tgz')
                    raise AssertionError('gate accepted unreadable directory')
                except (OSError, ValueError):
                    pass
                print(json.dumps({'writer_uid':0, 'reader_uid':1001, 'kernel_denied':True}))
            """)

        def test_matching_host_identity_full_encrypted_roundtrip(self):
            self.expect("""
                from test_t16_admission import synthetic_pipeline, inspect_synthetic_pipeline
                run, key = synthetic_pipeline(root)
                path = run.raw/'verification/business-oracle.json'
                assert path.stat().st_uid == path.stat().st_gid == 1001
                assert (run.raw/'verification').stat().st_mode & 0o777 == 0o700
                assert path.stat().st_mode & 0o777 == 0o600
                run.finish()
                summary = inspect_synthetic_pipeline(run, key)
                assert summary['evidence_complete'] and summary['cleanup_complete']
                assert summary['result'] == 'BLOCKED'  # No real900-second observation.
                print(json.dumps({'uid':1001,'gid':1001,'pipeline_complete':True,
                                  'new_clock_admission':'NOT_RUN'}))
            """)

        def test_inaccessible_directory_produces_incomplete_encrypted_evidence(self):
            self.expect("""
                from test_t16_admission import synthetic_pipeline
                synthetic_pipeline(root)
            """)
            blocked = self.root / "run/raw/blocked"
            blocked.mkdir(mode=0o700)
            (blocked / "secret").write_text("SYNTHETIC UNREADABLE")
            self.expect("""
                import hashlib
                from types import SimpleNamespace
                from t16_admission import Execution
                from test_t16_admission import inspect_synthetic_pipeline
                # Reuse only this test's prior synthetic writer output in a fresh collector.
                args=SimpleNamespace(app=Path('/code'), output=root/'collector',
                                     phase='bge',ci_commit='a'*40)
                run=Execution(args)
                run.raw=root/'run/raw'
                run.cert=root/'synthetic.cert.pem'
                key=root/'synthetic.key.pem'
                args.certificate_sha=hashlib.sha256(run.cert.read_bytes()).hexdigest()
                run.result.update(exit_code=0,verified=True)
                run.finish()
                summary = inspect_synthetic_pipeline(run,key)
                assert not summary['evidence_complete'] and not summary['cleanup_complete']
                assert summary['evidence_state'] == 'INCOMPLETE'
                assert summary['result'] == 'FAIL'
                assert summary['schema_cleanup'] == 'REPORTED_DROPPED_ORACLE_NOT_VERIFIED'
            """)

        def test_writer_identity_mismatch_leaves_failure_record(self):
            raw = self.root / "raw"
            raw.mkdir(mode=0o700)
            os.chown(raw, 1001, 1001)
            denied = self.child(
                "(root/'raw/unauthorized').write_text('synthetic')", uid=1002
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse((raw / "unauthorized").exists())
            self.expect("""
                from t16_evidence import write_json
                record={'writer_uid':1002, 'reader_uid':1001, 'status':'INCOMPLETE', 'exit_code':1}
                write_json(root/'identity-failure.json', record)
                assert json.loads((root/'identity-failure.json').read_text()) == record
                print(json.dumps(record))
            """)

        def test_missing_oracle_fail_closed(self):
            self.expect("""
                from test_t16_admission import synthetic_pipeline, inspect_synthetic_pipeline
                run,key=synthetic_pipeline(root)
                (run.raw/'verification/business-oracle.json').unlink()
                run.finish()
                summary=inspect_synthetic_pipeline(run,key)
                assert not summary['evidence_complete'] and not summary['cleanup_complete']
                assert summary['result']=='FAIL'
            """)

        def test_wrong_sha_refuses_pass(self):
            self.expect("""
                from test_t16_admission import synthetic_pipeline, inspect_synthetic_pipeline
                run,key=synthetic_pipeline(root)
                (run.raw/'verification/business-oracle.json.sha256').write_text('0'*64)
                run.finish()
                assert not inspect_synthetic_pipeline(run,key)['evidence_complete']
            """)

        def test_links_fifo_and_escape_refused(self):
            self.expect("""
                from t16_evidence import bundle
                raw=root/'raw'
                raw.mkdir(mode=0o700)
                (root/'outside').write_text('synthetic')
                (raw/'escape').symlink_to('../outside')
                try:
                    bundle(raw,root/'bad.tgz')
                    raise AssertionError('followed escape')
                except ValueError:
                    pass
                (raw/'escape').unlink()
                os.mkfifo(raw/'fifo')
                try:
                    bundle(raw,root/'bad.tgz')
                    raise AssertionError('accepted FIFO')
                except ValueError:
                    pass
            """)

        def test_archive_and_cleanup_fault_injections_as_nonroot(self):
            self.expect("""
                import unittest
                from test_t16_admission import EvidencePipelineTests
                names=['test_mid_archive_failure_never_publishes_a_complete_archive',
                       'test_cleanup_failure_is_recorded_even_with_complete_evidence']
                suite=unittest.TestSuite(EvidencePipelineTests(name) for name in names)
                assert unittest.TextTestRunner().run(suite).wasSuccessful()
            """)

        def test_public_helper_with_docker_copy_root_ownership_is_readable(self):
            from t16_admission import stage_public_helpers

            target = self.root / "ci_harness"
            stage_public_helpers(
                Path(__file__).parent, target
            )  # Root owner, as Docker COPY.
            self.expect("""
                import subprocess
                helper=root/'ci_harness/t16_clock.py'
                assert helper.stat().st_uid==0
                process=subprocess.run([sys.executable,str(helper),'--worker'],input='',
                                       capture_output=True,text=True,timeout=3)
                assert process.returncode==0,process.stderr
            """)

        def test_full_public_tree_is_readable_across_uid_without_exposing_private_evidence(
            self,
        ):
            from t16_admission import stage_public_source

            archive = PublicSourceTests().source_archive(self.root)
            stage_public_source(archive, self.root / "build")
            raw = self.root / "root-private"
            raw.mkdir(mode=0o700)
            (raw / "oracle.json").write_text("synthetic private evidence")
            self.expect("""
                import subprocess
                entry=root/'build/scripts/verify_t16_a3.py'
                assert entry.stat().st_uid==0
                assert (root/'build/backend/src/public.py').read_text()=='VALUE = 42\\n'
                result=subprocess.run([sys.executable,str(entry)],capture_output=True,text=True)
                assert result.returncode==0 and result.stdout=='verified entry\\n'
                try:
                    (root/'root-private/oracle.json').read_bytes()
                    raise AssertionError('private evidence became readable')
                except PermissionError:
                    pass
            """)

        def test_cache_runtime_cannot_be_read_or_adopted_by_other_uid(self):
            self.expect("""
                from t16_cache import create_runtime, validate_runtime
                create_runtime(root/'guest-runtime','synthetic-cache-owner')
                validate_runtime(root/'guest-runtime','synthetic-cache-owner',1001,1001)
            """)
            os.chmod(self.root, 0o755)
            other = self.child(
                """
                from t16_cache import validate_runtime
                try:
                    validate_runtime(root/'guest-runtime','synthetic-cache-owner',1002,1002)
                    raise AssertionError('adopted another identity runtime')
                except (ValueError,PermissionError):
                    pass
                try:
                    (root/'guest-runtime/ml-cache/.owner.json').read_bytes()
                    raise AssertionError('read another identity private cache')
                except PermissionError:
                    pass
            """,
                uid=1002,
            )
            self.assertEqual(other.returncode, 0, other.stderr)

        def test_regular_file_to_fifo_race_is_bounded(self):
            child = self.child(
                """
                from unittest.mock import patch
                from t16_evidence import bundle
                raw=root/'raw';raw.mkdir(mode=0o700)
                path=raw/'raced';path.write_bytes(b'synthetic')
                real_open=os.open
                def swapped(name,flags,*args,**kwargs):
                    if name=='raced':
                        path.unlink();os.mkfifo(path,0o600)
                    return real_open(name,flags,*args,**kwargs)
                with patch('t16_evidence.os.open',side_effect=swapped):
                    try:
                        bundle(raw,root/'bad.tgz')
                        raise AssertionError('accepted replaced FIFO')
                    except (ValueError,OSError):
                        pass
                assert not (root/'bad.tgz').exists()
            """,
                timeout=3,
            )
            self.assertEqual(child.returncode, 0, child.stderr)

    return unittest.defaultTestLoader.loadTestsFromTestCase(LinuxOwnershipTests)


def bge_image_suite(image, context):
    """Opt-in real full-image regression. No mounts, DB, Provider or network access."""
    import textwrap
    from uuid import uuid4

    from t16_admission import safe_environment

    environment = safe_environment(os.environ)
    probe = textwrap.dedent("""
        import hashlib, importlib, json, os, pathlib, runpy, stat
        root=pathlib.Path('/work')
        paths=['scripts/verify_t16_a3.py', 'backend/tests/t16_a3_oracle.py',
               'backend/tests/t16_a3_scenario.py', 'backend/tests/t16_a3_retrieval_checks.py',
               'backend/.venv/pyvenv.cfg', 'evals/data/embedding_manifest.json']
        for name in paths:
            assert (root/name).read_bytes(), name
        namespace=runpy.run_path(str(root/'scripts/verify_t16_a3.py'),run_name='access_probe')
        with namespace['offline_boundary']() as boundary:
            for module in ['sqlalchemy','psycopg','pgvector','langgraph.checkpoint.postgres',
                           't16_a3_oracle','t16_a3_scenario','t16_a3_retrieval_checks']:
                importlib.import_module(module)
            manifest=json.loads((root/'evals/data/embedding_manifest.json').read_text())
            model=root/'.models'/manifest['revision']
            assert len(manifest['files'])==6
            for name, ref in manifest['files'].items():
                data=(model/name).read_bytes()
                assert len(data)==ref['size_bytes']
                assert hashlib.sha256(data).hexdigest()==ref['sha256']
            from agentmall.retrieval.embedding import LocalEncoder
            encoder=LocalEncoder()
            vector=encoder.encode(['键盘'],query=True)[0]
            assert len(vector)==512
            assert str(next(encoder.model.parameters()).device)=='cpu'
            assert boundary.blocked_external_attempts==0
        print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(), 'model_files':6,
                          'dimension':512,'device':'cpu','external_attempts':0}))
    """)

    class BgeImageTests(unittest.TestCase):
        def container(self, user, code, *, readonly=True):
            name = "am-t16-image-test-" + uuid4().hex
            argv = [
                "docker",
                "--context",
                context,
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--user",
                user,
                "--memory",
                "2g",
                "--cpus",
                "2",
                "--tmpfs",
                "/tmp:rw,mode=1777,size=128m",
                "-e",
                "HOME=/tmp",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
            ]
            if readonly:
                argv.append("--read-only")
            docker = ["docker", "--context", context]
            try:
                return subprocess.run(
                    argv + [image, "python", "-c", code],
                    check=False,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            finally:
                query = docker + ["ps", "-aq", "--filter", f"name=^/{name}$"]
                observed = subprocess.run(
                    query, check=False, env=environment, capture_output=True, timeout=15
                )
                if observed.returncode:
                    raise RuntimeError("IMAGE_TEST_CLEANUP_UNKNOWN")
                if observed.stdout.strip():
                    subprocess.run(
                        docker + ["rm", "-f", name],
                        check=False,
                        env=environment,
                        capture_output=True,
                        timeout=15,
                    )
                    observed = subprocess.run(
                        query,
                        check=False,
                        env=environment,
                        capture_output=True,
                        timeout=15,
                    )
                    if observed.returncode or observed.stdout.strip():
                        raise RuntimeError("IMAGE_TEST_CLEANUP_UNVERIFIED")

        def test_full_verifier_help_as_nonroot(self):
            result = self.container(
                "1001:1001",
                """
import subprocess,sys
raise SystemExit(subprocess.run([sys.executable,'scripts/verify_t16_a3.py','--help']).returncode)
""",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--state-dir", result.stdout)

        def test_root_and_nonroot_read_full_verifier_dependencies_and_real_model(self):
            for uid in (0, 1001):
                with self.subTest(uid=uid):
                    result = self.container(f"{uid}:{uid}", probe)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    record = json.loads(result.stdout)
                    self.assertEqual(
                        record,
                        {
                            "uid": uid,
                            "gid": uid,
                            "model_files": 6,
                            "dimension": 512,
                            "device": "cpu",
                            "external_attempts": 0,
                        },
                    )

        def test_unreadable_full_script_dependency_or_model_is_rejected(self):
            for path in [
                "/work/scripts",
                "/work/backend/.venv/lib/python3.12/site-packages/sqlalchemy",
                "/work/.models",
            ]:
                with self.subTest(path=path):
                    code = (
                        "import os; "
                        f"os.chmod({path!r},0o700); "
                        "os.setgroups([]); os.setgid(1001); os.setuid(1001);\n" + probe
                    )
                    result = self.container("0:0", code, readonly=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(
                        "PermissionError" in result.stderr
                        or "ModuleNotFoundError" in result.stderr,
                        result.stderr,
                    )

    return unittest.defaultTestLoader.loadTestsFromTestCase(BgeImageTests)


def cache_image_suite(image, context):
    """Real nonroot full-image/cache bind checks; every container has network=none."""
    import shutil
    from uuid import uuid4

    from t16_admission import safe_environment

    environment = safe_environment(os.environ)
    docker = ["docker", "--context", context]

    class CacheImageTests(unittest.TestCase):
        def command(self, args):
            return subprocess.run(
                docker + args,
                check=False,
                env=environment,
                capture_output=True,
                text=True,
                timeout=150,
            )

        def setUp(self):
            self.volume = "am-t16-cache-test-" + uuid4().hex
            self.names = []
            self.directory = tempfile.TemporaryDirectory()
            self.addCleanup(self.directory.cleanup)
            public = Path(self.directory.name)
            public.chmod(0o755)
            shutil.copyfile(
                Path(__file__).with_name("t16_cache.py"), public / "t16_cache.py"
            )
            (public / "t16_cache.py").chmod(0o644)
            self.helper = public
            self.assertEqual(
                self.command(["volume", "create", self.volume]).returncode, 0
            )
            self.addCleanup(self.remove_owned)
            inspected = self.command(["volume", "inspect", self.volume])
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.source = json.loads(inspected.stdout)[0]["Mountpoint"]
            result = self.root_command("""
import os,sys
from pathlib import Path
sys.path.insert(0,'/harness')
from t16_cache import create_runtime
os.chown('/owned',1001,1001)
os.setgroups([]);os.setgid(1001);os.setuid(1001);os.umask(0o077)
create_runtime(Path('/owned/guest-runtime'),'synthetic-cache-owner')
""")
            self.assertEqual(result.returncode, 0, result.stderr)

        def root_command(self, code):
            return self.command(
                [
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0:0",
                    "--mount",
                    f"type=volume,source={self.volume},target=/owned",
                    "-v",
                    f"{self.helper}:/harness:ro",
                    image,
                    "python",
                    "-c",
                    code,
                ]
            )

        def remove_owned(self):
            for name in self.names:
                result = self.command(["ps", "-aq", "--filter", f"name=^/{name}$"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(
                    result.stdout.strip(), "cache test container not removed"
                )
            removed = self.command(["volume", "rm", self.volume])
            self.assertEqual(removed.returncode, 0, removed.stderr)
            observed = self.command(
                ["volume", "ls", "-q", "--filter", f"name=^{self.volume}$"]
            )
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertFalse(observed.stdout.strip())

        def preflight(
            self, *, target="ml-cache", cache_readonly=False, mount_cache=True
        ):
            name = "am-t16-cache-probe-" + uuid4().hex
            self.names.append(name)
            args = [
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--read-only",
                "--user",
                "1001:1001",
                "--memory",
                "2g",
                "--cpus",
                "2",
                "-e",
                "HOME=/runtime/home",
                "-e",
                "TMPDIR=/runtime/tmp",
                "-e",
                "HF_HOME=/runtime/cache/huggingface",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "--mount",
                f"type=bind,source={self.source}/guest-runtime,target=/runtime",
                "-v",
                f"{self.helper}:/harness:ro",
            ]
            if mount_cache:
                args += [
                    "--mount",
                    f"type=bind,source={self.source}/guest-runtime/{target},"
                    "target=/work/.ml-cache" + (",readonly" if cache_readonly else ""),
                ]
            return self.command(
                args
                + [
                    image,
                    "python",
                    "/harness/t16_cache.py",
                    "--uid",
                    "1001",
                    "--gid",
                    "1001",
                    "--owner",
                    "synthetic-cache-owner",
                ]
            )

        def rejected(self, result):
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["status"], "NONROOT_CACHE_PREFLIGHT_FAILED"
            )

        def test_real_jieba_and_cpu_encoder_succeed_without_network(self):
            result = self.preflight()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record["dimension"], 512)
            self.assertEqual(record["model_files"], 6)
            self.assertEqual(record["uid"], 1001)
            self.assertEqual(record["gid"], 1001)
            self.assertEqual(record["network_attempts"], 0)
            self.assertEqual(record["forbidden_source_writes"], 0)
            self.assertTrue(record["persisted_cache_reload"])
            # Another process must be able to read the same cache without rebuilding.
            again = self.preflight()
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertEqual(
                json.loads(again.stdout)["cache_sha256"], record["cache_sha256"]
            )

        def test_missing_mount_is_rejected(self):
            self.rejected(self.preflight(mount_cache=False))

        def test_missing_cache_directory_is_rejected(self):
            result = self.root_command(
                "import shutil;shutil.rmtree('/owned/guest-runtime/ml-cache')"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.rejected(self.preflight(mount_cache=False))

        def test_readonly_cache_mount_is_rejected(self):
            self.rejected(self.preflight(cache_readonly=True))

        def test_wrong_uid_gid_is_rejected(self):
            result = self.root_command(
                "import os;os.chown('/owned/guest-runtime/ml-cache',1002,1002)"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.rejected(self.preflight())

        def test_nonwritable_mode_is_rejected(self):
            result = self.root_command(
                "import os;os.chmod('/owned/guest-runtime/ml-cache',0o500)"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.rejected(self.preflight())

        def test_wrong_bind_source_with_same_marker_is_rejected(self):
            result = self.root_command("""
import os,shutil
os.setgroups([]);os.setgid(1001);os.setuid(1001);os.umask(0o077)
shutil.copytree('/owned/guest-runtime/ml-cache','/owned/guest-runtime/wrong-cache')
""")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.rejected(self.preflight(target="wrong-cache"))

    return unittest.defaultTestLoader.loadTestsFromTestCase(CacheImageTests)


if __name__ == "__main__":
    os.umask(0o077)
    if (
        len(sys.argv) == 5
        and sys.argv[1] == "--bge-image"
        and sys.argv[3] == "--docker-context"
    ):
        result = unittest.TextTestRunner(verbosity=2).run(
            bge_image_suite(sys.argv[2], sys.argv[4])
        )
        raise SystemExit(not result.wasSuccessful())
    if (
        len(sys.argv) == 5
        and sys.argv[1] == "--cache-image"
        and sys.argv[3] == "--docker-context"
    ):
        result = unittest.TextTestRunner(verbosity=2).run(
            cache_image_suite(sys.argv[2], sys.argv[4])
        )
        raise SystemExit(not result.wasSuccessful())
    if sys.argv[1:] == ["--linux-ownership"]:
        result = unittest.TextTestRunner(verbosity=2).run(linux_ownership_suite())
        raise SystemExit(not result.wasSuccessful())
    unittest.main()
