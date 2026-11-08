# Merchant Copilot Implementation Plan

> Execute inline with superpowers:executing-plans; user delegates decisions. One fresh final review, one final local commit, no remote operation.

**Goal:** Authenticated merchant questions produce actual read tools, bounded deterministic statistics, cited suggestions and editable review drafts.
**Architecture:** Separate request-scoped LangGraph + original read services/MCP projection, read-only snapshot, explicit MockTransport, fetch-SSE and existing merchant forms.
**Tech Stack:** FastAPI/SQLAlchemy/PostgreSQL/LangGraph/ChatDeepSeek MockTransport/React.
**Spec:** docs/superpowers/specs/2026-11-08-merchant-copilot-design.md

## Constraints and review focus
No domain writes, buyer-thread privilege changes, Provider/Key, old DB/container changes or remote writes. Preserve missing/partial scopes and error metrics. Object ownership, stale fingerprints, model invented IDs, untrusted descriptions and auth switch/disconnect are fail-closed tests. Reuse existing MCP auth and projections; no new dependencies.

- [x] Owned PG/runner and fresh baseline: verify source, resources, start only new names; necessary small baseline tests.
- [x] RED backend merchant-only/disabled/actual tools/counts/zero writes. Add contracts, domain reader, bounded model adapter, graph, JSON/SSE/recheck routes. GREEN.
- [x] RED evidence invention, cross-Store, unsafe args, truncation, policy, timeout/cancellation and snapshots. Implement narrow evidence renderer and guard. GREEN.
- [x] Official MCP read adapter: two tools, direct result equality over real localhost transport; negative mismatch/forbidden tools. No existing gateway changes.
- [x] RED frontend parsing/no auto execution/auth-stream/readonly fill. Add MerchantCopilot and workbench tab/focused case/reason form bridge; explicit Mock composition root, browser realPG scenarios/screenshots.
- [x] Bounded A-N offline evaluation, one full pytest/Vitest/Playwright, Ruff/format/typecheck/ESLint/build; retain failures, minimal fixes.
- [x] One fresh final review, privacy/protected files/docs, owned resource cleanup, local commit and CLEAN.

Ruling: delegated autonomous execution waives design approval pauses; no separate builder subagent. One final review only. Model-generated prose is not trusted business data; advisory templates/tone are deterministic and cited. Stateless analysis avoids a second durable workflow system.

Final: 1083/14 pytest,126 Vitest,118 full Playwright, static/build pass. One fresh review findings RED/GREEN fixed, no re-review. Raw failures retained; owned cleanup and final privacy audit/commit follow.
