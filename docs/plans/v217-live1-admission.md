# V2.17 LIVE1 admission implementation plan

Goal: provide a bounded composition of existing formal APIs and the existing
Playground SDK transport/ledger for the three already frozen product-smoke inputs.
This is local engineering, not Live authorization or an evaluation result.

Base: `550853eeffe113f840dbe17de57fc71e3d68434b`. Preserve the original proposal,
protocol, Prompt, business runtime and all L8 evidence. No old L8 Host is imported.

## Design and scope

Reuse `create_app`, `initialize_environment`, `PlaygroundLedger`,
`PlaygroundTransport`, `attach_models` and the explicit `controlled_offline.Operator`.
The older `evals.provider` transport does not fail closed on all unknown outcomes;
it is audited, not silently substituted for the stricter existing implementation.
Do not build another Host, authorization service or evaluation platform.

Add a smoke-specific composition module, an independent SQL assertion module and
contract tests. Maintain a small private batch receipt containing the fixed A/B/C
order, exclusive task identities, full per-task fee holds and continuous wall-clock
timestamps. Never resume/recover a stopped execution. A restart is read-only.

The operator makes one explicit command per decision and one separate Resume.
Proposal GET, identity/snapshot verification, Confirmation GET and original API
business validation remain required. A cancelled/ambiguous write halts the batch;
it is never replayed or marked successful. Cleanup requires frozen, exported,
verified evidence, known ledger/write outcomes and exact current-task ownership.

The existing durable graph enforces model/tool/delegation/step/output limits.
The composition additionally enforces input/HTTP/fee limits and persisted
Episode90s/Outer300s across HITL. Outer begins before initialization; authorization
waiting begins neither clock. No CLI flag or synthetic receipt grants Live access.

## Execution checks

- [x] Pin missing admission behavior with failing synthetic tests first.
- [x] Implement only the composition and safe evidence/clock/operator adapters.
- [x] Exercise the real SDK parser with MockTransport for all response/usage faults.
- [x] Exercise real PostgreSQL, Checkpoint, explicit HITL and independent SQL facts
      using development or CONTRACT_TEST_ONLY inputs, not L8 unrun tasks.
- [x] Verify BGE revision/six hashes and 512-dimensional CPU inference.
- [x] Run final backend suite/static checks against final source; run frontend
      regression if the shared API or product runtime changes.
- [x] Independently review the final diff and freeze new local Commit/Tree and
      the unchanged three-task proposal/protocol into a new external binding.
- [x] Export/verify evidence before exact owned-resource cleanup; preserve failures.

## Admission decisions

No real Provider key is read during engineering. Future execution requires a new
Owner decision binding final source/tree, proposal/protocol, current price/model,
three-task order, resources, explicit operator and CNY2.50/task/CNY7.50 batch caps.
Mock evidence cannot issue that decision. Actual supplier invoice remains UNKNOWN
unless independently obtained; a reservation/observed upper bound is not an invoice.
Unknown usage, budget or business writes stop the entire batch.

## Final disposition

Offline composition and regressions are complete. Overall admission is BLOCKED:
the unchanged B input has a unit/total-price conflict and C has unsupported return
intent wording. No Live authorization is requested. The external binding records
this failure before ARM. Known failed test environments are preserved; exact owned
containers may be stopped after evidence verification, without deleting volumes.
