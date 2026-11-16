# V2.17 interview-ready implementation plan

**Goal:** Deliver a reproducible interview portfolio from verified V2.16, with a truthful edited demo and separately frozen exploratory Live proposal.

**Architecture:** Preserve the existing product/Agent/Domain API architecture. Add one continuous browser regression and a small static smoke-plan validator, not another Runner or evaluation platform. Reuse formal API operator, Ledger, RunEvent, Checkpoint and independent SQL assertions. Media is an edit of retained real offline footage plus explicitly sourced evidence cards.

**Tech stack:** FastAPI, SQLAlchemy/PostgreSQL17/pgvector, LangChain/LangGraph, React/TypeScript/Playwright; optional local ffmpeg/Pillow tooling for media only.

**Spec:** Owner's AGENTMALL_V217_INTERVIEW_READY_MILESTONE in this task. The detailed request authorizes local implementation and asks for independent approval only for fees, GitHub writes or new security permissions. No additional design-approval gate is introduced.

## Decisions and scope

- Use the existing isolated checkout on a new local branch from exact `8e21bdcad3170487626a17ccda0f624457bccd26` after main Run43783548437 succeeds. Keep all other branch references and original private evidence unchanged.
- Product UI already implements three requested flows. Verify their continuous use before adding product changes; do not invent new features or weaken transactions.
- Tests run on an allowlisted source copy and new owned containers/volumes with no external network. Old `.env*`, history, L8 data and private Host packages are excluded from Guest mounts.
- Edit a silent, captioned 3–5 minute MP4. Preserve source WebM, recorder exit1 and original SQL facts. Evidence cards are explanatory projections, explicitly distinct from recorded application screens.
- New smoke is EXPLORATORY_PRODUCT_SMOKE, never Holdout or production certification. No execution verb/key loader is added to the static validator. Freeze actual final Commit and contract hashes in a separate local binding receipt to avoid a self-referential Git SHA.

## File responsibilities

- `frontend/tests/interview-demo.spec.ts`: one continuous A/B/C formal API + UI + SQL regression, explicit synthetic approvals, refresh/idempotence and two distinct Multi confirmations.
- `evals/product_smoke.py`, `backend/tests/test_v217_smoke_contract.py`: validate/freeze a small product-specific proposal, reject drift/budget escalation/unknown source and independent-Holdout claims; never invoke a model.
- `evals/proposals/v217-product-smoke.json`, `docs/V217_LIVE_SMOKE.md`: new ordered inputs, fixture recipes, executable SQL/API assertions, operator/stop/export rules and future authorization scope.
- `scripts/render_interview_video.py`, `docs/media/v217/`: deterministic edit list, MP4, script/subtitles/source hashes; optional media dependencies stay outside product locks.
- README and existing Architecture/Demo/Engineering/Interview/Evaluation/Limitations pages: current state and source-grounded explanations; historical L8 numbers/evidence remain intact. New `docs/RESUME_PROJECT.md` provides honest interview wording.
- `docs/evidence/v217/verification.json`, `docs/V217_INTERVIEW_READY.md`: sanitized final results. Full logs/SQL/media probes/resource identities remain private and hashed.

## Execution checklist (one milestone)

- [x] Independently read exact main Run, Jobs and logs; verify parents/tree and expected T16 skip.
- [x] Write smoke contract failing tests; implement smallest static validator and verify.
- [x] Add/run continuous A/B/C browser path in a fresh owned environment; preserve all intermediate failures.
- [x] Edit and decode-check MP4; inspect representative frames, captions, chapters and sensitive content.
- [x] Complete documentation/12 interview answers/resume and freeze smoke inputs without running them.
- [x] Run full Backend, BGE, Vitest, Playwright, Ruff/format/typecheck/lint/build on final runtime source.
- [x] Fresh read-only whole-branch review; resolve substantive findings, audit links/privacy/diff and owned-resource cleanup.
- [x] Prepare final local commit only; actual SHA/parent/tree/CLEAN and post-commit binding are established in the external final receipt, never preclaimed here.

## Review focus

1. Old WebM/SQL evidence must never be presented as a V2.17 Live result or freshly captured screen.
2. A known business result must survive refresh and repeated same-request Resume without an extra transaction.
3. Full-context cost reservations can stop before HTTP12; no document promises all12 requests for CNY2.50.
4. Smoke identity must bind final source and all task/fixture/assertion bytes; source alias/model alias cannot prove immutable weights.
5. No new helper may read credentials, auto-approve, Resume, Recover, dispatch or silently upgrade evidence labels.

## Global boundaries

Local work only; no Push/PR/Merge/Tag/Release/Deploy/Dispatch/Rerun. Real Provider requests0, Key reads0, costs0. L8 PASS1/FAIL4/NOT_SCORED3/NOT_RUN7, 08 UNKNOWN, E1_ORACLE_CONTRACT_MISMATCH, Independent Holdout0. Release ON_HOLD. Future smoke caps: HTTP12/models12/tools16/delegations4/steps24, input3145728/output12000, Episode90s/Outer300s, CNY2.50/task and CNY7.50/batch; Live authorization0.
