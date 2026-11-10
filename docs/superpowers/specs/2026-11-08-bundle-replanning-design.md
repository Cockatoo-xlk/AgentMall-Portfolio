# V2.9 Multi-turn Bundle Replanning

User delegates bounded design and implementation; no intermediate approval pauses. Base8a8d54bd7b21d7e084c7a8d02f312d64f0203b4b in existing linked worktree.

Reuse CandidateSet JSON details, ThreadContext optimistic version, immutable Run snapshots and existing HITL checkout. No new table or authorization fields. Alternatives: full retrieval on every edit violates incremental requirement; new planner/database duplicates existing paths. Chosen: strict revision operations bound to latest offered source + context version; service applies complete validated delta, refreshes only affected pools, revalidates other exact SKUs.

Operations KEEP, REPLACE(cheaper optional), SET_CONSTRAINT(allowlisted ProductQuery fields), ADD, REMOVE, UPDATE_BUDGET and UPDATE_QUANTITY. Controlled Chinese grammar with residual checking; unsupported clauses clarify, contradictory operations reject atomically. Structured and text changes must agree when both supplied. Modification and purchase cannot coexist. No inherited consent.

Reuse current tool entry and bounded composer (five candidates per category / at most3125 combinations). Reused pools contain the freshly read exact source SKU, invalid source gives explicit gap; refreshed pools keep all other hard predicates. Changed budget/quantity recomputes total without vector queries. Cheaper means unit cents strictly less than prior snapshot. Fresh snapshot rechecks price/version/stock/store.

New CandidateSet details include source_bundle_id, revision operations, per-category reuse/refreshed/invalid status and old/new facts/total/budget diff. Old CandidateSets remain immutable; current offered IDs cleared upon accepted edit even when infeasible. Bounded last20 historical snapshots exposed read-only with no purchase selection. Idempotency uses unchanged Run request receipt and digest. THREAD_BUSY blocks edits during confirmation.

Existing persisted event allowlist extended with scalar category/count/amount summaries only. Existing SSE GET/stream delivers them. Existing BundlePanel shows diff/history and controlled editing guidance; natural-language task input plus API typed revision, no new agent framework. Current purchase path still requires latest unique bundle, explicit quantities/address and independent Confirmation.

Tests: PostgreSQL operations A-L, actual retrieval query counts, immutable source, replay/stale/concurrent versions, corrupt or unavailable source, budgets/stock/confirmation, restore/events; Fixture/Mock only. One bounded complete offline backend/frontend/browser run plus minimal fixes/necessary retests. Old databases/containers, MCP authority, transactions and frozen eval data remain unchanged.
