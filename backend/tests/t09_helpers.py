from uuid import uuid4

import pytest
from multiagent_helpers import ai, call, choose_purchase, final, install, make_models, route
from sqlalchemy import text


@pytest.fixture
async def durable_env(env):
    from agentmall.agents.persistence import setup_checkpoint

    schema = "cp_" + uuid4().hex
    with env[1].begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    settings = env[3].model_copy(update={"checkpoint_schema": schema})
    env[2].state.settings = settings
    try:
        await setup_checkpoint(settings)
        yield env[0], env[1], env[2], settings
    finally:
        with env[1].begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def purchase_models(env):
    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    return models


async def thread(env, buyer, mode="multi"):
    r = await env[0].post("/api/v1/agent/threads", headers=buyer, json={"mode": mode})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def start(
    env, buyer, tid, request_id=None, message="找一款300元以内静音键盘准备购买，送演示宿舍"
):
    return await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs",
        headers=buyer,
        json={"request_id": request_id or str(uuid4()), "message": message},
    )


async def confirm(env, buyer, pid, decision="approve"):
    r = await env[0].post(
        f"/api/v1/proposals/{pid}/confirmations", headers=buyer, json={"decision": decision}
    )
    assert r.status_code == 201, r.text
    return r.json()["confirmation_id"]


async def resume(env, buyer, tid, run, confirmation_id, request_id=None):
    return await env[0].post(
        f"/api/v1/agent/threads/{tid}/resume",
        headers=buyer,
        json={
            "run_id": run["id"],
            "interrupt_id": run["pending_confirmation"]["interrupt_id"],
            "proposal_id": run["pending_confirmation"]["proposal_id"],
            "confirmation_id": confirmation_id,
            "request_id": request_id or str(uuid4()),
        },
    )


async def two_proposals(env, buyer, product):
    from aftersales_helpers import delivered_order
    from multiagent_helpers import ai, call, choose_purchase, final, install, make_models, route

    order = await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "prepare_return", "return", read_only=False),
            route("shopping", "find_products", "replacement"),
            route("order", "prepare_checkout", "new", depends=["replacement"], read_only=False),
            route("finish"),
        ],
        aftersales=[
            ai(
                call(
                    "check_eligibility", {"order_id": order["id"], "reason_code": "QUALITY_ISSUE"}
                ),
                call("retrieve_policies", {"order_id": order["id"], "query": "质量问题退货期限"}),
            ),
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": order["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "按键故障",
                    },
                )
            ),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    tid = await thread(env, buyer)
    run = (
        await start(
            env,
            buyer,
            tid,
            message=f"订单{order['id']}有质量问题，想退掉。再帮我推荐一款500元以内静音键盘，准备购买，送演示宿舍。",
        )
    ).json()
    return tid, run, order
