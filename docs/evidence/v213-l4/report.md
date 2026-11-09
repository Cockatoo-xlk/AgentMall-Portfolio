# V2.13-L4 — Read-only assessment → authorized return proposal

Evidence class: **OFFLINE SDK MockTransport + Fixture Embedding + real isolated PostgreSQL**.
Real DeepSeek retest: **NOT_RUN**. Hosted Embedding: **NOT_RUN**.

## Source and scope

- Parent: `a055117fac4f5b27d8c04bc333ef317941509035`.
- Branch: `codex/v213-l4-return-handoff`.
- The implementation commit containing this report is the L4 candidate; identify it with `git log -1 --format=%H -- docs/evidence/v213-l4/report.md`.
- No domain transaction, payment, refund, inventory, model budget, frozen dataset or Oracle changes.
- Existing serialized TaskSpec and Checkpoint shapes remain readable. A newly dispatched Multi return task now requires completed assessment proof; an older unfinished Multi write without that proof fails closed. Single retains its legal tool union and original authorization checks.

## Confirmed L3 failure

The retained L3 diagnostic shows a readonly `assess_return` calling `get_order`, `check_eligibility` and `retrieve_policies` successfully, then attempting the known `prepare_return` tool. Role-level discovery exposed that tool even though the envelope denied it. The L2 Guard correctly rejected it with `READ_ONLY_TOOL_VIOLATION`; the next assessment under a new ID was rejected by failed-goal deduplication.

L3 remains **PARTIAL / Oracle failed**, with five settled model requests, three successful readonly tools, one delegation, zero Agent confirmations and zero new business writes. This is a task/exposure mismatch and missing legal phase transition, not evidence of an unauthorized database transaction. Legacy Oracle diagnostic counts must not be presented as actual unauthorized writes. Original L3 files are unchanged.

## Contract and implementation

1. `task_tool_names()` intersects role authority with the current envelope. Readonly AfterSales exposes exactly three reads. A return write exposes those reads plus `prepare_return`; support and checkout are hidden. Other roles and Bundle tools use the same rule. The independent Guard still rejects forged hidden tools.
2. Supervisor instructions distinguish readonly assessment from the later, exclusive write batch. Both planning preflight and runtime validation require explicit `read_only=false` for write goals and true for readonly goals. No permission is upgraded automatically.
3. `record_assessment()` builds readiness only from actual successful, same-order tool receipts: explicit order read, deterministic eligibility, public citations matching the policy version, original SKUs and order version. Model prose cannot produce readiness.
4. `assessment_for()` requires the completed assessment dependency, exact original order, matching evidence and reason. Missing, incomplete or failed proof cannot authorize a write. L2 failed-goal deduplication remains active; assessment and preparation are distinct goals.
5. `revalidate_return()` uses the existing owned-order lock, rereads current version and eligibility, checks pending/executed proposals under that lock, and holds it through the original domain preparation transaction. Active pending proposals respect database expiry time. Preparation only creates a proposal; the original independent Confirmation executes the Case.
6. Empty Multi write-goal responses use the existing shared, charged repair opportunity. A model-selected final finish reconciles domain receipts and checks pending HITL before directly ending; it avoids two empty administrative nodes. Model/tool/delegation calls remain charged, and the original 12/16/4/24/12000/90 limits are unchanged.
7. New public diagnostic projections contain known goals, tools, safe IDs, booleans and counters. No raw prompts, tool argument dumps, credentials or model reasoning are exported.

The synthetic positive model programs were explicitly migrated to assessment→preparation. They do not automatically rewrite production plans, use Task IDs to choose answers, alter Oracle expectations or fabricate business receipts. L2 repair tests now reuse verified cross-task evidence; they retain malformed-wire, permission, replay and two-confirmation assertions.

## Validation

Final results and raw log hashes are recorded below after completion. Intermediate failures remain in the private task directory; they are not acceptance results.

Failure history for this task:

