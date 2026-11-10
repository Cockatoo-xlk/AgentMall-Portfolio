# T16-A3 independent CI admission plan

Goal: prepare one manually dispatched, two-stage offline verification of frozen product commit `77b215878edbce50ce107c6e77e31de4d2044ff9`. This document authorizes no remote operation.

Architecture: the default-branch-registered `ci.yml` is dispatched at the approved candidate ref and calls the candidate's reusable workflow. A CI-only candidate checks out the frozen product separately. Stage A runs its existing full core commands on Ubuntu 24.04 x64; Stage B builds a bounded Python container for the frozen real-BGE verifier (its cgroup memory oracle requires a container). Both use fresh PostgreSQL containers, clocks and evidence directories. Public artifacts contain allowlisted status and encrypted originals only.

Constraints: no product edits, keys, Live approval, paid model requests, retries, extra skips, existing schemas or remote writes. Admission 60s; subsequent observation at least 900s and throughout tests. Wall rollback greater than 1ms, nonadvancing monotonic time, residual greater than 100ms, or host/guest offset range at least 100ms blocks execution.

Review focus: clock faults during child processes; encrypted evidence on failure; immutable product identity; public artifact leakage; fresh ownership and failed-schema retention on an ephemeral runner.

## Task 1: CI-only harness and proposal

- [x] Add failing standard-library tests for clock boundaries, unknown/missing evidence, identity guards, environment sanitization, and encrypted export safety.
- [x] Implement `scripts/ci/t16_clock.py`, `t16_evidence.py`, `t16_admission.py`, and the bounded BGE image.
- [x] Add manual-only workflow, exclude the proposed branch from the old push trigger, retain existing CI assertions.
- [x] Run helper tests, Ruff, YAML/actionlint if available, encryption round-trip, source/hash guards and full history audit. Do not run the formal workload on the rejected local VM.
- [x] Review once; fix important findings and rerun affected checks.
- [x] Prepare local commit and external exact commit/file handoff; final receipt is authoritative for commit success and clean status.

## Evidence boundaries

Local synthetic helper tests are not GitHub execution or product regression evidence. Original A3 failures remain unchanged. The new candidate's workflow and containers are unexecuted until a separately authorized push and one dispatch. A public receiving certificate and its SHA are required before dispatch; its private key stays with the owner. Failure schemas are not explicitly dropped; the ephemeral runner eventually destroys its volumes, so an encrypted dump is required and this lifecycle must be disclosed.
