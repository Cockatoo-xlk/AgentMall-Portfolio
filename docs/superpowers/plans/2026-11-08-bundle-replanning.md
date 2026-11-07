# V2.9 implementation plan

Inline execution with TDD and one fresh read-only final reviewer, then one local commit. User requests autonomous execution.

## Constraints and review focus
No Provider/Key, remote writes, historical resource changes, MCP auth changes, commerce state-machine changes or900-second monitor. Review unsupported hard clauses, mixed purchase+edit, stale sources after failed replan, KEEP with catalog mutation, concurrent/replayed request and pending proposals.

- [x] Fresh owned PostgreSQL/runner; RED API/SQL tests for all revision operations and incremental query contract.
- [x] Strict BundleRevision schemas/parser/apply in new agents/bundle_revision.py; integrate existing context acceptance and request digest compatibility.
- [x] Reuse fresh exact SKU or refresh affected pool in bundle_tools; persist diff/history and allowlisted events without changing checkout.
- [x] Extend existing BundlePanel/types/timeline; RED/GREEN component and browser restore/confirmation test with screenshots.
- [x] Directed tests, then one complete offline pytest/Vitest/Playwright + static/build. Preserve failures and bounded retests.
- [x] Fresh read-only reviewer, security/scope audit, docs/results and exact owned cleanup; one local commit, CLEAN.
