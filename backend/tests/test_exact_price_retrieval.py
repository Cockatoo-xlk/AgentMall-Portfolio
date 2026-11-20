"""Trusted product requirements qualify rows before ordinary page and recall limits."""

from uuid import UUID, uuid4, uuid5

import pytest
from multiagent_helpers import ai, call, final, last_result
from pydantic import ValidationError
from retrieval_helpers import FixtureEncoder
from sqlalchemy import text
from t09_helpers import durable_env as durable_env
from t09_helpers import start, thread
from test_agent_tools import install as install_legacy
from test_agent_tools import send as send_legacy
from test_baseline_fairness import SingleModel

from agentmall.agents.schemas import SearchInput as LegacySearchInput
from agentmall.agents.specialist_tools import SearchInput as SpecialistSearchInput
from agentmall.catalog.models import Product
from agentmall.retrieval.ingest import index_products
from agentmall.seed import seed


def product(number, store_id, price, *, active=True, stock=4, category="keyboard"):
    return Product(
        id=UUID(int=number),
        store_id=store_id,
        name=f"价格检索样品 {number}",
        category=category,
        price_cents=price,
        on_hand=stock,
        active=active,
        attributes={},
        description="价格检索测试样品",
    )


async def legacy_search(env, buyer, message, **arguments):
    arguments = {"query": "键盘", "category": "keyboard", **arguments}
    model = install_legacy(env, [ai(call("search_products", arguments)), final()])
    response = await send_legacy(env, buyer, message=message)
    assert response.status_code == 200, response.text
    page = last_result(model.seen[-1])
    assert page["ok"], page
    assert response.json()["resource_refs"] == [
        {"type": "product", "id": item["id"]} for item in page["items"]
    ]
    return page


async def test_legacy_exact_price_finds_seeded_k104_beyond_the_first_five(env, buyer):
    store = env[3].storefront_id
    async with env[2].state.sessions.begin() as session:
        session.add_all([product(1, uuid4(), 49900), product(2, store, 49900, active=False)])
    with env[1].connect() as connection:
        catalog = connection.execute(
            text(
                "SELECT id, name, price_cents FROM products "
                "WHERE store_id=:store AND active AND category='keyboard' AND price_cents<=49900 "
                "ORDER BY id"
            ),
            {"store": store},
        ).all()
    target = catalog[5]
    assert (target.name, target.price_cents) == ("静音 K104", 49900)

    ordinary = await legacy_search(env, buyer, "查找键盘", max_price_cents=49900)
    assert [p["id"] for p in ordinary["items"]] == [str(p.id) for p in catalog[:5]]
    assert ordinary["next_cursor"] == str(catalog[4].id)

    exact = await legacy_search(env, buyer, "买一件键盘，每件499元。")
    assert [(p["id"], p["price_cents"]) for p in exact["items"]] == [(str(target.id), 49900)]
    assert exact["next_cursor"] is None
    narrower = await legacy_search(env, buyer, "买一件键盘，每件499元。", max_price_cents=49899)
    assert narrower["items"] == [] and narrower["next_cursor"] is None


async def test_exact_price_page_requires_a_textual_product_kind(env, buyer):
    store = env[3].storefront_id
    async with env[2].state.sessions.begin() as session:
        for number, value in [(1, ["风扇"]), (2, {"label": "风扇"}), (3, "桌面风扇")]:
            item = product(number, store, 10000, category="home_appliance")
            item.attributes = {"appliance_type": value}
            session.add(item)

    page = await legacy_search(
        env, buyer, "买一台风扇，每台100元。", query="家电", category="home_appliance", limit=1
    )
    assert [(p["id"], p["price_cents"]) for p in page["items"]] == [(str(UUID(int=3)), 10000)]
    assert page["next_cursor"] is None


async def test_legacy_exact_price_page_also_requires_the_users_wireless_in_stock_keyboard(
    env, buyer
):
    store = env[3].storefront_id
    async with env[2].state.sessions.begin() as session:
        for number in range(1, 24):
            cheaper = product(number, store, 11100)
            cheaper.attributes = {"connection": "无线"}
            session.add(cheaper)
        for item, connection in [
            (product(30, uuid4(), 32100), "无线"),
            (product(31, store, 32100, active=False), "无线"),
            (product(32, store, 32100, category="mouse"), "无线"),
            (product(33, store, 32100), "有线"),
            (product(34, store, 32100, stock=0), "无线"),
            (product(80, store, 32100), "无线"),
        ]:
            item.name = f"键盘样品 {item.id.int}"
            item.attributes = {"connection": connection}
            session.add(item)

    for category in ("keyboard", None):
        page = await legacy_search(
            env, buyer, "请购买一件无线键盘，每件321元。", category=category, limit=1
        )
        assert [(p["id"], p["price_cents"]) for p in page["items"]] == [(str(UUID(int=80)), 32100)]
        assert page["next_cursor"] is None


