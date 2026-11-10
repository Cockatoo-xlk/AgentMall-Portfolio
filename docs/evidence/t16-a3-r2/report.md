# T16-A3-R2 — Independent GitHub CI admission

Status: `T16_A3_R2_CI_PLAN_READY_FOR_OWNER_APPROVAL`.

This is an upload audit and local CI-only candidate, not final T16-A3 acceptance. GitHub execution, stable-runner clock admission, final product regression and fresh BGE/Oracle execution are **NOT_RUN**. Historical `BLOCKED_ENVIRONMENT_CLOCK` and all original A3 failures remain unchanged.

## Scope and identities

The owner explicitly permitted one independent **local** CI candidate commit after the original read-only request. Branch: `codex/t16-a3-ci-verify`, based on frozen `77b215878edbce50ce107c6e77e31de4d2044ff9`. No product source, migration, dependency lock, existing assertion, skip or retry setting is changed. Product fingerprint remains `1e54c1f0d0b76ff0a975fbcc9938008336febbf1a1c8c5564253a23f4a901e27`.

The final commit/inventory handoff is generated outside Git after commit to avoid self-referential hashes. It includes every tracked path, size, SHA-256, exact commit chain and deterministic content-tree digest. It is required input to any next authorization.

## Publication audit

The frozen product has 12 reachable commits, 10 after the public main, 643 unique reachable blobs and 528 current files. Every blob's bytes were read, hashed and scanned, including old versions; the largest was 474,898 bytes. No tracked weight/model archive or private Live directory was found. Author/committer identities use only the owner-approved public name and noreply address. All new candidate files are separately scanned and enumerated in the final handoff.

Two token-shaped strings in the redaction test are malformed synthetic examples, classified `SYNTHETIC_TEST_DATA`. Public CI passwords/secrets and demo identities are explicitly synthetic and used only with disposable test databases. No actual provider key, authenticated JWT, personal workstation path, raw Live ledger, Live authorization or private Checkpoint serialization was found in the reviewed Git blobs. This is a scoped audit, not a mathematical guarantee that every possible secret pattern is detectable.

Twenty-one reachable PNG versions have no private text/EXIF metadata chunks. Visual contact-sheet review showed fixture/synthetic commerce screens and synthetic resource IDs. No browser address bar, token or personal workstation information was observed. Raw contact sheets and scanner working files stay ignored/private. MIT/COPYRIGHT/THIRD_PARTY_NOTICES are unchanged; this candidate adds original CI code/documentation, not vendored packages, model weights, binary tools or published Docker images.

Categories:

| Category | Handling |
| --- | --- |
| SYNTHETIC_TEST_DATA | Explicit test fixtures, malformed credential examples, demo users, test requests and disposable DB settings |
| REVIEWED_PUBLIC_EVIDENCE | Existing sanitized reports/screenshots, blob metadata and this CI plan/status |
| PRIVATE_LOCAL_EVIDENCE | Ignored historical `.playground`/diagnostic originals, new local raw audit and helper logs; never staged |
| SENSITIVE_OR_UNKNOWN | None unresolved in the reviewed upload set; unknown runtime outputs must be encrypted and cannot be uploaded raw |

[History audit](git-history-audit.json), [full baseline blob inventory](reachable-blobs.json), [reachable commit metadata](history-commits.json), [historical preservation](historical-integrity.json).

## Remote read-only result

Authenticated GitHub CLI/API succeeded with normal TLS. The connected GitHub tool transport failed, so no result was inferred from it. Public repository/default main remains `17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`; the proposed branch was HTTP404/absent. PR #1 remains open Draft at `bd0f58368bd40e2b479599fa270b30e43703d2b8`. No remote write or workflow trigger occurred. These facts must be checked again immediately before a future authorized push.

## CI design and verification

The existing default-branch-registered `ci.yml` is the future manual dispatch target at the approved branch. It calls the candidate's reusable two-job workflow. Only the new branch is excluded from automatic push CI; other branches retain their existing checks. Candidate reruns (`run_attempt > 1`) are refused. No current permission to push or dispatch exists.

Stage A: Ubuntu 24.04 x64 native frozen full core commands. Stage B: new Ubuntu x64 runner, bounded digest-pinned Debian/Python BGE execution container (frozen verifier needs numeric cgroup memory limit). Fresh PG17/pgvector0.8.7 containers/volumes/passwords and new schemas per stage. Separate checkouts bind the exact frozen product and CI candidate. Each stage requires 60s clock admission, at least 900s subsequent observation and both samplers throughout tests, with unchanged thresholds and no retry.

The final local helper suite: **14 tests passed, exit 0**, including clock threshold boundaries, failed sampler, wrong execution identity, environment credential exclusion, incomplete proof, command deadline/export, actual child termination after injected pause timeout, partial encrypted export, unsafe archive entries, and real OpenSSL synthetic encryption/decryption. No Docker engine or provider was used by this suite. New helpers pass Ruff 0.17.3 and format with the project's backend rules; both workflows pass checksum-verified actionlint1.7.12; Git diff check passes. [Exact commands, exit codes and raw log SHA](verification.json).

One initial local lint command accidentally applied the backend's 100-column policy to all existing CI scripts and reported the unchanged frozen bootstrap's 104-column DSN line. That failure is retained; it is not presented as a passing full-project lint run. Correctly scoped new-helper checks pass. The existing complete CI Ruff invocation and frozen bootstrap remain unchanged for remote validation.

One independent review found three important CI-only defects. Each was reproduced RED, fixed, and covered in the final 14-test GREEN suite: pause timeout skipping termination; export preparation dropping remaining evidence; host sampler failure not failing closed. A mock initially intercepted OpenSSL too broadly; this harness failure is retained and corrected to mock only unavailable Docker transport. No second review loop. [Review/fixes](review.json).

## Pending execution, resources and disclosure

No new full pytest/Vitest/Playwright/BGE count is recorded here. The frozen final source still requires independent execution; old 823/85/96 receipts are not substituted. Old macOS VM clock failures and Docker/network/OOM evidence remain historical failures. No source fingerprint or Live policy is silently rebound.

The proposed standard public runner is 4 vCPU/16 GiB/14 GiB disk, up to two sequential 45-minute jobs. Dependency/image installation size and actual available capacity are unverified; locked torch may bring sizeable Linux wheels. Fail rather than remove unknown software, swap locks, use a paid larger runner or retry. Standard public compute is documented as free; account artifact/storage allowance and actual billing remain UNKNOWN. Proposed encrypted originals are bounded at 100 MB/phase, retention one day, no cache.

The owner must supply an approved **public** receiving certificate and SHA before dispatch; its private key never enters Actions. Public artifacts are only allowlisted summaries plus encrypted originals. On collection failure, partial evidence is still encrypted and marked incomplete/failed; no false PASS. A failed BGE Oracle retains owned schemas until export. Ephemeral runner teardown eventually destroys volumes, so encrypted dump/restore material is required; no promise of a persistent failed DB is made. Core fixture cleanup retains its original behavior.

Paid model requests **0**; real Key reads **0**; Live approvals **0**; push/dispatch/merge/deployment **0**. Live multi-turn verification remains **NOT_RUN**.

[Detailed next authorization, exact execution sequence, resource limits and evidence plan](remote-execution-plan.md). Stop here for owner approval of the final CI candidate SHA, one new-branch push, one dispatch and evidence/storage parameters. No main/PR update, Live operation or rerun is included.
