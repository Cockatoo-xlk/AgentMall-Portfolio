# Expanded Catalog Implementation Plan

> Execution: native implementation, followed by independent code review.

**Goal:** 13 categories and 120 synthetic SKUs without changing the legacy 12-product evaluation profile.

**Architecture:** Preserve `seed(..., profile="legacy")` by default. An explicit expanded profile adds 108 UUID5-keyed records from a versioned JSON resource, never overwriting existing rows. Share category vocabulary across DTOs, search and trusted intent parsing; keep business execution unchanged. The local demo explicitly selects expanded while tests and evals retain legacy defaults.

**Tech stack:** Existing PostgreSQL 17/pgvector, SQLAlchemy/Alembic, FastAPI, LangGraph and React/TypeScript. No new dependencies or services.

## Constraints and decisions

- Keyboard 8, mouse 6, headphones 6; each of 10 new categories 10: total 120.
- Original 12 UUIDs, values, orders and frozen evaluation artifacts remain unchanged.
- Append migration 0008; downgrade must refuse while expanded categories exist.
- JSON records contain SKU, category-specific string attributes, synthetic description, price and inventory; UUID5 uses storefront plus a versioned SKU key.
- Category aliases are deterministic catalogue vocabulary. Multiple explicit categories remain ambiguous rather than silently choosing one.
- Strict screen-size filtering for the monitor comparison; category transitions clear incompatible keyboard preferences. Never inherit purchase authorization.
- Product index vocabulary gets a new version, requiring explicit atomic rebuild. Keep similarity 0.45, RRF, pre-LIMIT scope and fresh domain checks.
- UI uses existing styling, responsive category grid and original SVGs; no branded images.
- No Provider/Key, remote writes, old database/container operations, new payment/refund rules or historical evaluation rewrites.

## Tasks

- [x] Write and observe failing tests for explicit profile, category validation and trusted cross-category constraints.
- [x] Implement incremental category migration and validated data resource, insert-only expanded seed and explicit demo profile.
- [x] Extend category aliases/index vocabulary, exact filters and second tool-level verification; test A–E, stale index, stock and tenant exclusion.
- [x] Extend catalogue navigation, specification summaries/detail labels and 10 original category illustrations; add unit and browser tests.
- [x] Test real PostgreSQL upgrade, 120-SKU pagination, repeat seed preservation, cart/independent Confirmation, concurrency/idempotency, and existing V2 regression.
- [x] Capture synthetic browser screenshots, update run/profile/rebuild instructions, review diff, clean up only new resources, create one local commit.

## Review focus

Legacy fixture drift; seed overwrite and UUID collision; incompatible cross-category memory; unfiltered vector recall; migrations that silently destroy expanded data; pagination duplicates; implicit order approval.

Implementation review: keyword specificity, revocable screen/activity/subtype memory and managed Legacy launcher were checked and repaired. Final regression/commit identity is recorded in docs/evidence/v25/verification.json; the plan is not an execution receipt.
