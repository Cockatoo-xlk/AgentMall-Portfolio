# T15-C local design and execution plan

Base: 617cdf29a4353673bbfe141d5c87eec1ce665ec3. Scope is the user's T15-C request; native inline execution. No Key reads, new model calls, remote writes or changes to historical workspaces.

## Design

Keep the existing Workspace, authenticated runtime status, RunEvent timeline and HITL coordinator. Expose PostgreSQL time in the authenticated proposal GET X-Server-Time header; the client attaches display-only server_time metadata. Proposal response JSON, POST/replay results and immutable payload/hash remain byte-compatible. Anchor the visual countdown to this time and browser monotonic elapsed time, never browser wall-clock authorization. At zero pause new approval and perform at most one GET per snapshot; the server alone declares EXPIRED. Missing time means UNKNOWN with manual status refresh. Existing confirmation/receipt recovery keeps its stable identifiers. Requote is an explicit user action; no automatic Run or paid call.

Improve existing timeline labels into readable role/tool/status summaries while retaining safe persisted metadata and pagination. Runtime counters remain server-provided; unknown Usage/bill and stopped budgets stay explicit. Publish only a manually reviewed aggregate B1 summary tied to the old source commit/fingerprint, never private ledgers, approval or checkpoint blobs. This source changes the fingerprint and is NOT live verified.

Alternatives considered: browser Date.now authorization is inaccurate under clock skew; a separate trace system conflicts with canonical RunEvent. Reuse existing APIs and add only server-time metadata.

## Tasks

1. Read-only verify B1 seven receipts, event seq1..50, official checkpoint summaries, manual confirmation and DB oracle; hash protected original artifacts before/after. Create a public allowlisted aggregate with historical-version caveat.
2. RED first: PostgreSQL response-time/immutable-snapshot tests; countdown unit tests including skew/missing time; browser expiration and no-auto-rerun tests. Implement minimal additive time and countdown, readable trace, runtime budget improvements. Preserve stable resume IDs and explicit human actions.
3. Update README/COPYRIGHT/SNAPSHOT and developer Live/recovery guide; add a 3–5 minute recording script and owner release checklist. Preserve old failures, exact test environments and frozen manifests.
4. Isolated staged offline CI: PG17/pgvector dedicated project, bounded backend memory, host browser. Run whole pytest CI_OFFLINE_CORE (only existing14skips), Ruff, TS/lint/build, Vitest, whole Playwright retries0; save command exit/log hashes and cleanup owned schemas/processes.
5. Audit all added/changed reachable historical blobs from public main through T14-P0/P1/R1-A/T15-A and new commit; classify synthetic/private/public/unknown. One independent final review, fix real issues once, local commit and stop.

## Review focus

- Missing/malformed server timestamp and skewed browser clock never authorizes an expired proposal.
- Countdown zero or refresh causes no Confirmation/Resume/Run/Provider write.
- Existing committed/unknown-response operation remains reconcilable after a deadline.
- Old B1 evidence is historical after any frontend/backend fingerprint change.
- Public summary/history contains no original approval, ledger, full checkpoint, machine paths or real tokens; all old source/evidence unchanged.
