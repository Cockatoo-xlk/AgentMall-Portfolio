from uuid import uuid4

from conftest import row
from t09_helpers import confirm, purchase_models, resume, start, thread  # noqa: F401
from t09_helpers import durable_env as durable_env


async def test_durable_purchase_waits_and_authenticated_resume_commits_once(durable_env, buyer):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    request_id = str(uuid4())
    response = await start(env, buyer, tid, request_id)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "WAITING_INPUT"
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    repeated = await start(env, buyer, tid, request_id)
    assert repeated.status_code == 200
    assert repeated.json()["id"] == run["id"]
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    resume_id = str(uuid4())
    done = await resume(env, buyer, tid, run, cid, resume_id)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"
    again = await resume(env, buyer, tid, run, cid, resume_id)
    assert again.status_code == 200, again.text
    assert again.json()["result"]["proposal_ids"] == done.json()["result"]["proposal_ids"]
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 1
    fetched = await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)
    assert fetched.json()["runs"][0]["id"] == run["id"]
    events = await env[0].get(
        f"/api/v1/agent/runs/{run['id']}/events?after_seq=0&limit=2", headers=buyer
    )
    assert events.status_code == 200
    assert len(events.json()["items"]) == 2
    assert [e["seq"] for e in events.json()["items"]] == [1, 2]


async def test_thread_and_run_owner_scope_and_digest_conflict(durable_env, buyer, buyer2):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    assert (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer2)).status_code == 404
    assert (await start(env, buyer2, tid)).status_code == 404
    request_id = str(uuid4())
    run = (await start(env, buyer, tid, request_id)).json()
    assert (await start(env, buyer, tid, request_id, message="不同需求")).status_code == 409
    assert (await start(env, buyer, tid)).status_code == 409
    assert (
        await env[0].get(f"/api/v1/agent/runs/{run['id']}/events", headers=buyer2)
    ).status_code == 404


async def test_persisted_goal_redacts_secrets_and_events_are_incremental(durable_env, buyer):
    from multiagent_helpers import install, make_models, route

    env = durable_env
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    tid = await thread(env, buyer)
    run = (
        await start(
            env,
            buyer,
            tid,
            message="看看商品，password=hunter-secret；api_key=sk-test-secret；地址：真实街道",
        )
    ).json()
    stored = row(
        env[1], "SELECT request_payload::text p,node_journal::text j,result::text r FROM agent_runs"
    )
    for value in stored.values():
        assert (
            "hunter-secret" not in value
            and "sk-test-secret" not in value
            and "真实街道" not in value
        )
    cursor = 0
    seqs = []
    while True:
        response = await env[0].get(
            f"/api/v1/agent/runs/{run['id']}/events?after_seq={cursor}&limit=2", headers=buyer
        )
        body = response.json()
        if not body["items"]:
            break
        seqs.extend(x["seq"] for x in body["items"])
        cursor = body["next_seq"]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_terminal_partial_run_does_not_permanently_block_thread(durable_env, buyer):
    from multiagent_helpers import install, make_models, route

    env = durable_env
    models = make_models(
        supervisor=[route("shopping", "find_products", "shop"), route("finish"), route("finish")],
        shopping=[RuntimeError("fixture failure")],
    )
    await install(env, models, indexed=False)
    tid = await thread(env, buyer)
    first = (await start(env, buyer, tid)).json()
    assert first["status"] == "PARTIAL"
    second = await start(env, buyer, tid)
    assert second.status_code == 201, second.text


async def test_disabled_durable_model_is_never_labeled_fixture(durable_env, buyer):
    env = durable_env
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    assert run["last_error"] == "MODEL_DISABLED"
    assert run["result"]["execution_mode"] == "DISABLED"


async def test_safe_demo_address_survives_goal_redaction(durable_env, buyer):
    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (
        await start(env, buyer, tid, message="找一款300元以内静音键盘准备购买，地址：演示宿舍")
    ).json()
    assert run["status"] == "WAITING_INPUT", run
    assert len(run["result"]["proposal_ids"]) == 1
