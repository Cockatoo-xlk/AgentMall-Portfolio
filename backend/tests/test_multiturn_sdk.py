from uuid import uuid4

import pytest
from conftest import row
from multiturn_helpers import install_context_sdk, wireless_products
from t09_helpers import confirm, resume, thread
from t09_helpers import durable_env as durable_env
from test_thread_memory import read, turn


@pytest.mark.parametrize("mode", ["single", "multi"])
async def test_three_turn_sdk_paths_and_independent_confirmation(
    durable_env, buyer, tmp_path, mode
):
    env = durable_env
    await wireless_products(env)
    provider, program = await install_context_sdk(env, tmp_path)
    try:
        tid = await thread(env, buyer, mode)
        first = await turn(env, buyer, tid, "推荐一款300元以内静音键盘", 0)
        assert first.status_code == 201, first.text
        ctx = (await read(env, buyer, tid))["context"]
        assert ctx["candidate_sets"] and ctx["candidate_sets"][0]["valid"]
        second = await turn(env, buyer, tid, "改成无线的，预算提高到400元", ctx["version"])
        assert second.status_code == 201, second.text
        ctx = (await read(env, buyer, tid))["context"]
        candidates = ctx["candidate_sets"][0]
        assert len(candidates["items"]) == 3
        target = candidates["items"][1]["id"]
        third = await turn(
            env,
            buyer,
            tid,
            "就买第二款，一件，送演示宿舍",
            ctx["version"],
            candidate_set_id=candidates["id"],
        )
        assert third.status_code == 201, third.text
        run = third.json()
        assert run["status"] == "WAITING_INPUT", run
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert run["context_snapshot"]["selected"][0]["id"] == target
        pid = run["pending_confirmation"]["proposal_id"]
        proposal = (await env[0].get(f"/api/v1/proposals/{pid}", headers=buyer)).json()
        assert proposal["canonical_payload"]["items"][0]["product_id"] == target
        cid = await confirm(env, buyer, pid)
        request_id = str(uuid4())
        done = await resume(env, buyer, tid, run, cid, request_id)
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "COMPLETED", done.json()
        assert (await resume(env, buyer, tid, run, cid, request_id)).status_code == 200
        assert row(env[1], "SELECT count(*) n FROM orders WHERE status='PENDING_PAYMENT'")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
        # Actual SDK requests receive different canonical budgets and route/execute real tools.
        assert {
            r["content"]
            .get("constraints", r["content"].get("canonical_constraints", {}))
            .get("max_price_cents")
            for r in program.requests
        } >= {30000, 40000}
        assert row(env[1], "SELECT count(*) n FROM agent_candidate_sets")["n"] == 2

        current = (await read(env, buyer, tid))["context"]
        recommendation = await turn(env, buyer, tid, "推荐键盘，不购买", current["version"])
        assert recommendation.status_code == 201, recommendation.text
        assert recommendation.json()["constraints"]["purchase_requested"] is False
        assert recommendation.json()["constraints"]["quantity"] is None
        assert recommendation.json()["constraints"]["address_label"] is None
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
    finally:
        await provider.close()