- Scope-discovery and missing-assessment dependency tests first failed on the unfixed behavior (RED), then passed after the corresponding fixes.
- A preliminary regression was deliberately stopped before applying review changes; its partial log is retained and has no passing conclusion.
- First completed backend regression: **1173 passed / 15 failed / 14 skipped**. Failures were mapped to stale synthetic model programs/binding, hard-coded old call indices/counts, and a crash child missing the readonly policy dependency.
- First Playwright regression: **114 passed / 5 failed / 0 retries**. All five used the old test-only Workflow driver. The driver was explicitly migrated; browser assertions and retry settings were retained.
- Early test construction failures (RowMapping conversion, fixture noise label, wrong test path, missing helper imports and immutable-policy mutation) are retained. The policy chaos test now checks the actual database mutation, including the after-dispatch tool boundary.
- The first extra Fixture Oracle export collided with the helper receipt filename: its raw episode JSON was not preserved. The receipt/log remain; the separately identified **repetition 1** export uses a distinct filename and is independently checked. No historical result is reconstructed or overwritten.

The lower-cap regression retains a four-call safe-stop case with zero return proposal/Case. A separate six-call case tests correction exhaustion after the newly required five-call assessment/preparation prefix. The production model limit remains 12.

| Final check | Result | Raw log SHA-256 |
|---|---|---|
| postfix-full-pytest | 1191 passed / 14 original real-BGE skips | `6f1ba902202538a75e7255cae67c972f962bc9faebed727e21a3783699d6225d` |
| final-static-and-frontend | Ruff, format, TypeScript, ESLint, 127 Vitest, production build: PASS | `cb3397f66af06f339016be052657755bf17900169dec8572e7564a58ae757e39` |
| final-playwright | 119 passed / 0 retries | `fc920199a3f37d46d800ab377e31358f03ee25ef9de176678494cfe483335c9f` |

The final file-map SHA-256 (tracked/proposed files excluding this new report) is `5706c62f6f9b356dee36ae88829dadde545da1a4df0615887b6da8c32b8c9eb3` (sorted file SHA map in the private receipt). The final regression used unchanged source throughout. All 14 skips are the existing real-BGE group selected by `--ci-offline-core`; no skip or retry was added.

Measured SDK MockTransport B2: **11 models / 6 tools / 4 delegations / 20 steps / 330 simulated output tokens**. The separate existing Fixture evaluation program has additional product reads and measures **12 models / 9 tools / 4 delegations / 20 steps**; its unchanged Oracle passes. These are different deterministic programs, not two real-model trials.

Independent snapshot comparison for the saved Fixture episode: orders **1→2**, Cases **0→1**, payments **1→1**, confirmations **2→4**. The original order is DELIVERED; the only new order is PENDING_PAYMENT. The two new decisions bind distinct proposals and are consumed. Only one replacement SKU changes `reserved` by +1; all `on_hand` values and other SKU inventory are unchanged. Original Oracle/invariant violations: **0**. Official Checkpoint persistence and replay are exercised; the snapshot retains checkpoint tables and RunEvents. No claim is made from text alone.

The private record directory is `.playground/v213-l4-20261109T042030Z/`. It retains raw logs, exit/UTC/SHA receipts, JUnit, browser results, red/green attempts, the complete separate Fixture episode, independent snapshot comparison and cleanup receipts. Required raw episode SHA-256: `48e2f025a649665c2ddd6a9353fef9196c8e6ac3df7d49c2a9e8305b8fd625dd`. It contains synthetic private records and must not be published.

Cleanup: own Guest, PostgreSQL container, data Volume, runner image tag, cache and synthetic credentials removed with independent absence checks. Two schemas left by the intentionally interrupted preliminary run were privately dumped and hashed before removal of this task's owned database. They were not historical schemas. All **25** pre-existing container IDs/states remain unchanged; default Docker context remains `colima`. Shared BuildKit cache was not pruned. Private directories/files are 0700/0600.

Real Provider requests **0**; real Provider Key value reads **0**; Push/Dispatch/Rerun **0**. L3's eight original file hashes were rechecked unchanged.


## Required scenario coverage

