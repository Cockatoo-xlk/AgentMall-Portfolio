# T16-A3 independent CI: execution proposal, not authorization

Status: local CI candidate only. No push, dispatch, PR change, model key access or provider request has occurred in this stage.

## Exact identities

- Repository: `Cockatoo-xlk/AgentMall-Portfolio` (Public).
- New branch: `codex/t16-a3-ci-verify` (remote absent at admission inspection).
- Product: `77b215878edbce50ce107c6e77e31de4d2044ff9`.
- Product fingerprint: `1e54c1f0d0b76ff0a975fbcc9938008336febbf1a1c8c5564253a23f4a901e27`.
- CI candidate SHA and full inventory: the final local handoff receipt outside the commit. A commit cannot include its own SHA/content-tree hash. Approve that exact 40-character SHA, not merely the product SHA.
- Last read-only main: `17f72b8ccd6a86e083fd3206ea839dd28dc22bcf`. PR #1 remains open/draft at `bd0f58368bd40e2b479599fa270b30e43703d2b8`.

## Required next authorization

The owner must separately approve ONE ordinary push of the exact CI candidate to this new branch and ONE manual dispatch of `ci.yml` at that same SHA/ref. No merge, existing PR change, main update, rerun, larger runner or repair push is included. Main/branch identity, clean status, certificate hash, artifact/storage budget and all candidate hashes must be checked again before that authorization is used. An absent or changed identity means stop.

The receiving material is a PUBLIC RSA X.509 PEM certificate (valid at least two hours) plus SHA-256 of its exact bytes. The owner retains the private key locally, outside Git and Actions. Never provide a private key as a workflow input. It is for evidence encryption, not a TLS trust change or Live model authorization. The current candidate does not contain a receiving certificate. The synthetic encryption test generates and destroys only its own temporary test pair.

GitHub requires a manually dispatched workflow to exist on the default branch. The existing `ci.yml` meets that condition; dispatch its branch version, which calls the new reusable workflow. The new reusable file alone cannot be the first manual dispatch target. The old push workflow excludes only this admission branch; no assertion or test is removed.

## One formal Run, two sequential jobs

Both jobs use fresh GitHub-hosted `ubuntu-24.04` x64 standard runners. Each checks out product `77b2158` under `app/`, and the approved CI commit under `harness/`. Only CI configuration/helpers/documentation differ from the product. Source fingerprint and clean product checkout are checked before dependency setup or DB writes. All action revisions are full-SHA pinned; workflow token permissions are `contents: read`; credentials are not persisted. No repository/environment secrets or DeepSeek key are mapped.

### A — frozen CI_OFFLINE_CORE

Python 3.12.10, uv 0.9.18, Node 24.21.0; locked dependencies and npm lock; Chromium with native Linux dependencies. Runs unchanged product `scripts/ci/run.py`: fresh bootstrap/migrations/repeat seed/official Checkpointer, Ruff, format, full `pytest --ci-offline-core --strict-markers -ra`, typecheck, ESLint, Vitest, build, and all Playwright with existing 0 retries. Actual receipts/log SHA and counts are parsed after execution; fewer than 823 pytest passes, anything other than the original 14 skips, or missing 85 Vitest/96 Playwright passes refuses acceptance. These are acceptance thresholds, not recorded results.

The unchanged core skip contract is 13 `real_bge` cases plus one missing private historical Live-original comparison. Their actual node IDs/reasons are preserved in the encrypted pytest log. Stage B is mandatory real-BGE acceptance, not a reclassification of those skipped core cases as passes. It runs only if A is successful.

### B — real BGE and complete business Oracle

Builds an amd64, digest-pinned Python 3.12.10 Debian Bookworm container on the Ubuntu runner. This distinction is explicit: B's application process is Debian-container/x86_64, A is Ubuntu-native/x86_64. The existing verifier reads numeric cgroup `memory.max`; running it unbounded on the host could encounter `max`. The container is capped at 8 GiB/3 CPUs; PG at 1 GiB/1 CPU. No model or image is published.

Installs the unchanged embedding lock. Downloads only the manifest's six public BGE files from the pinned official Hugging Face revision; verifies exact sizes/SHA. No HF token or paid endpoint is used. Runs the frozen `scripts/verify_t16_a3.py` with new private state/output paths under a fresh container; 14 real retrieval checks, CPU 512 dimensions, genuine pgvector, exact three inputs, controlled MockTransport and independent read-only PG/Checkpoint Oracle. A private `strace` records `fsync` calls, alongside the verifier's original JSON, sidecars and validation before cleanup.

The three inputs are unchanged:

1. 推荐300元以内的静音键盘，不要购买。
2. 我改主意了，要支持无线连接的，预算提高到400元。
3. 就买刚才推荐的第二款，一件，送演示宿舍。

Require first-turn candidates ≥1, second-turn ≥2; turn 3 binds the second actual current candidate. Before the independent Mock test operator confirms: orders 0. Afterwards: exactly one PENDING_PAYMENT order, correct Proposal/Confirmation/inventory/idempotency, payments 0, continuous Run events, final Checkpoint and no pending writes. Frozen Oracle validates these; raw values/IDs stay encrypted. No result is prefilled.

