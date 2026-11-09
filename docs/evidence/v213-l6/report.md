# V2.13-L6 — Budget-constrained Multi-Agent optimization

Evidence class: **OFFLINE official SDK MockTransport / Fixture Model + Fixture Embedding + real isolated PostgreSQL 17/pgvector**. Decisions in tests are **TEST_OPERATOR**. Real DeepSeek retest, hosted embedding, real payments and remote CI: **NOT_RUN**. Provider requests and Provider Key reads in this task: **0**.

## Source and boundaries

- Parent: `d32d25b25db8d5464fb561b1ef1482598ae31b1c`.
- Branch: `codex/v213-l6-model-budget-optimization`.
- The commit containing this report is the L6 candidate: `git log -1 --format=%H -- docs/evidence/v213-l6/report.md`.
- Original limits remain **12 model calls, 16 tools, 4 delegations, 24 business steps, 12,000 output tokens and 90 seconds per Run**. Inner SDK recursion protection remains 36. No extra free model calls, graph nodes or repair allowance.
- No changes to domain services, order/inventory/payment/refund transactions, Confirmation contracts, durable graph, database schemas, dependency locks, frozen datasets or Oracles.
- Original L1/L3/L5 private records are retained; 26 original file hashes are checked independently. No raw private model output is committed here.

## What L5 actually establishes

The preserved L5 receipts show **PARTIAL / BUDGET_EXCEEDED**, 12 settled Provider requests, 10 tools and 4 delegations. Usage is 32,109 input / 3,188 output tokens; ¥0.089722 is a peak-price estimate, not a billing receipt. One return Confirmation executed, while checkout never reached its separate Confirmation. Findings establish zero unauthorized database writes; the legacy missing-decision diagnostic is not an unauthorized-write count.

The diagnostic contains 91 complete events (no truncation). Its original SHA-256 is `071675b428c78da8b20a9681b591b80f7017761cc503b3690d6d8546b07b841b`. It supports the following call sequence; it does not supply invented missing model responses.

| L5 call | Role | Observed work | Necessary decision / optimization |
|---:|---|---|---|
| 1 | Supervisor | Dispatch `assess_return` | Model planning retained |
| 2 | AfterSales | `get_order` + `retrieve_policies` | Independent reads may batch; domain reads retained |
| 3 | AfterSales | `check_eligibility` | Deterministic domain eligibility retained |
| 4 | AfterSales | Natural-language assessment ending | Complete same-order server receipts can end readonly task |
| 5 | Supervisor | Dispatch `prepare_return` | Separate writable task retained |
| 6 | AfterSales | Repeat `get_order` + `check_eligibility` | Reuse assessment evidence in model context; authoritative fresh domain rechecks remain |
| 7 | AfterSales | `prepare_return` | Model selects tool; independent return HITL follows |
| 8 | Supervisor | Dispatch `find_products` | Only after return execution |
| 9 | Shopping | `retrieve_products` | Real database-backed candidates |
| 10 | Shopping | Natural-language recommendation ending | Validated nonempty product receipts can end this simple readonly task |
| 11 | Supervisor | Dispatch `prepare_checkout` | Model planning retained |
| 12 | Order | Three `get_product` calls in **one batch** | Choosing one verified candidate saves two tools, **not two model calls** |
| NOT_RUN | Order / Supervisor | Prepare checkout / final finish | At least two further model rounds under those retained choices; counterfactual, not observed L5 output |

No repeated Supervisor dispatch is established in L5. Four delegations have distinct semantics and remain separate. Keeping the observed decisions would require at least 14 model calls to finish; that counterfactual explains the bottleneck without treating the final count alone as proof.

## Implementation

