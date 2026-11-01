# T15-A Live Playground implementation plan

> Execute inline, test first. Reuse the durable graph, domain tools, existing confirmation/payment/cart and Checkpoint/Epoch kernel. No paid requests or history changes.

Goal: connect actual ChatDeepSeek SDK instances to the persistent Single/Multi workspace under an explicit local-only entry, with separately approved, reserve-before-send persistent global budgets and server-authenticated mode/usage evidence.

Architecture: agentmall/playground/{policy,ledger,provider,runtime,cli}. Normal app stays disabled. New factory requires enable+fresh policy+source-hash-bound independent local approval before reading Key. MockTransport injection is always tagged MOCK_TRANSPORT, never Live. Ledger stores only safe per-call metadata, not messages. File locks/fsync make reservations durable before wire send; caps cover calls/input/output/cost/wall. UNKNOWN/provider/protocol errors halt the ledger. Scope by authenticated Run/node/role/ordinal rejects paid node replay after a missing checkpoint; no automatic retry or budget reset.

Routes/UI: authenticated GET /agent/runtime optionally by owned Run returns model mode and safe owner-scoped counters/usage/upper cost vs actual billing UNKNOWN. Existing workspace adds provider panel; timeline/HITL/payment/cart remain original APIs. No new approval/payment tools.

Isolation: new worktree from c06c584. Test project agentmall-t15-a-tests, host55440/8016/5186, internal guarded PG55433; own .t15-a/PGDATA. Future Live project agentmall-playground-local uses55441/8017/5187 and .playground/PGDATA. No old containers, schemas, ledgers or manifests modified. Mac browser + container FastAPI/PG avoids known2GiB VM browser OOM. No Live environment/approval/ledger created by this turn.

1. Preserve protected file hashes/heads/config and existing container identities; inspect SDK/graph boundaries and current official model/prices. Tests first for policy/authorization rejection before key access, reserve/settle/UNKNOWN/restart/concurrent/replay/owner isolation and real SDK MockTransport wire validation.
2. Implement minimal provider boundary and durable-scope wrapper in run_service; expose trusted runtime status. Test real PG/Checkpoint Multi route and two different natural-language paths, independent proposals/confirmations, malicious tools and ambiguous failures. Do not use Fake ChatModel as SDK evidence.
3. Add workspace runtime/usage panel, fixture/server identity; test units/E2E using explicitly tagged SDK MockTransport on real FastAPI/PG/Checkpoint. Keep original fixture regression modes, default configuration and existing assertions.
4. Provide explicit localhost startup/provisioning, private example config, and separately gated first Live Smoke plan. No authorization receipt generated, no Key read or real model requests. Source/pricing hashes and limits must be approved later.
5. Run targeted plus full offline backend/ruff, frontend static/units and all browser scenarios in bounded separate phases. Preserve every failure, new counts separately, no new skip/retry. Check protections, clean only own test resources, commit locally and stop.

Risk checks: no scope => no send; provider error text never escapes; complete wire Usage required; unknown never releases reservations; no response-body/checkpoint/prompt in public metadata; approval does not come from browser or historical eval; all Live SDK clients have max_retries0, fixed HTTPS endpoint, no redirects/proxy/telemetry; actor/store never model arguments. Optional policy search requires verified local BGE files, never silently Fixture embedding in Live.