## Time admission and isolation

After setup, independently sample Linux runner host and the owned execution container at approximately 100Hz. Record bracketed host/guest pings, wall/monotonic deltas, both sampler heartbeats and raw JSONL. Require 60 seconds admission and at least 900 seconds observation after admission, covering all test execution. Early test completion extends observation, not test retries. Sampling is discrete; it does not prove the absence of every unsampled clock step.

Unchanged fatal thresholds: wall delta < −1,000,000ns; monotonic delta ≤0; |wall delta − monotonic delta| >100,000,000ns; low-round-trip host/guest offset range ≥100,000,000ns. Missing/stalled/failed samplers also fail closed. Faults fence owned DB/workload and terminate owned descendants even if Docker pause times out. No JWT/security change, system clock change or threshold relaxation occurs.

Each job creates a new random ownership namespace, PG container, volume and password. The fixed test protocol requires local `agentmall/agentmall_test` at 127.0.0.1:55433; this is a new cluster identity each job, not reuse of a historical DB. Test and checkpoint schemas are freshly generated by the frozen initializer. No Mac Docker context or historical environment is accessed.

## Resources, time and potential fees

Standard public Ubuntu x64 runners are documented as 4 vCPU/16 GiB RAM/14 GiB SSD. Each job has a 45-minute workflow cap; harness stops test/setup at 40 minutes, leaving bounded collection/upload time. Maximum two jobs/90 runner-minutes; observation alone uses at least 32 minutes across two sequential jobs. Dependencies/build can make the actual run longer. No larger/paid runner, cache, automatic retry or repeat dispatch is proposed.

Before setup require ≥12 GiB total RAM and ≥8 GiB free disk. Locked Linux torch may include sizeable CUDA wheels even for CPU use. Actual installation/image size, memory peak, OOM state and disk availability remain UNKNOWN until the runner executes. If the standard runner cannot build/load it, classify infrastructure failure and stop; do not unlock/swap dependencies, delete unknown tools or upgrade runner class automatically.

Public standard-runner compute has no metered minute charge under current GitHub documentation. Artifact storage has separate account allowances; available allowance/actual billing is UNKNOWN. Each phase's raw bundle is limited to 100 MB before compression; upload only ciphertext plus bounded status for one day; no cache. The owner must accept/check storage allowance before dispatch. Paid model requests are prohibited, not budgeted.

## Evidence and failure policy

All command stdout/stderr, application receipts, raw clock samples, synthetic DB credentials, Mock state, Oracle and failure dump remain in private runner-temp directories (0700/0600). Console prints only fixed status, safe counts and hashes. Public Artifact contains AES-256-GCM CMS encrypted originals using the owner certificate, and allowlisted summary; never raw logs, unencrypted checkpoint state or credentials. The raw bundle has a path/size/SHA inventory; original archive and ciphertext hashes are separate.

Collection operations are independent: a missing guest or failed dump still permits encryption of other originals and an explicit incomplete-evidence failure. Missing/unknown Oracle, nonzero command, clock anomaly or collection failure cannot become PASS. No automatic rerun; B is NOT_RUN if A fails. Preserve failed Run ID/Attempt1 and download/decrypt artifacts locally within retention, then verify archive hashes and original sidecars before reviewing raw content.

On B Oracle failure the frozen verifier does not DROP its schemas. The harness does not remove owned resources on incomplete evidence. **GitHub's ephemeral VM eventually destroys resident volumes regardless:** a successful encrypted DB dump preserves export/restore material, not a long-lived database. Dump/export failure is BLOCKED with explicitly incomplete recovery evidence, never a claim that the schema remains accessible after runner teardown. Frozen core tests retain their existing per-test cleanup behavior; this is not changed to preserve every core failure DB.

## Proposed operator sequence — NOT executed here

1. Obtain explicit approval binding candidate SHA, branch, one push, one dispatch, evidence certificate SHA and storage allowance. Recheck identities and no existing run.
2. Ordinary push only the approved candidate to the absent branch; verify remote head. Push alone triggers no admission.
3. Invoke the existing `ci.yml` with `--ref codex/t16-a3-ci-verify`, `ci_commit`, public PEM and SHA through a structured JSON input file. No private key, token echo, shell interpolation of PEM, workflow_dispatch of the new file, or extra dispatch.
4. Observe that Run/Attempt1 read-only. Preserve failures; do not repair/re-push/rerun. Collect actual test counts, skip reasons, runtime versions, source identities, clocks, model checks, full Oracle and encrypted-evidence hashes.
5. Stop. A successful independent offline result would permit a new T16-B0 proposal, with a new environment/session/source-bound policy and independently approved paid scope. It would not authorize Live, merge or publication.

Sources: [GitHub workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow), [hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [artifact access](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts?tool=webui), [OpenSSL CMS](https://docs.openssl.org/3.0/man1/openssl-cms/). Checked during this admission preparation; recheck before execution.
