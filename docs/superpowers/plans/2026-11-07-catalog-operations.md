# Catalog Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Native execution, one final fresh read-only code review. User has delegated implementation choices and local completion; one local commit at the end.

**Goal:** merchant import/draft/assisted extraction/review/publish/index/buyer shopping closed loop.
**Architecture:** scoped draft and import records, shared command receipts, explicit bounded index tasks; reuse Product and original commerce services.
**Tech Stack:** existing FastAPI, Pydantic, PostgreSQL/SQLAlchemy, React/TypeScript, pgvector and MockTransport.
**Spec:** docs/superpowers/specs/2026-11-07-catalog-operations-design.md

## Constraints

Base cb70ebb6687490db7b21794eb8257a1078d6939d; no real Provider/Key, main/PR/remote operations, historical database/volume changes, new queue, frozen data edits, payment or LangGraph rewrite. New isolated test resources only. Preserve 13 categories, Legacy12 and Expanded120 identities.

## Review focus

- A model inventing or moving a source quote: reject rather than trusting the draft.
- Publication race with inventory reservations: lock and never decrease on_hand below reserved.
- Response loss and mutation replay: stable command identity and authoritative GET recovery.
- Index failure/current version mismatch: retain published fact, prevent stale retrieval and bound attempts.
- Approved content changed before publish: invalidate approval; never publish an unreviewed revision.

## Steps

- [x] RED tests for import, source-verified parser, states/permissions/version/idempotency and index behavior.
- [x] Add catalog_operations schemas/models and migration0010; preserve old migration history.
- [x] Implement bounded file ingestion, disabled/MockTransport Parser, source witnesses and draft review.
- [x] Implement merchant command services/routes and targeted ProductSearch upsert.
- [x] Integrate product tab, upload/paste, draft editor/evidence, separate approve/publish/index and recovery controls.
- [x] Verify new product listing/RAG/Agent/Single+Bundle checkout, failures, stock and original snapshots in fresh PG.
- [x] Run related pytest, complete Vitest, selected Playwright and static checks; review, retain failures, clean own resources, commit locally.
