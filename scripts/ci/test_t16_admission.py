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
                self.assertEqual(gate.sample(1_000_000_000 + wall, 1_000_000_000 + mono), expected)

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
            run = Execution(SimpleNamespace(app=Path(tmp), output=Path(tmp) / "run", phase="core"))
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
                    run.command([sys.executable, "-c", "import time; time.sleep(20)"], monitor=True)
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
                    run.command([sys.executable, "-c", "import time; time.sleep(20)"], monitor=True)
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
                SimpleNamespace(app=root, output=root / "run", phase="bge", ci_commit="a" * 40)
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
                patch.object(run, "command", side_effect=RuntimeError("SYNTHETIC_DUMP_FAILURE")),
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
            args = SimpleNamespace(app=Path(tmp), output=Path(tmp) / "owned", phase="core")
            run = Execution(args)
            run.deadline = 0
            with patch("t16_admission.subprocess.run"):
                run.command([sys.executable, "-c", "print('synthetic export')"], export=True)
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

        self.assertEqual(public_summary("bge", {"exit_code": 0}, {})["result"], "BLOCKED")

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


if __name__ == "__main__":
    os.umask(0o077)
    unittest.main()