1. `assessment_receipt()` centralizes the existing same-order order/eligibility/public-policy proof. A typed negative eligibility may finish a readonly assessment, but **never sets `ready=true`**. Missing reads, errors or mismatched policy cannot finish it; a model final without required return-assessment receipts is blocked.
2. `read_completion.py` ends only fulfilled Multi readonly `assess_return` and non-Bundle `find_products`. It uses actual committed tool receipts, validated ProductDTOs and canonical constraints; empty/error/incomplete reads continue normally. Single and Bundle retain their existing model loop. Completed readonly goals are deduplicated within the Run even if the model renames the task.
3. The SDK's existing tools-to-model `return_direct` edge is scoped to fresh per-Handoff tool instances. Its END destination is declared at graph compilation, then the Guard disarms every scoped read tool **before any validated batch executes**. Only complete receipts re-arm it. The SDK dispatches tool calls as parallel Send branches: each wrapper awaits the whole batch before returning, so a fast sibling cannot route to an extra model call or finish prematurely. Cancellation propagates without detached tasks. No synthetic AIMessage, fake tool result or new graph node is introduced.
4. AfterSales instructions expose `verified_assessments` as proof for a model-selected `prepare_return`. `assessment_for()` and `revalidate_return()` still enforce dependencies, exact order and reason, owned-order lock, current version/eligibility, expiry, duplicate checks and original domain preparation. Python does not select or execute a write on the model's behalf.
5. Order receives at most three role-scoped verified candidate snapshots, with retrieval rank/score/source where known; absent metadata remains `null`. Every snapshot explicitly says `is_current_quote=false`. The model chooses a suitable candidate; no first-ranked SKU is forced. It normally reads that selected product and makes a later model call for checkout. Existing domain checks reread current product, version, price, stock, quantity, address and explicit intent.
6. `read_goal_completed` diagnostics expose only allowlisted role/goal/tool identifiers, receipt basis and a boolean indicating a skipped ending round. Existing model/tool/budget/HITL events remain. No prompt, raw arguments, credentials or chain of thought is added to public diagnostics.

The abandoned implementation used a `before_model` node. A deliberately unfulfilled read-loop regression showed that its extra graph hop reached recursion protection before the fixed model budget. That approach was removed; no limit was raised. Two intermediate attempts at the existing END edge exposed the missing compile-time END map and per-tool Send timing, respectively. All failure logs remain private.

## Measured call paths

| Step | Optimized (11) | Batched (10) |
|---:|---|---|
| 1 | Supervisor → assessment | Supervisor → assessment |
| 2 | AfterSales order + policy | AfterSales order + eligibility + policy |
| 3 | AfterSales eligibility | Supervisor → return preparation |
| 4 | Supervisor → return preparation | AfterSales prepare return → HITL 1 |
| 5 | AfterSales prepare return → HITL 1 | Supervisor → shopping |
| 6 | Supervisor → shopping | Shopping retrieval |
| 7 | Shopping retrieval | Supervisor → checkout |
| 8 | Supervisor → checkout | Order read selected product |
| 9 | Order read selected product | Order prepare checkout → HITL 2 |
| 10 | Order prepare checkout → HITL 2 | Supervisor finish |
| 11 | Supervisor finish | — |

Relative to the counterfactual 14-call completion: remove one assessment ending, one duplicate-read model round and one Shopping ending → 11; independently batching the assessment reads → 10. Reducing Order reads from three to one reduces tools only. These savings are from controlled synthetic programs and receipt gating; they are **not a promise of real-model behavior**.

## Business acceptance and independent SQL evidence

The SDK tests use a separate physical synchronous PostgreSQL connection in **REPEATABLE READ READ ONLY**, independent of the async API/domain connection. Before, checkout-waiting and final snapshots cover orders/items, Cases, proposals, Confirmations, products, payments and idempotency receipts. Raw JSON snapshots and SHA remain private.

Both normal profiles assert:

- No Case before return approval; no new order before checkout approval.
- Two distinct proposal-bound decisions; reusing the return decision for checkout returns 409.
- Exactly one new REQUESTED Case and one new PENDING_PAYMENT order; payments delta **0** (the synthetic delivered original has its own existing payment).
- Replacement SKU differs from the original, quantity is one, total equals current item price and is at most 50,000 cents. The model selects from authenticated candidates; a non-observed SKU is refused.
- Only the selected SKU's `reserved` increases by one; all other reservations and all `on_hand` values are unchanged.
- Replaying both original Resume requests returns the persisted final receipt with no additional Case, order, decision, model call or stock reservation.
- Price/version change, shortage, delisting, expired eligibility and insufficient budget fail closed; a committed return Case survives later purchase failure.

### A–P coverage

