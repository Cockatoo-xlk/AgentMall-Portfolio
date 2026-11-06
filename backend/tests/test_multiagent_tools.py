import pytest
from multiagent_helpers import ai, call, final, install, make_models, route, send
from sqlalchemy import text


@pytest.mark.parametrize(
    "role,goal,name,args",
    [
        ("shopping", "find_products", "execute_confirmed_action", {}),
        ("shopping", "find_products", "prepare_return", {}),
        ("aftersales", "assess_return", "prepare_checkout", {}),
        ("order", "inspect_orders", "confirm_proposal", {}),
        ("order", "inspect_orders", "list_orders", {"actor_id": "someone", "role": "merchant"}),
        (
            "order",
            "inspect_orders",
            "prepare_checkout",
            {"product_id": "00000000-0000-0000-0000-000000000001", "approved": True},
        ),
    ],
)
async def test_specialist_whitelist_rejects_entire_batch_before_domain(
    env, buyer, role, goal, name, args
):
    models = make_models(
        supervisor=[route(role, goal, "task"), route("finish")], **{role: [ai(call(name, args))]}
    )
    trace = await install(env, models)
    result = await send(env, buyer)
    assert "INVALID_TOOL_BATCH" in result["error_codes"]
    assert not any(e["kind"] == "tool" for e in trace["events"])
    with env[1].connect() as c:
        for table in ("orders", "refunds", "confirmations", "action_proposals"):
            assert c.scalar(text(f"SELECT count(*) FROM {table}")) == 0


async def test_cross_user_order_denied_from_real_domain(env, buyer, buyer2, product):
    from lifecycle_helpers import create_order

    order = await create_order(env[0], buyer, product)
    models = make_models(
        supervisor=[route("order", "inspect_orders", "foreign"), route("finish")],
        order=[ai(call("get_order", {"order_id": order["id"]})), final("对方订单已付款")],
    )
    await install(env, models)
    result = await send(env, buyer2, message="查询订单")
    assert "NOT_FOUND" in result["error_codes"]
    assert result["facts"] == [] and result["entity_refs"] == []
    assert "对方订单已付款" not in result["answer"]


async def test_actor_disabled_between_model_and_tool_rechecked(env, buyer):
    def revoke(messages):
        with env[1].begin() as c:
            c.execute(text("UPDATE users SET disabled=true WHERE login='buyer1'"))
        return ai(call("list_orders"))

    models = make_models(
        supervisor=[route("order", "inspect_orders", "orders"), route("finish")],
        order=[revoke, final()],
    )
    trace = await install(env, models)
    result = await send(env, buyer, message="查询订单")
    assert "AUTHORIZATION_CHANGED" in result["error_codes"]
    assert result["facts"] == [] and result["entity_refs"] == []
    assert any(e.get("error_code") == "UNAUTHORIZED" for e in trace["events"])


async def test_get_cart_does_not_create_business_row(env, buyer):
    models = make_models(
        supervisor=[route("order", "inspect_orders", "cart"), route("finish")],
        order=[ai(call("get_cart")), final()],
    )
    await install(env, models)
    result = await send(env, buyer, message="看看购物车")
    assert result["error_codes"] == []
    assert any(f["kind"] == "cart" and f["data"]["items"] == [] for f in result["facts"])
    assert result["status"] == "done"
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM carts")) == 0


async def test_cross_store_product_rejected(env, buyer, product):
    from uuid import uuid4

    with env[1].begin() as c:
        c.execute(
            text("UPDATE products SET store_id=:store WHERE id=:id"),
            {"store": uuid4(), "id": product},
        )
    models = make_models(
        supervisor=[route("shopping", "find_products"), route("finish")],
        shopping=[ai(call("get_product", {"product_id": product})), final()],
    )
    await install(env, models)
    result = await send(env, buyer)
    assert "NOT_FOUND" in result["error_codes"]
    assert result["facts"] == []


@pytest.mark.parametrize(
    "message",
    [
        "推荐一款静音键盘",
        "推荐一款静音键盘，送演示宿舍，不要准备购买",
        "推荐一款静音键盘准备购买",
    ],
)
async def test_missing_or_negative_purchase_intent_cannot_prepare(env, buyer, message):
    from multiagent_helpers import choose_purchase

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
    result = await send(env, buyer, message=message)
    if message.endswith("准备购买") and "不要" not in message:
        assert result["status"] == "needs_input"
    else:
        assert result["status"] == "done"
    assert result["error_codes"] == []
    assert not models["order"].seen
    with env[1].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM action_proposals")) == 0


async def test_original_database_rejected_before_model_request(env, buyer):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    # No connection to 55432 is made: the scope guard precedes session acquisition.
    engine = create_async_engine(env[2].state.engine.url.set(port=55432))
    from uuid import uuid4

    from retrieval_helpers import actor

    from agentmall.agents.graph import run_graph

    models = make_models(supervisor=[route("finish")])
    await install(env, models, indexed=False)
    try:
        thread = uuid4()
        result = await run_graph(
            actor(env[3]),
            thread,
            {"request_id": uuid4(), "thread_id": thread, "message": "找键盘"},
            sessions=async_sessionmaker(engine),
            settings=env[3],
            models=models,
        )
        assert result.error_codes == ["DATABASE_SCOPE_MISMATCH"]
        assert not models["supervisor"].seen
    finally:
        await engine.dispose()
