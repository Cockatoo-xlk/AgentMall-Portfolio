# V2.7 Catalog Operations Design

The merchant receives a product-management tab inside the existing workbench. CSV/JSON input creates only scoped drafts, never published products. Verified AI suggestions cite exact source spans; absent/ambiguous facts remain unknown. Parser is disabled on ordinary startup, with an explicitly injected offline MockTransport adapter in the existing local demo/test server. No live-key loader is involved.

## Decisions

Reuse the products table and its version, stock invariant, active flag, immutable order snapshots and ProductSearch identity. Append a migration for four small catalog-operation records: import jobs, drafts, command receipts, and index jobs. Draft workflow is DRAFT → READY_FOR_REVIEW → APPROVED → PUBLISHED; rejection/editing requires review again. A published draft is immutable; existing products are edited through a new revision draft bound to expected catalog_version.

Alternatives considered: staging unpublished rows in products would expose drafts to existing readers; a background queue/service exceeds this MVP. Separate drafts plus explicit database-backed index execution preserves existing read semantics and gives a truthful recoverable status without infrastructure.

Every mutation requires merchant and server-derived Store. An actor/store/request UUID receipt binds operation, resource, and body. Row locks and expected versions prevent concurrent overwrites. Publishing increments product version, preserves reserved stock, and refuses on_hand below reserved. Product mutation and index task commit together; an explicit subsequent index action can fail without rolling back a valid merchant operation. Index attempts are bounded at three, idempotent by request ID, and lock product/version; outdated work is STALE. Inactive/stale indices are already excluded by existing Hybrid RAG filters.

MVP input limits: UTF-8 JSON/CSV, 128 KiB content, 50 rows, fixed columns and bounded fields; HTTP JSON envelope is streamed with a 512 KiB bound. No paths, eval, URL fetch or arbitrary execution. Category-specific attribute allowlists preserve synthetic catalog conventions (e.g. ports and string screen_inches). An AI proposal must match deterministic source witnesses before it can enter draft attributes; human editing remains explicit and independently reviewed.

Human approval and publication are separate API/button actions. Listing refresh only reads state, never replays writes. Unknown responses keep their request UUID for explicit reconciliation. No defaults for missing price/stock/category at publication. Only structured text and evidence are retained, no raw model reasoning or credentials.

## Validation

Use a fresh PG17/pgvector and official Checkpointer, Fixture embeddings and MockTransport. Cover input limits/injection/schema errors, evidence rejection, workflow, tenants, repeated import/publication, stock/version races, stale indices, bounded retry, unchanged order snapshots, new product single/Bundle checkout and existing merchant/SSE/evaluation paths. Preserve old migration and frozen data, no live requests or remote operations.