| Requirement | Evidence |
|---|---|
| A | Synthetic observed-shape SDK ablation reaches 12 models / 10 tools / PARTIAL, with Case 1 and no new checkout; it is not reconstructed private model prose |
| B–C | Full and batched reads, missing eligibility/policy, public-policy/version/error negatives, bounded batch barrier |
| D–E | One model-selected return write; domain revalidation call-count and actual expiry/version/policy mutation tests |
| F–H | Bounded role-scoped candidates; unobserved SKU and current price/stock/delist refusal; real domain purchase checks |
| I–L | Two independent decisions, incorrect decision 409, Case/order/stock SQL snapshots and replay assertions |
| M–N | 11/10-call complete paths at default cap12; caps4/5 and deliberately unfulfilled default12 exhaust safely |
| O | Existing malformed/hidden-write/authority batch rejection and permission/Store isolation suites |
| P | Full Single, Bundle/Replanning, Copilot, MCP, Worker, API and browser regressions |

Synthetic drivers were explicitly migrated to task-aware queues/endings where eliminated model-final rounds no longer occur. The budget-exhaustion Fixture now deliberately queries an empty price range so that it still tests an **unfulfilled** loop, rather than a fulfilled readonly task. Frozen inputs, Oracle answers, original skip/retry policy and safety assertions are unchanged. Call-index/count assertions were updated to the new measured paths.

## Verification and retained failures


| Final check | Result | Raw log SHA-256 |
|---|---|---|
| Final complete pytest | 1220 passed / 14 existing offline-core skips | `402e7adfa8edcaf5bed077aedc3c4168122a931d52a62ebbebac3eeb1d0a07c7` |
| Final Python static checks | Ruff and format: PASS | `9413d7c4ade5ce98aa38287b13a606b2513fc6bae3cdd63f46511926166eb12e` |
| Full frontend checks | TypeScript, ESLint, 127 Vitest and production build: PASS | `d8dd256239f59b567a6c42488b0dff46d6ae5c5cdfc08431fd2cd54ac3f26867` |
| Full Playwright | 119 passed / 0 retries / 0 flaky | `7e7e4e27f32f276f997e17041dff6e5ddb9ea3d9d73603ad0b092764c9e87d9c` |
| Final targeted safety/migration checks | 36 passed | `d94768c29999f0f1f48be4c1b8e8e555dbc2f0233b2da294a4784e3ca9c1c867` |

The final pytest run used unchanged source/test bytes throughout. The 14 existing skips are 13 real-BGE checks without weights in this Fixture runner plus one raw-private-Live-evidence test (originals are deliberately not mounted); synthetic regressions still run. No skip, retry or Oracle answer was added or weakened. The final two test-only migrations were included in this complete run.

| SDK profile | Models | Tools | Delegations | Steps | Simulated output tokens | Independent SQL snapshot SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| optimized | 11 | 7 | 4 | 20 | 330 | `78bcba41f80e792934c297a457dc79187961cdf661a1e0181b36d2fe256d8feb` |
| batched | 10 | 7 | 4 | 20 | 300 | `db00327191236e849d46d201fb3da5a397f125d201b7b094ac277684b3ee7767` |

The final SQL exports additionally verify every stored proposal payload hash, both consumed decisions and their exact Case/order `result_ref` bindings. Per profile, orders **1→2**, Cases **0→1**, confirmations **2→4**, payments **1→1**, idempotency receipts **4→8**. Resume replay produces no further deltas. Raw snapshots are extracted from the final JUnit evidence, not fabricated from expected values.

After sealing the SQL snapshots, the exclusively owned PostgreSQL container, data Volume, runner image tag and temporary Jieba cache were removed; independent Docker lookups find none. No leftover test/Checkpoint schemas remained before removal. All **25** historical containers retain their original IDs and states; default Docker Context remains `colima`. Cleanup receipt SHA-256: `5a53ac9fab7e51503ac89c73e0cb455b908d4876434d41579c8b7b4071ec7093`. One resource-stat command used an unsupported option and exited125; no measurement was accepted from it and its discarded stderr is UNKNOWN. A later successful snapshot (not a peak) is retained.

Candidate file-map fingerprint: `704a5d5b5b9eddac529acbc3ffce86f5b1996fe4c596a721ca778c6fb15d8287` over **736** tracked/proposed files excluding this new report. It is SHA256 of the sorted path→file-SHA256 JSON map encoded with `sort_keys=True, separators=(",", ":")`. The exact map is private; it can be regenerated from the committed tree with this report excluded.

Intermediate failures are not passing receipts:

