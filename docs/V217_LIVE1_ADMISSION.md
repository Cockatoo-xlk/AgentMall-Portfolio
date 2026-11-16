# V2.17 LIVE1 Runner admission

Status: **ADMISSION_BLOCKED**. This is offline engineering evidence, not a real
model result. Original Smoke A/B/C are all **NOT_RUN**. Live authorization is NONE;
real Provider requests, real Key reads and actual expenditure are all zero.
Release remains ON_HOLD.

## Frozen inputs and the two product-contract blockers

The implementation branches from main
`550853eeffe113f840dbe17de57fc71e3d68434b`, tree
`09c712d590a85170e688748d13823c46170f61aa`. Its main push CI is
[43845199507](https://github.com/Cockatoo-xlk/AgentMall-Portfolio/actions/runs/43845199507).
This existing main CI does not replace the new branch's local regression.

Preserved byte-for-byte:

| Object | SHA256 |
| --- | --- |
| `evals/proposals/v217-product-smoke.json` | `4dd539b51bc1b3162825a3721bb3e99c59d264ad9794d49db6107603fa620230` |
| `docs/V217_LIVE_SMOKE.md` | `bd5a7a44a16b5f8e2a112a42ae2c647364b97eec407ae186250369031758d96e` |
| Original `evals/oracles.py` | `dac5a79ee6b8c5d9a0807b043eb67bd47403ebba5eb1a8514bec9d1d6e982fb6` |

Pure calls to the existing `user_constraints(MultiRequest(...))` parser expose:

* B requests two K68 items at CNY199 each. The frozen sentence's amount becomes
  `max_price_cents=19900` and quantity=2. Existing purchase validation treats that
  budget as the complete purchase limit: `19900 * 2 > 19900`. This is a unit-price
  versus total-budget interpretation conflict, not an observed model failure.
* C's wording `申请质量退货` does not match the existing explicit return-action
  patterns. The remaining bare `退货` is intentionally excluded as sufficient
  authorization; `return_requested=false` and `reason_code=None`. `prepare_return`
  therefore cannot legally execute the requested return. Recognizing the quality
  reason independently is also necessary; the parser currently recognizes
  `质量问题`.

Sources: `agents/context.py:user_constraints`,
`agents/request_intents.py:RETURN_ACTION/_request_intent/return_intent`,
`agents/runtime.py:checkout_blocker`, and
`agents/specialist_tools.py:prepare_return`, under `backend/src/agentmall/`.

`static_admission` and CLI binding validation now reject these incompatible frozen
contracts **before ARM, database initialization, credential consumption or any
Provider request**. They do not inject typed constraints, rewrite user input,
alter product parsers, or claim that a static-compatible task has passed.
An independently authorized product-parser fix and a newly bound Source are
needed before these exact tasks can be admitted. Changing the tasks or weakening
the purchase/return permission checks is not an acceptable workaround.

## Reused execution chain

`smoke_cli` → `SmokeBatch` → `SmokeSession` → formal FastAPI ASGI/Run API → existing
LangGraph/DurableBudget/Checkpoint/Fence → existing Playground SDK transport and
ledger. Single and Multi use the same ChatDeepSeek request validation and budget
path. No L8 private Host, new Agent, Orchestrator or generic evaluation service is
introduced. `evals/provider.py` is unchanged and is not the admitted transport.

The additional modules are narrow composition, independent SQL assertions, and
an explicit local operator console. Initialization creates new owned UUID schemas
and a Checkpoint schema; a real local BGE encoder is mandatory in native mode.
The delivered-order setup for C uses formal checkout/confirmation/mock-payment/
merchant APIs and is recorded separately from the Smoke baseline. This is
synthetic business setup, never real funds.

Operator calls remain separate: inspect actual persisted Proposal, explicitly
approve or reject that snapshot, then separately Resume with the bound
Confirmation and new request ID. There is no decision loop or automatic Recover.
Cached receipts cannot bypass current actor, authorization, clock or ledger
checks. Duplicate formal API Resume is covered as well as local receipt replay.

## Enforced limits and trust boundary

Per task: HTTP/model12, tool16, delegation4, step24, input3145728/output12000
Tokens, Episode90s, Outer300s, CNY2.50. The three-task conservative fee holds total
CNY7.50. Existing durable graph limits are retained. Outer begins durably before
initialization; Episode begins before the first Run API call and includes all
HITL waiting. Buffered nonblocking operator input and Provider/API timeouts cannot
pause or reset either clock. Process reattachment cannot resume execution.

Native HTTPS retains TLS verification, retries=0, trust_env=false and redirects
disabled. Every request has a persisted full-context reservation before sending;
status/model/tool JSON/schema/Usage validation and settlement precede SDK delivery.
UNKNOWN or RESERVED cannot authorize another request. Exceptions preserve holds.
An HTTP200 Run carrying a fatal infrastructure/scope/budget error also stops the
entire batch, rather than being treated as an ordinary business failure.

Price verification binds the official DeepSeek documentation, exact model mapping,
peak all-cache-miss rates and an actual checked_at within 24 hours. No timestamp
refresh without a fresh official lookup is allowed. The documented revision is
not immutable Provider weights. Real TLS and real Provider execution were not
tested in this task.

Live requires a separately obtained exact-binding Owner decision. The local
receipt records that decision and is one-use; it is **not** cryptographic proof of
external approval or protection against a malicious same-UID process. Tests never
create a real Owner grant. Static contract blockers remain effective even if a
receipt is supplied. CLI flags or synthetic contract mode cannot activate native
network sending.

Credentials are consumed once from a separate anonymous pipe only after owned
PG initialization, BGE verification and actor binding. No Provider environment
variable is read. No key appears in arguments, evidence, errors or logs. The
mutable FD buffer is zeroed and SDK clients are closed/detached; this does not
claim secure erasure of immutable Python/SDK strings or Host process memory.

Owner clarified that settled, validated Usage and budget closure are distinct
from a supplier's actual invoice. The invoice remains **UNKNOWN** when absent;
estimated upper cost is never relabeled actual billing. Usage/budget UNKNOWN
still stops the batch and retains the original reservation.

## Evidence, assertions and cleanup

Freeze → exclusive export → SHA256 verification precedes independent scoring.
Starting freeze permanently disables the Session's start/decision/Resume methods,
including when export fails; a waiting Run cannot be approved after its snapshot
has been sealed.
Assertions compare formal API results against SQL business facts, independent
Confirmation consumption, inventory/order deltas, payment/refund deltas,
Checkpoint metadata and worker/lock state. A completed Run alone cannot pass.
Agent inputs contain user requirements; assertion expectations do not enter the
model. Raw prompts, authorization headers, private Checkpoint bodies and arbitrary
Provider response bodies are not exported.

A fatal first Run may commit before the synchronous API returns an error. The
runner records its request ID before starting; halt-time discovery uses only GET
on that owned Thread and exact request ID. The console attempts a best-effort
read-only forensic export, closes clients, and preserves resources. Its asynchronous
10-second timeout cannot hard-interrupt synchronous SQL connection/read calls;
this is not a guaranteed forensic completion deadline. It never
settles an unknown request or resumes a failed Run to obtain evidence.

Cleanup is a separate explicit operator instruction for the current verified
schema pair. It requires exact environment ownership, a completed client-close
proof, known writes/Usage, and no halt. Known ordinary Oracle FAIL is not by
itself a cleanup blocker. UNKNOWN, missing evidence and ownership mismatch retain
resources. The tool cannot delete Docker containers/volumes or historical assets.

## Evidence interpretation and remaining work

Final local regression, executed 2026-11-16 in this task's isolated network:

| Check | Actual result | Exit |
| --- | --- | --- |
| Full CI_OFFLINE_CORE backend, serialized | 1681 passed / 15 skipped / 6 warnings | 0 |
| Real fixed-revision BGE selection on final code | 14 passed / 1682 deselected / 3 warnings | 0 |
| Vitest | 146 passed | 0 |
| Playwright | 129 passed / 0 retries | 0 |
| TypeScript / ESLint / production build | passed | 0 |
| Ruff / format | passed, 345 Python files formatted | 0 |

The core suite's 14 BGE skips were executed separately above. The remaining skip
requires unavailable historical private Live evidence; its synthetic regression
still ran. Six backend warnings concern existing `record_property` with xunit2;
the BGE warnings are existing jieba escape-sequence warnings. A first full run
reported 1679 passed / 1 failed / 15 skipped when a global schema-snapshot cleanup
test overlapped independent BGE teardown. Its assertion was unchanged; the final
serialized full run above passed. Other retained red/green failures cover fixture
selection, operator identity, fatal-first-Run export and post-freeze writes. None
is erased or represented as an original Smoke model result.

Tests use DEVELOPMENT / CONTRACT_TEST_ONLY requests, real PostgreSQL, actual SDK
MockTransport and separately fixed-revision local BGE. Development B/C inputs
exercise supported semantics; their success is not a result for the incompatible
frozen Smoke inputs. Synthetic operators explicitly inspect and approve each
Proposal in separate calls; this is not unattended Live permission.

New source hashes, commands, actual counts, exit codes, warnings, intermediate
failures, log hashes, model-file hashes and owned resource receipts are retained
in the task's ignored private evidence directory. After a local commit, CLI
`prepare` records the exact new Commit/Tree and all tracked source hashes in an
external binding without changing the original V2.17 freeze. Do not call this
branch original V2.17 Source.

L8 remains PASS1 / FAIL4 / NOT_SCORED3 / NOT_RUN7; 08 Usage ledger and actual cost
remain UNKNOWN, E1_ORACLE_CONTRACT_MISMATCH remains open, independent Holdout=0.
This Runner work does not rerun or rescore L8. Future real Smoke requires resolved
product compatibility, a fresh clean source binding, a valid official price
snapshot, new isolated resources and separate Owner API/fee/operator/credential/
cleanup authorization. No paid authorization is requested while admission is
blocked.
