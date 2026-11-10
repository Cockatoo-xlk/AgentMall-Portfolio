# T14-P1 Cart Lifecycle Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans in this session, one executor; one final targeted review. No parallel implementation.

**Goal:** Successful cart checkout consumes only its verified, unchanged cart within the order transaction; every confirmed/recovered order re-reads server cart state.

**Architecture:** `prepare_checkout` adds server-verified cart_source to immutable/hash-bound canonical_payload only for cart requests. `_execute_checkout` retains idempotency -> proposal -> confirmation -> UUID-sorted products with a cart-source-only owned-cart prefix lock before those locks; exact version/item match consumes only quoted rows and increments once. Mismatch preserves cart but permits the established old-snapshot order contract. Receipt gets additive nullable cart_consumption; old proposals/receipts remain readable. Order detail re-reads proposal receipt and GET /cart through CartProvider, never browser-clears arrays.

**Tech Stack:** Existing PostgreSQL17/pgvector, SQLAlchemy/Psycopg/FastAPI, React/TypeScript/Vitest/Playwright. No new dependencies, schemas, payment adapters or migration expected.

**Spec:** User T14-P1 request in this chat; exact baseline d8a18b0b56b0bdebe9a1ea1400849f82cecdbbef. Rules copied into task assertions below.

## Global Constraints

- New worktree `AgentMall-T14-P1-Cart-Lifecycle`, branch `codex/t14-p1-cart-lifecycle`; no source/index/config changes to original Private, published main or P0 worktree/evidence.
- Local only: no Push, remote Actions, deploy, paid models or historical Manifest/evidence updates.
- Dedicated Compose project `agentmall-t14-p1`, PGDATA `.t14-p1/postgres-data`, host55439/8015/5185. Five pre-existing containers including the active P0 demo are not ours.
- Baseline644/14, Vitest55, Playwright60; new cases separately counted, no added skips. Historical frozen source hashes stay frozen and describe older revisions.

## Review Focus

- Cart version changes before/while checkout or after commit: preserve new/modified/re-added items; no stale read/UI overwrite.
- Item-list/legacy checkout with a cart-like proposal_slot must not consume cart.
- Failure after deletion must roll back cart/version, reservation, confirmation, receipt, event and order together.
- Same/different idempotency keys, lost HTTP response and process restart must recover one order and one cart consumption.
- Cart refresh errors after a committed order are unknown cart state, never order failure or a false empty cart; source/receipt queries remain authenticated.

## Task 1 — Atomic backend consumption

Files: actions/service.py, actions/schemas.py, cart/service.py; new tests/test_checkout_cart_consumption.py. Interfaces: cart_source={cart_id,user_id,store_id,version}; optional ActionReceipt.cart_consumption in CONSUMED/SKIPPED_CART_CHANGED/NOT_APPLICABLE.

- [x] Write real PG tests for unchanged cart, add B/modify A/remove-readd A, unrelated/legacy checkout, reject/expiry/stock failure, rollback/replay, cross-user/store and observed lock waits. Observe expected RED before product code.
- [x] Implement provenance and transaction consumption, retain existing sorted product lock order, re-check clock after all lock waits; replay returns persisted result before any cart consumption. Run new tests and existing checkout/cart/order lifecycle tests.

## Task 2 — Server cart refresh and UI evidence

Files: frontend/state/Cart.tsx, pages/Orders.tsx, api/types.ts; backend/tests/web_e2e_server.py read-only cart facts; new frontend/tests/cart_checkout.spec.ts and narrowly targeted Vitest as needed.

- [x] Real UI RED: create cart order, assert PENDING_PAYMENT and empty server cart/badge before payment; payment success, refresh/relogin stay consistent.
- [x] Implement receipt-aware GET refresh, preserve monotonic cart versions and explicit skipped/unknown notices. Test new B/modified A protection, Agent direct order, refusal/expired/failure, double click/lost response and read-only recovery; compare independent SQL facts and capture screenshots.

## Task 3 — Regression, one review, protection and local commit

- [x] Build immutable final runner, verify loaded source hashes, run full CI_OFFLINE_CORE (Ruff/format/pytest/typecheck/lint/Vitest/build/Playwright); keep every failing receipt. One targeted read-only independent review, reproduce/fix confirmed issues and regress as needed.
- [x] Curate local report, file list, true DB/PNG/command-hash evidence and frozen Manifest version boundary. Stop only owned resources; schemas/sessions/advisory locks0. Re-hash Private/main/P0/R5 and pre-existing container identities. Local commit only, clean worktree, stop.


## Execution boundary

完整命令集合分阶段验证：Linux容器后端670/14；最终Mac静态检查及Vitest65；Mac完整Chromium headless + 本轮容器FastAPI/PG/Checkpoint全量74。单容器一体化CI因真实OOM中断143，不标记为该命令通过。旧P0 runner结束原因UNKNOWN，所有明确保护文件及四个旧PG容器的身份/启动时间/挂载/端口另行核对，不能以文件核验代替运行时无影响证明。最终凭据见docs/evidence/t14-p1/。