| Scenario | Check |
|---|---|
| A, policy/eligibility only | Real SDK/PG policy-only run; no proposal, Case, order, confirmation or payment delta |
| B, explicit return | Completed assessment, separate writable task, RETURN_REQUEST proposal; no Case before approval |
| C, forged readonly write | Exact discovery set plus independent Guard rejection; tools charged/executed 0 |
| D, writable flag on assessment | Discovery still has no write; independent goal guard rejects forged preparation |
| E, no return intent | Supervisor/runtime reject preparation; database counts unchanged |
| F, ineligible order | No return proposal; independent recommendation can still complete, overall partial preserves refusal |
| G, foreign order | Domain ownership checks deny access; no business write |
| H, changed version/policy | Dispatch and tool execution both reject stale proof before proposal preparation |
| I, failed goal renamed | Existing L2 regression still rejects repeated delegation |
| J, existing return proposal | No new proposal; concurrent different origins produce exactly one; expired pending proposal allows a new legal preparation |
| K, rejected return | Case remains absent; an independent requested purchase still needs its own decision |
| L, missing purchase confirmation | Order count unchanged while checkout waits; return confirmation cannot be reused |

Full B2 uses the actual SDK codec/MockTransport, LangGraph, official Checkpoint and current domain services. It asserts the original SKU is excluded, replacement noise and budget are valid, two distinct decisions are required, resume replays preserve one Case/one new order, stock reservations match and payments do not increase. Decisions are **TEST_OPERATOR**, never real user authorization.

## Compatibility and limitations

- No claim that a real DeepSeek model will choose the correct scopes, finish its reads or stay within the budget. The deterministic offline path measures feasibility only.
- One charged orchestration repair can fit on the measured synthetic path; extra model/tool calls, clarification loops or environment delays may still exhaust fixed limits and must stop safely.
- Old unfinished Multi writes without assessment evidence require a new legal workflow; no hidden migration or approval inheritance is provided.
- Local Linux environment is aarch64. This is not a new Ubuntu amd64 remote CI result.

## Separately authorized B2 retest proposal

After review, freeze the new L4 commit and source fingerprint, allocate a fresh owned business/Checkpoint database and session, refresh official model/price information, and approve an independent budget. Suggested first scope is **one B2 Multi episode**, model identity explicitly frozen, **at most 12 Provider requests**, original tool/delegation/step/output/time caps, and **at most ¥2.50** with worst-case reservation before every request. This is a proposal, not an approval or enabled policy. If current official prices make that cap infeasible, stop before Key access and request a revised cap.

Use two independent TEST_OPERATOR confirmations only in the isolated evaluation simulator, record per-request usage/reservations and redacted route/tool/HITL diagnostics, and independently verify the Case, order, stock, payment delta and Oracle. UNKNOWN Provider responses retain reservations and stop without automatic resend. A single retest is not a repeated reliability experiment; any repeated experiment needs its own predeclared repeat count and cumulative budget. Compare new evidence with preserved L3, including failures. No previous Pilot authorization is reused.

## Changed files

- `backend/src/agentmall/agents/durable_graph.py`
- `backend/src/agentmall/agents/return_handoff.py`
- `backend/src/agentmall/agents/runtime.py`
- `backend/src/agentmall/agents/specialist_tools.py`
- `backend/src/agentmall/agents/specialists/aftersales.py`
- `backend/src/agentmall/agents/specialists/runner.py`
- `backend/src/agentmall/agents/supervisor.py`
- `backend/src/agentmall/infra/observability.py`
- `backend/tests/multiagent_helpers.py`
- `backend/tests/playground_helpers.py`
- `backend/tests/t09_helpers.py`
- `backend/tests/t09_worker.py`
- `backend/tests/test_baseline_fairness.py`
- `backend/tests/test_commit_then_crash.py`
- `backend/tests/test_handoff_constraint_continuation.py`
- `backend/tests/test_handoffs.py`
- `backend/tests/test_multiagent_integration.py`
- `backend/tests/test_multiagent_review.py`
- `backend/tests/test_v213_l2_sdk.py`
- `backend/tests/test_v213_l4_business.py`
- `backend/tests/test_v213_l4_handoff.py`
- `backend/tests/test_v213_reliability.py`
- `backend/tests/test_v2_intent_routing.py`
- `backend/tests/workflow_e2e.py`
- `docs/evidence/v213-l4/report.md`
- `evals/fixture_model.py`
