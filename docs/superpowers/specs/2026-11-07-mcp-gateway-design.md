# V2.8 MCP Tool Gateway design

Base: 5f197611d6e4cb93a0a39c3882456f196c84551e. Branch: codex/v2-mcp-tool-gateway. User delegates implementation and bounded verification; one final local commit, no remote writes or paid Provider.

## Approach and scope

Use the official pinned MCP Python v2 SDK low-level Server for dynamic role-filtered discovery, Pydantic inputs and structured results. The SDK owns JSON-RPC, per-request 2026-07-28 discovery/metadata, stdio and Streamable HTTP. Direct functions without wire transport would not meet the task; proxying every HTTP endpoint would expose excessive capabilities. The chosen adapter explicitly maps nine tools to existing domain services, with no alternate business SQL or new tables.

Tool surface: search_products, get_product (public); list_my_orders, get_my_order, check_return_eligibility (buyer); get_public_return_policy (public policy, or owned buyer order); list_merchant_catalog, list_merchant_after_sales, create_product_draft (merchant). No approval, publish, checkout, payment, refund, inventory or SQL tools. Merchant draft command reuses V2.7 request_id and cannot carry an owner, approval or status. List responses use bounded stable pagination; output strips unnecessary identity/authorization internals.

## Authentication

Credentials never appear in tool arguments. Stdio explicitly loads only AGENTMALL_MCP_TOKEN (optional, public otherwise) and validates through existing authenticate on every message. HTTP gets an optional Bearer credential from the actual request, rejects invalid credentials instead of downgrading to public, and never trusts user/role/Store in model input. Discovery is filtered as well as call execution; reauthentication checks expiration/disabled users and Store changes. HTTP is a separate explicit entry on literal127.0.0.1, with Host/Origin/peer checks, no proxy header trust, no CORS, bounded bodies and no token URLs. It is local custom bearer auth, not OAuth: REMOTE_AUTH_NOT_IMPLEMENTED. Ordinary FastAPI startup gains no automatic public MCP mount.

## Transactions and limits

Readonly tools use short domain-service transactions; create_product_draft delegates to the existing V2.7 transactional command service and returns a minimal receipt for the preserved DRAFT. A cancelled or lost write has UNKNOWN outcome, retry only with the same request_id; never auto-retry. Calls have a fixed wall-time bound, concurrent execution cap, finite JSON input/output bytes and finite page limits. Exceptions return allowlisted structured codes/messages; no raw argument, exception, token, DSN or Checkpoint is logged or returned. Cancellation propagates and rolls back in-flight transactions; committed commands retain the original receipt.

## Compatibility and evidence

Validate official SDK package and actual supported versions before claiming compatibility. Test 2026-07-28 stateless request flow over real stdio subprocess and localhost HTTP using official Client, not just in-memory calls. Test any offered legacy fallback explicitly or label NOT_TESTED. Independent clients must obtain facts from a fresh PostgreSQL/Expanded catalog and compare to original FastAPI results. No real LLM is needed for MCP; existing MockTransport/Fixture regressions remain separately identified. No LangGraph or commerce rewrite.

## Verification and isolation

Fresh owned PG17/pgvector and test schemas; existing local trusted dependency cache, no historical resources modified. RED before implementation, new MCP protocol/auth/schema/error/cancellation/idempotency tests, relevant catalog/Bundle/merchant regression, Vitest and selected Playwright. One fresh read-only whole-branch reviewer at the end. Private logs0600 under a new ignored directory; publish only reviewed synthetic summaries. No 900-second admission, encryption pipeline or remote CI.