@pytest.mark.parametrize("tool", ["search_products", "get_product"])
async def test_legacy_stock_read_and_candidate_search_use_current_intent(env, buyer, tool):
    item = product(10103, env[3].storefront_id, 19800, stock=0)
    item.name = "库存观察键盘"
    async with env[2].state.sessions.begin() as session:
        session.add(item)
    args = (
        {"query": item.name, "limit": 1}
        if tool == "search_products"
        else {"product_id": str(item.id)}
    )
    for message, visible in [
        ("请查一下库存观察键盘是否有库存，我只查询。", True),
        ("不用推荐，查一下库存观察键盘。", True),
        ("请购买一件键盘，送演示宿舍。", False),
        ("请推荐键盘。", False),
        ("只列出现货键盘。", False),
    ]:
        model = install_legacy(env, [ai(call(tool, args)), final()])
        response = await send_legacy(env, buyer, message=message)
        assert response.status_code == 200, response.text
        receipt = last_result(model.seen[-1])
        if tool == "search_products":
            assert receipt["ok"]
            results = receipt["items"]
        else:
            assert receipt["ok"] is visible, (message, receipt)
            results = [receipt] if visible else []
        assert [(p["id"], p["available"]) for p in results] == (
            [(str(item.id), 0)] if visible else []
        ), message


async def durable_search(env, buyer, message, **arguments):
    model = SingleModel(
        role="order",
        script=[ai(call("retrieve_products", {"query": "键盘", **arguments})), final()],
    )
    env[2].state.durable_single_model = model
    tid = await thread(env, buyer, "single")
    response = await start(env, buyer, tid, message=message)
    assert response.status_code == 201, response.text
    run = response.json()
    facts = run["result"]["facts"]
    receipt = next(f for f in facts if f["kind"] == "retrieval_candidates")
    candidates = receipt["data"]["items"]
    assert {f["id"] for f in facts if f["kind"] == "product"} == {c["id"] for c in candidates}
    return run["constraints"], candidates


async def test_durable_exact_price_qualifies_both_rankings_before_candidate_limits(
    durable_env, buyer
):
    env = durable_env
    client, _, app, settings = env
    store, other_store = settings.storefront_id, uuid4()
    encoder = FixtureEncoder()
    async with app.state.sessions.begin() as session:
        # All vectors tie and all scoped documents contain the same lexical token.
        # These 25 lower UUIDs occupy both default 20-row recall pools.
        session.add_all([product(i, store, 10000) for i in range(1, 26)])
        session.add_all(
            [
                product(26, other_store, 49900),
                product(27, store, 49900, active=False),
                product(28, store, 49900, stock=0),
                product(29, store, 49900, category="mouse"),
                product(30, store, 49901),
                product(101, store, 49900),
                product(102, store, 49900),
            ]
        )
        await session.flush()
        await index_products(session, store, encoder)
        await index_products(session, other_store, encoder)
        k104 = await session.scalar(text("SELECT id FROM products WHERE name='静音 K104'"))
    app.state.retrieval_encoder = encoder

    for mode in ("lexical", "vector", "hybrid"):
        ordinary = await client.get(
            "/api/v1/retrieval/products",
            params={
                "query": "键盘",
                "category": "keyboard",
                "mode": mode,
                "max_price_cents": 49900,
            },
        )
        assert ordinary.status_code == 200, ordinary.text
        assert [r["id"] for r in ordinary.json()["items"]] == [
            str(UUID(int=i)) for i in range(1, 6)
        ]

    constraints, exact = await durable_search(env, buyer, "买一件键盘，每件499元。")
    assert constraints["product_needs"]["unit_price_cents"] == 49900
    assert [(c["rank"], c["id"], c["product"]["price_cents"]) for c in exact] == [
        (1, str(UUID(int=101)), 49900),
        (2, str(UUID(int=102)), 49900),
        (3, str(k104), 49900),
    ]
    _, narrower = await durable_search(env, buyer, "买一件键盘，每件499元。", max_price_cents=49899)
    _, over_budget = await durable_search(env, buyer, "买一件键盘，每件499元，总预算498元。")
    assert narrower == over_budget == []


@pytest.mark.parametrize("path", ["legacy", "durable"])
async def test_requested_camera_model_precedes_catalog_and_recall_limits(durable_env, buyer, path):
    env = durable_env
    _, _, app, settings = env
    store = settings.storefront_id
    encoder = FixtureEncoder()
    async with app.state.sessions.begin() as session:
        await seed(session, settings, profile="expanded")
        # Even a full-text C10 hit in the description does not identify a C10 model.
        for number, code in enumerate(["C1"] * 25 + ["XC10", "C10A", "C100"], 1):
            item = product(number, store, 89900, category="camera")
            item.name = f"候选 {code} 相机"
            item.description = "用于对比 C10 相机的合成样品"
            session.add(item)
        if path == "durable":
            await session.flush()
            await index_products(session, store, encoder)
    message = "请购买一台 C10 相机，送演示宿舍。"
    if path == "legacy":
        page = await legacy_search(env, buyer, message, query="相机", category="camera", limit=1)
        items = page["items"]
    else:
        app.state.retrieval_encoder = encoder
        constraints, candidates = await durable_search(env, buyer, message, query="相机")
        items = [c["product"] for c in candidates]

    target = uuid5(store, "expanded-120-v1:camera-10")
    assert [(p["id"], p["name"]) for p in items] == [(str(target), "专业 C10 相机")]
    if path == "durable":
        assert constraints["product_needs"]["model_code"] == "C10"


@pytest.mark.parametrize("schema", [LegacySearchInput, SpecialistSearchInput])
def test_model_cannot_supply_trusted_purchase_filters(schema):
    with pytest.raises(ValidationError) as exc:
        schema.model_validate(
            {"query": "键盘", "unit_price_cents": 10000, "model_code": "C1", "product_kind": "fan"}
        )
    assert {(e["loc"], e["type"]) for e in exc.value.errors()} == {
        ((key,), "extra_forbidden") for key in ("unit_price_cents", "model_code", "product_kind")
    }
