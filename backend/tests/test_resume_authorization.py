from uuid import uuid4

import pytest
from conftest import row
from sqlalchemy import text
from t09_helpers import confirm, purchase_models, resume, start, thread  # noqa: F401
from t09_helpers import durable_env as durable_env


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("other_user", 404),
        ("wrong_confirmation", 409),
        ("old_interrupt", 409),
        ("expired", 409),
        ("disabled", 401),
        ("store", 404),
        ("mixed", 422),
    ],
)
async def test_resume_requires_current_identity_and_exact_confirmation(
    durable_env, buyer, buyer2, mutation, expected
):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    pending = run["pending_confirmation"]
    cid = await confirm(env, buyer, pending["proposal_id"])
    body = {
        "request_id": str(uuid4()),
        "run_id": run["id"],
        "interrupt_id": pending["interrupt_id"],
        "proposal_id": pending["proposal_id"],
        "confirmation_id": cid,
    }
    headers = buyer
    if mutation == "other_user":
        headers = buyer2
    elif mutation == "wrong_confirmation":
        body["confirmation_id"] = str(uuid4())
    elif mutation == "old_interrupt":
        body["interrupt_id"] = "old"
    elif mutation == "expired":
        with env[1].begin() as c:
            assert c.scalar(text("SELECT current_schema()")) == env[3].db_schema
            c.execute(text("ALTER TABLE action_proposals DISABLE TRIGGER immutable_snapshot"))
            c.execute(
                text(
                    "UPDATE action_proposals SET expires_at=clock_timestamp()-interval '1 second' "
                    "WHERE id=:id"
                ),
                {"id": pending["proposal_id"]},
            )
            c.execute(text("ALTER TABLE action_proposals ENABLE TRIGGER immutable_snapshot"))
    elif mutation == "disabled":
        with env[1].begin() as c:
            c.execute(text("UPDATE users SET disabled=true WHERE login='buyer1'"))
    elif mutation == "store":
        env[2].state.settings = env[3].model_copy(update={"storefront_id": uuid4()})
    elif mutation == "mixed":
        body["clarification"] = "别的需求"
    response = await env[0].post(f"/api/v1/agent/threads/{tid}/resume", headers=headers, json=body)
    assert response.status_code == expected, response.text
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0


async def test_reject_ends_without_order_and_replay_preserves_budget(durable_env, buyer):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"], "reject")
    request_id = str(uuid4())
    done = await resume(env, buyer, tid, run, cid, request_id)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"
    # L3 pauses before the final Supervisor decision, which is charged on resume.
    assert done.json()["budget"]["models"] == run["budget"]["models"] + 1
    replay = await resume(env, buyer, tid, run, cid, request_id)
    assert replay.json() == done.json()
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM action_proposals WHERE status='REJECTED'")["n"] == 1


async def test_clarification_uses_real_interrupt_and_preserves_budget(durable_env, buyer):
    from multiagent_helpers import install, make_models, route

    env = durable_env
    models = make_models(supervisor=[route("clarify"), route("finish")])
    await install(env, models, indexed=False)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid, message="看看商品")).json()
    assert run["pending_confirmation"]["type"] == "clarification"
    response = await env[0].post(
        f"/api/v1/agent/threads/{tid}/resume",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "run_id": run["id"],
            "interrupt_id": run["pending_confirmation"]["interrupt_id"],
            "clarification": "只看300元以内键盘",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED", response.text
    assert response.json()["budget"]["models"] == 2


async def test_each_return_and_purchase_needs_own_confirmation_and_same_action_other_key(
    durable_env, buyer, product
):
    from aftersales_helpers import submit_case
    from t09_helpers import two_proposals

    env = durable_env
    tid, run, order = await two_proposals(env, buyer, product)
    assert run["status"] == "WAITING_INPUT", run
    # The second proposal cannot precede the first independent user decision.
    assert len(run["result"]["proposal_ids"]) == 1, run
    assert run["pending_confirmation"]["action_type"] == "RETURN_REQUEST"
    return_pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, return_pid)
    after = (await resume(env, buyer, tid, run, cid)).json()
    assert after["status"] == "WAITING_INPUT", after
    assert after["pending_confirmation"]["action_type"] == "CHECKOUT"
    assert len(after["result"]["proposal_ids"]) == 2, after
    assert (
        after["pending_confirmation"]["interrupt_id"] != run["pending_confirmation"]["interrupt_id"]
    )
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert (await resume(env, buyer, tid, after, cid)).status_code == 409
    duplicate = await submit_case(
        env[0], buyer, {"proposal_id": return_pid}, {"confirmation_id": cid}, key=str(uuid4())
    )
    assert duplicate.status_code == 200, duplicate.text
    second = await confirm(env, buyer, after["pending_confirmation"]["proposal_id"])
    done = (await resume(env, buyer, tid, after, second)).json()
    assert done["status"] == "COMPLETED", done
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
    assert done["budget"]["models"] == after["budget"]["models"] + 1
    assert after["budget"]["models"] > run["budget"]["models"]


async def test_resume_rechecks_current_price_and_never_auto_refreshes_proposal(durable_env, buyer):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, pid)
    with env[1].begin() as c:
        c.execute(
            text("UPDATE products SET price_cents=price_cents+1,catalog_version=catalog_version+1")
        )
    result = await resume(env, buyer, tid, run, cid)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "PARTIAL"
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1


async def test_expired_unconfirmed_action_advances_to_next_pending_proposal(
    durable_env, buyer, product
):
    from t09_helpers import two_proposals

    env = durable_env
    tid, run, order = await two_proposals(env, buyer, product)
    expired = run["pending_confirmation"]["proposal_id"]
    with env[1].begin() as c:
        c.execute(text("ALTER TABLE action_proposals DISABLE TRIGGER immutable_snapshot"))
        c.execute(
            text(
                "UPDATE action_proposals SET expires_at=clock_timestamp()-interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": expired},
        )
        c.execute(text("ALTER TABLE action_proposals ENABLE TRIGGER immutable_snapshot"))
    original = row(env[1], "SELECT request_payload p FROM agent_runs WHERE id=:id", id=run["id"])[
        "p"
    ]
    refreshed = await env[0].post(f"/api/v1/agent/threads/{tid}/runs", headers=buyer, json=original)
    assert refreshed.status_code == 200, refreshed.text
    next_run = refreshed.json()
    assert next_run["status"] == "WAITING_INPUT", next_run
    assert next_run["pending_confirmation"]["proposal_id"] != expired
    assert "STALE_PROPOSAL" in next_run["result"]["error_codes"]
    cid = await confirm(env, buyer, next_run["pending_confirmation"]["proposal_id"])
    result = await resume(env, buyer, tid, next_run, cid)
    assert result.json()["status"] == "PARTIAL", result.text
    assert result.json()["pending_confirmation"] is None
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2


async def test_confirmation_keeps_deferred_clarification(durable_env, buyer):
    from multiagent_helpers import route

    env = durable_env
    models = await purchase_models(env)
    models["supervisor"].script[-1] = route("clarify")
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    after = await resume(env, buyer, tid, run, cid)
    assert after.json()["status"] == "WAITING_INPUT", after.text
    assert after.json()["pending_confirmation"]["type"] == "clarification"
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