- Baseline RED: missing candidate metadata / extra model rounds, and repeated completed readonly delegation.
- Missing eligibility/policy initially accepted as a model-final result: fixed with server receipt gating; negative assertions retained.
- Synthetic flat scripts required explicit task-aware migration; their old final messages cannot spill into another writable task.
- Added before-model graph hop failed the unchanged recursion test: abandoned.
- Missing compiled END destination, followed by unsynchronized parallel Send routing, failed targeted SDK tests: corrected, then 22 SDK tests passed.
- Minimal guard-only test doubles lacked the new scoped-tools field: their context construction was brought into line with real ToolContext; permission assertions retained.
- Preliminary Ruff found a duplicate import and a long SQL literal; both corrected without behavioral changes.
- First complete pytest: **1217 passed / 2 failed / 14 skipped**. The checkpoint counter still expected the removed model ending, and a product-injection mock placed its attack after that ending. The checkpoint now asserts the exact persisted/API counter (4); the injection test covers both the normal early stop and an explicit negative-control ablation that makes the attack reachable, retaining the original rejection/no-write assertions. A misplaced test import caused one collection failure and was corrected; its exit2 log is retained. No production code changed after the reviewed candidate.

Private task directory: `.playground/v213-l6-20261109T113259Z/`. It retains original hash protection, raw logs, exit/UTC/SHA receipts, JUnit with independent SQL snapshots, test failures and cleanup evidence. No private evidence is tracked.

## Remaining real-model risk / next authorization

This local Linux aarch64 regression establishes offline feasibility and safety, not a DeepSeek success rate or Ubuntu amd64 remote CI result. A real model can still choose redundant reads, omit dependencies, emit invalid batches, spend its one repair, choose an unsuitable candidate or exhaust the unchanged 90-second/12-call limits. The pinned SDK's return-direct/parallel routing behavior is regression-tested; upgrading that SDK requires rerunning these tests. A nonblocking review gap remains: the test cancels the whole read batch, not one independently cancelled sibling. Such a sibling can leave the remaining reads waiting until the unchanged enclosing Run deadline; current tools expose no independent cancellation API. This is not evidence of immediate cancellation for that untested case.

A subsequent B2-only real-model test needs a newly frozen source/commit, fresh owned database/session, explicit model identity and current official price snapshot, a persistent cumulative ledger and separate owner approval. Suggested first experiment: **one Multi B2 episode, at most 12 Provider requests, original 16/4/24/12000/90 caps**, two independent TEST_OPERATOR decisions in the isolated simulator, and a separately approved cost cap with worst-case reservation. No price, approved policy, Key access or execution authorization is created by this report. UNKNOWN responses retain reservations and stop; no automatic resend. Compare all new failures as well as successes with L5. Repeated reliability experiments require separately declared repetitions and cumulative budget.

## Changed files

- `backend/src/agentmall/agents/model_control.py`
- `backend/src/agentmall/agents/read_completion.py`
- `backend/src/agentmall/agents/return_handoff.py`
- `backend/src/agentmall/agents/runtime.py`
- `backend/src/agentmall/agents/specialist_tools.py`
- `backend/src/agentmall/agents/specialists/aftersales.py`
- `backend/src/agentmall/agents/specialists/order.py`
- `backend/src/agentmall/agents/specialists/runner.py`
- `backend/src/agentmall/agents/specialists/shopping.py`
- `backend/src/agentmall/infra/observability.py`
- `backend/tests/multiagent_helpers.py`
- `backend/tests/playground_helpers.py`
- `backend/tests/test_agent_write_sequencing.py`
- `backend/tests/test_checkpoint_state.py`
- `backend/tests/test_handoff_constraint_continuation.py`
- `backend/tests/test_multiagent_integration.py`
- `backend/tests/test_multiagent_sdk.py`
- `backend/tests/test_prompt_injection.py`
- `backend/tests/test_v213_l2_batch.py`
- `backend/tests/test_v213_l2_delegation.py`
- `backend/tests/test_v213_l2_sdk.py`
- `backend/tests/test_v213_l4_business.py`
- `backend/tests/test_v213_l6_budget.py`
- `backend/tests/test_v213_l6_completion.py`
- `backend/tests/test_v213_reliability.py`
- `docs/evidence/v213-l6/report.md`
- `evals/fixture_model.py`
