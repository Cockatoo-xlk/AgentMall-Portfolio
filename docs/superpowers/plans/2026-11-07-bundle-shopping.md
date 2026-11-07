# Bundle Shopping Implementation Plan

**Goal:** 2–5 independently constrained categories, one deterministic feasible bundle and one explicitly authorized multi-SKU checkout, retaining all V2.5 single-product flows.

**Architecture:** A strict BundleRequirements contract lives inside current authenticated Thread preferences. Shopping invokes one bounded Hybrid RAG tool per requested category; its last successful retrieval triggers deterministic composition from verified candidate pools. This stays inside existing Shopping/Supervisor handoffs and original model/tool/delegation budgets. Order receives only a currently selected immutable bundle and uses the original multi-item CHECKOUT service and HITL. CandidateSet gains a kind/details extension through migration0009, preserving old rows as product lists. Runtime facts/candidate_lists already participate in official Checkpoint and Node Journal snapshots.

**Execution:** Native implementation and directed tests, followed by a fresh read-only code review and one bounded full local offline regression. One local commit, no remote writes.

## Invariants

- Global budget is integer cents across quantities, not a per-item allowance.
- Per-category filters never leak to another category; unknown/conflicting requirements clarify.
- One SKU per category,2–5 unique categories; bounded5-candidate pools, at most3125 combinations.
- Rank feasible combinations by explicit quiet preference, total price, then stable Product IDs. No global-optimality claim beyond retrieved candidates.
- Snapshot binds Thread/source Run/actor/store/preferences digest, prices, versions, quantities and15-minute server expiry.
- Purchase requires current intent, an explicit unique/current bundle selection, user-specified quantities and address. One proposal, one Confirmation, one atomic order. Any stale/foreign/missing item rejects the whole action.
- No payment/refund/domain transaction changes, new Agent, queue, Provider request, Key read, old DB/container mutation,900-second admission, encrypted evidence framework or remote operation.

## Tasks

- [x] Add failing parser/planner/selection tests and append CandidateSet migration0009.
- [x] Implement strict requirements, deterministic parser and bounded factual composition.
- [x] Add bundle memory publication/selection/expiry; preserve legacy request and checkpoint shapes.
- [x] Add scoped Shopping retrieval and Order bundle tool; preserve budgets, HITL and replay semantics.
- [x] Add responsive bundle cards, complete checkout details and actual SSE computation events.
- [x] Verify A–J in owned Expanded PostgreSQL/official Checkpointer with MockTransport; Legacy compatibility and small UI tests.
- [x] Run one bounded complete offline regression, review privacy/source scope, preserve failures, remove only owned test resources and commit locally.

## Review focus

Missing-category false success; global quantity/budget overflow; stale plans or wrong actor/store; model-supplied extra SKUs/quantities; partial inventory reservation; duplicate publication/expiry extension; legacy tool exposure and memory shape.

## Final verification note

One complete regression found legacy registry/Fixture integration failures. These were corrected without changing frozen manifests and verified with bounded targeted reruns. The final report preserves the failed full-run receipts; no second complete run or remote CI is claimed.
