# T16-A: versioned Thread context (offline implementation plan)

Scope: structured preferences, verified ranked candidate references and existing durable workflows. No new commerce domain, paid requests, remote writes or historical evidence changes.

## Storage and trust

Add a one-to-one ThreadContext with optimistic version, whitelisted preferences and current candidate-list references. Add immutable CandidateSet records populated only by authenticated retrieval tools; ranks bind product IDs, price and catalog version. Bind each new Run to its accepted context snapshot in the same transaction as preference updates. Existing Runs/results and old stateless callers remain compatible. Once a Thread opts into versioned context, subsequent starts require its version.

Only category, budget, quiet preference and ProductNeeds persist. Quantity, delivery alias, purchase intent, confirmation, interrupt and model budget never persist as preferences. Current user text and explicit patch operations can replace or clear preferences; contradictory constraints within one input require clarification. Model outputs and retrieved text cannot update trusted preferences.

## References and authorization

The browser sends the displayed candidate-set ID and expected context version. Ordinals resolve against that immutable set, never a newly sorted list. A changed preference invalidates the old list. Multiple lists or unclear references require clarification. Read and proposal creation revalidate product ownership, active status, price/version and availability. Proposals still require an independent Confirmation and durable Resume. THREAD_BUSY, epoch fencing, node journals and action idempotence stay intact.

## API and interface

Extend GET Thread with context and verified candidate cards; add an authenticated idempotent PATCH context endpoint. Add optional context version and candidate-set ID to RunCreate. The workspace shows confirmed preferences, version/provenance, numbered candidates, explicit preference editing/clearing and read-only historical Run navigation. No raw historical chat or model reasoning is shown or concatenated.

## Test-first sequence

1. Add failing PostgreSQL tests for budget replacement, clearing, immutable Run snapshots, CAS/idempotence and cross-owner isolation.
2. Add migration and minimal context service; bind creation/recovery to its snapshot.
3. Capture retrieval lists and validate ordinal references; exercise real ChatDeepSeek SDK through conditional MockTransport with different structured inputs and actual domain tools.
4. Add UI and focused Vitest/Playwright tests for three turns, confirmation, refresh/login, stale lists, response loss and no purchase intent.
5. Run full offline backend, frontend and browser regression in a new clock-observed Linux VM. Keep the existing 14 skips unchanged. Preserve every failed attempt and report environment limits.

## Evidence and release boundary

Private raw receipts live under ignored .t16-a only. Public evidence contains synthetic IDs, sanitized summaries, actual commands/counts/exits and hashes. Old T15-B1 Live evidence remains evidence for its historical commit only. T16 makes zero real provider calls. Final completion requires the complete regression and critical cases; otherwise report BLOCKED without overstating coverage.
