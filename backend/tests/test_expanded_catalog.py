"""V2.5 explicit catalogue profile; PostgreSQL-backed business invariants."""

from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import func, select
from t09_helpers import durable_env as durable_env

from agentmall.agents.context import MultiRequest, user_constraints
from agentmall.catalog.models import Product
from agentmall.seed import PRODUCTS, seed


async def test_expanded_seed_is_explicit_repeatable_and_preserves_legacy(env):
    app, settings = env[2:]
    async with app.state.sessions.begin() as session:
        original = list((await session.scalars(select(Product).order_by(Product.id))).all())
        assert len(original) == 12
        before = {
            p.id: (p.name, p.attributes.copy(), p.price_cents, p.catalog_version) for p in original
        }
        await seed(session, settings, profile="expanded")
        assert await session.scalar(select(func.count()).select_from(Product)) == 120
        counts = dict(
            (
                await session.execute(
                    select(Product.category, func.count()).group_by(Product.category)
                )
            ).all()
        )
        assert len(counts) == 13
        assert counts["keyboard"] == 8 and counts["mouse"] == counts["headphones"] == 6
        assert all(
            n == 10 for c, n in counts.items() if c not in {"keyboard", "mouse", "headphones"}
        )
        assert {
            uuid5(settings.storefront_id, f"synthetic-sku-{i + 1:02}") for i in range(len(PRODUCTS))
        } == set(before)
        for p in original:
            await session.refresh(p)
            assert (p.name, p.attributes, p.price_cents, p.catalog_version) == before[p.id]
        phone = await session.scalar(
            select(Product).where(Product.category == "smartphone").limit(1)
        )
        phone.price_cents += 1
        phone.reserved = 1
        await session.flush()
        retained = (phone.id, phone.price_cents, phone.reserved)
        await seed(session, settings, profile="expanded")
        await seed(session, settings)  # Legacy default never removes or replaces rows.
        await session.refresh(phone)
        assert (phone.id, phone.price_cents, phone.reserved) == retained
        assert await session.scalar(select(func.count()).select_from(Product)) == 120


@pytest.mark.parametrize(
    "message,category,budget",
    [
        ("推荐3000元以内的手机，不要购买。", "smartphone", 300000),
        ("推荐适合公路车骑行的头盔。", "cycling", None),
        ("比较不同价位的27英寸显示器。", "monitor", None),
        ("推荐预算500元以内的生活电器。", "home_appliance", 50000),
    ],
)
def test_current_user_category_is_trusted_constraint(message, category, budget):
    c = user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))
    assert c.category == category
    assert c.max_price_cents == budget
    assert c.purchase_requested is False


@pytest.mark.parametrize(
    "query,category,budget,extra",
    [
        ("手机", "smartphone", 300000, {}),
        ("公路车骑行头盔配件", "cycling", None, {"activity": "road_cycling"}),
        ("27英寸显示器", "monitor", None, {"screen_inches": "27"}),
        ("生活家电", "home_appliance", 50000, {}),
        ("vlog", "camera", None, {}),
    ],
)
@pytest.mark.parametrize("mode", ["lexical", "vector", "hybrid"])
async def test_filtered_pgvector_retrieval_for_real_expanded_rows(
    env, query, category, budget, extra, mode
):
    from retrieval_helpers import actor, index

    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import SearchConfig, retrieve_products

    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    encoder = await index(env)
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            query,
            ProductQuery(query=query, mode=mode, max_price_cents=budget, **extra),
            encoder,
            config=SearchConfig(top_k=10),
        )
        assert len(hits) >= 2
        for hit in hits:
            assert hit.product.category == category
            assert hit.product.available > 0
            assert budget is None or hit.product.price_cents <= budget
            actual = await session.get(Product, hit.id)
            assert actual.catalog_version == hit.source_version
            if extra.get("screen_inches"):
                assert actual.attributes["screen_inches"] == "27"
            if extra.get("activity"):
                assert actual.attributes["usage"] == "公路车骑行"


async def test_expanded_pagination_filters_and_unknown_category(env):
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    ids = []
    cursor = None
    while True:
        params = {"limit": 7, **({"cursor": cursor} if cursor else {})}
        response = await env[0].get("/api/v1/products", params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        ids.extend(p["id"] for p in data["items"])
        cursor = data["next_cursor"]
        if not cursor:
            break
    assert len(ids) == len(set(ids)) == 120
    for cat in ["smartphone", "monitor", "cycling", "home_appliance"]:
        response = await env[0].get("/api/v1/products", params={"category": cat, "limit": 100})
        assert len(response.json()["items"]) == 10
        assert all(p["category"] == cat for p in response.json()["items"])
    phone = await env[0].get(
        "/api/v1/products", params={"query": "智能手机", "max_price_cents": 300000}
    )
    assert len(phone.json()["items"]) == 6
    assert all(p["category"] == "smartphone" for p in phone.json()["items"])
    assert (await env[0].get("/api/v1/products", params={"category": "unknown"})).status_code == 422


async def test_expanded_index_requires_versioned_rebuild_and_preserves_scope(env):
    from retrieval_helpers import actor, index
    from sqlalchemy import text

    from agentmall.retrieval.ingest import PRODUCT_INDEX_VERSION
    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import retrieve_products

    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    encoder = await index(env)
    with env[1].begin() as conn:
        conn.execute(
            text(
                "UPDATE product_search SET tokenizer_version="
                "'jieba-0.42.1-search-nfkc-v1:catalog-zh-v2'"
            )
        )
    async with env[2].state.sessions.begin() as session:
        assert (
            await retrieve_products(
                session, actor(env[3]), "手机", ProductQuery(query="手机"), encoder
            )
            == []
        )
    await index(env)
    with env[1].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM product_search WHERE tokenizer_version=:v"),
                {"v": PRODUCT_INDEX_VERSION},
            )
            == 120
        )
        conn.execute(text("UPDATE products SET active=false WHERE category='smartphone'"))
    async with env[2].state.sessions.begin() as session:
        assert (
            await retrieve_products(
                session, actor(env[3]), "手机", ProductQuery(query="手机"), encoder
            )
            == []
        )
        assert (
            await retrieve_products(
                session,
                actor(env[3], store=uuid4()),
                "显示器",
                ProductQuery(query="显示器"),
                encoder,
            )
            == []
        )
    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET on_hand=0 WHERE category='monitor'"))
        conn.execute(text("UPDATE products SET catalog_version=2 WHERE category='camera'"))
    async with env[2].state.sessions.begin() as session:
        for query in ["显示器", "相机"]:
            assert (
                await retrieve_products(
                    session, actor(env[3]), query, ProductQuery(query=query), encoder
                )
                == []
            )


def test_category_switch_clears_incompatible_memory_without_inheriting_authority():
    from agentmall.agents.memory import resolve_preferences
    from agentmall.agents.run_schemas import RunCreate

    # Category-specific keyboard requirements must not starve a new phone search.
    previous = {
        "category": "keyboard",
        "max_price_cents": 30000,
        "noise_preference": "quiet",
        "product_needs": {"layout": "87键", "connection": "无线"},
    }
    payload = RunCreate(
        request_id=uuid4(),
        message="改为推荐3000元以内的手机，不要购买。",
        expected_context_version=1,
    )
    preferences, constraints = resolve_preferences(previous, payload)
    assert preferences == {"category": "smartphone", "max_price_cents": 300000}
    assert constraints["purchase_requested"] is False
    assert constraints["quantity"] is constraints["address_label"] is None


async def test_new_sku_requires_confirmation_and_competes_for_last_unit(env, buyer, buyer2):
    from checkout_helpers import confirm, execute, prepare
    from conftest import row
    from sqlalchemy import text
    from test_order_concurrency import contend

    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
        product = str(
            await session.scalar(
                select(Product.id).where(Product.category == "smartphone").limit(1)
            )
        )
    with env[1].begin() as conn:
        conn.execute(text("UPDATE products SET on_hand=1 WHERE id=:id"), {"id": product})
    p1 = await prepare(env[0], buyer, product)
    p2 = await prepare(env[0], buyer2, product)
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    unauthorized = await env[0].post(
        "/api/v1/orders",
        headers={**buyer, "Idempotency-Key": str(uuid4())},
        json={"proposal_id": p1["proposal_id"], "confirmation_id": str(uuid4())},
    )
    assert unauthorized.status_code != 201
    c1 = await confirm(env[0], buyer, p1)
    c2 = await confirm(env[0], buyer2, p2)
    key = str(uuid4())
    results, _ = await contend(
        env,
        "SELECT id FROM products WHERE id=:id FOR UPDATE",
        {"id": product},
        [execute(env[0], buyer, p1, c1, key), execute(env[0], buyer2, p2, c2)],
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert row(env[1], "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 1
    winner = next(r.json() for r in results if r.status_code == 201)
    if results[0].status_code == 201:
        repeat = await execute(env[0], buyer, p1, c1, key)
        assert repeat.json() == winner
    else:
        repeat = await execute(env[0], buyer2, p2, c2)
        assert repeat.json() == winner
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    assert row(env[1], "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1


async def test_incremental_category_migration_refuses_destructive_downgrade(env):
    from alembic import command
    from alembic.config import Config
    from conftest import ROOT
    from sqlalchemy import text

    with env[1].begin() as conn:
        cfg = Config(str(ROOT / "backend/alembic.ini"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0007")
        assert "smartphone" not in conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='ck_products_category' "
                "AND connamespace=current_schema()::regnamespace"
            )
        )
        command.upgrade(cfg, "head")
        assert "smartphone" in conn.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname='ck_products_category' "
                "AND connamespace=current_schema()::regnamespace"
            )
        )
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    with pytest.raises(RuntimeError, match="Expanded products exist"), env[1].begin() as conn:
        cfg = Config(str(ROOT / "backend/alembic.ini"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0007")
    with env[1].connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
        assert conn.scalar(text("SELECT count(*) FROM products")) == 120


@pytest.mark.parametrize("mode", ["single", "multi"])
async def test_expanded_agent_recommends_facts_and_new_sku_waits_for_own_confirmation(
    durable_env, buyer, tmp_path, mode
):
    from conftest import row
    from multiturn_helpers import install_context_sdk
    from t09_helpers import confirm, resume, thread
    from test_thread_memory import read, turn

    env = durable_env
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    provider, program = await install_context_sdk(env, tmp_path)
    try:
        tid = await thread(env, buyer, mode)
        for message, category in [
            ("推荐3000元以内的手机，不要购买。", "smartphone"),
            ("改为比较27英寸显示器，不要下单。", "monitor"),
        ]:
            version = (await read(env, buyer, tid))["context"]["version"]
            response = await turn(env, buyer, tid, message, version)
            assert response.status_code == 201, response.text
            assert response.json()["status"] == "COMPLETED", (
                response.json().get("result") or {}
            ).get("error_codes")
            context = (await read(env, buyer, tid))["context"]
            assert context["preferences"]["category"] == category
            latest = context["candidate_sets"][0]
            assert len(latest["items"]) >= 2
            for item in latest["items"]:
                assert (
                    row(env[1], "SELECT category FROM products WHERE id=:id", id=item["id"])[
                        "category"
                    ]
                    == category
                )
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM confirmations")["n"] == 0
        target = latest["items"][1]
        purchase = await turn(
            env,
            buyer,
            tid,
            "就买第二款，一件，送演示宿舍。",
            context["version"],
            candidate_set_id=latest["id"],
        )
        assert purchase.status_code == 201, purchase.text
        run = purchase.json()
        assert run["status"] == "WAITING_INPUT", run
        pid = run["pending_confirmation"]["proposal_id"]
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        cid = await confirm(env, buyer, pid)
        request = str(uuid4())
        complete = await resume(env, buyer, tid, run, cid, request)
        assert complete.status_code == 200, complete.text
        assert complete.json()["status"] == "COMPLETED", complete.json()
        again = await resume(env, buyer, tid, run, cid, request)
        assert again.status_code == 200, again.text
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
        assert row(env[1], "SELECT product_id,quantity FROM order_items") == {
            "product_id": UUID(target["id"]),
            "quantity": 1,
        }
        assert (
            row(env[1], "SELECT reserved FROM products WHERE id=:id", id=target["id"])["reserved"]
            == 1
        )
        assert any(
            r["role"] == ("single" if mode == "single" else "shopping")
            and r["content"]["constraints"]["category"] == "smartphone"
            for r in program.requests
        )
    finally:
        await provider.close()


def test_optional_category_needs_keep_legacy_hash_shape_when_excluded():
    from agentmall.agents.context import ProductNeeds

    assert ProductNeeds().model_dump(exclude_none=True) == {}
    assert ProductNeeds(screen_inches="27").model_dump(exclude_none=True) == {"screen_inches": "27"}


def test_expanded_resource_uses_only_category_appropriate_synthetic_facts():
    from agentmall.catalog.categories import infer_category
    from agentmall.catalog.profiles import expanded_products

    required = {
        "smartphone": {"memory", "storage", "screen_size", "imaging"},
        "laptop": {"processor_tier", "memory", "storage", "weight", "usage"},
        "monitor": {"screen_inches", "resolution", "refresh_rate", "panel", "ports"},
        "camera": {"camera_type", "sensor_class", "video", "weight"},
        "cycling": {"equipment_type", "usage", "size", "material", "weight"},
        "fitness": {"equipment_type", "resistance", "usage"},
        "home_appliance": {"capacity", "power", "features", "usage"},
    }
    for product in expanded_products():
        assert required.get(product.category, set()) <= set(product.attributes)
        assert not ({"switch", "layout", "noise"} & set(product.attributes))
        assert "合成" in product.description and "无品牌授权" in product.description
    assert infer_category("电脑显示器") == "monitor"
    assert infer_category("推荐平板电脑") == "tablet"
    assert infer_category("推荐电脑") == "laptop"


async def test_keyword_search_never_broadens_subtypes_to_whole_category(env):
    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    for query, attr, expected in [
        ("无线鼠标", "connection", "无线"),
        ("咖啡机", "appliance_type", "咖啡机"),
    ]:
        response = await env[0].get("/api/v1/products", params={"query": query, "limit": 100})
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert items
        assert all(expected in p["attributes"].get(attr, "") for p in items)


@pytest.mark.parametrize(
    "field,value,category",
    [
        ("screen_inches", "27", "monitor"),
        ("activity", "road_cycling", "cycling"),
        ("product_kind", "coffee_machine", "home_appliance"),
    ],
)
async def test_new_category_preferences_have_explicit_versioned_clear(
    durable_env, buyer, field, value, category
):
    from t09_helpers import thread
    from test_thread_memory import read

    env = durable_env
    tid = await thread(env, buyer)
    response = await env[0].patch(
        f"/api/v1/agent/threads/{tid}/context",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "operations": [
                {"op": "SET", "field": "category", "value": category},
                {"op": "SET", "field": field, "value": value},
            ],
        },
    )
    assert response.status_code == 200, response.text
    context = (await read(env, buyer, tid))["context"]
    assert context["preferences"]["product_needs"][field] == value
    body = {
        "request_id": str(uuid4()),
        "expected_version": context["version"],
        "operations": [{"op": "CLEAR", "field": field}],
    }
    for _ in range(2):
        cleared = await env[0].patch(
            f"/api/v1/agent/threads/{tid}/context", headers=buyer, json=body
        )
        assert cleared.status_code == 200, cleared.text
    final = (await read(env, buyer, tid))["context"]
    assert field not in final["preferences"].get("product_needs", {})
    assert final["version"] == context["version"] + 1


@pytest.mark.parametrize(
    "query,kind,category",
    [
        ("咖啡机", "coffee_machine", "home_appliance"),
        ("哑铃", "dumbbell", "fitness"),
        ("公路车头盔", "helmet", "cycling"),
    ],
)
async def test_specific_product_kind_is_applied_before_vector_limit(env, query, kind, category):
    from retrieval_helpers import actor, index

    from agentmall.catalog.categories import KIND_ATTRIBUTES
    from agentmall.retrieval.schemas import ProductQuery
    from agentmall.retrieval.search import SearchConfig, retrieve_products

    async with env[2].state.sessions.begin() as session:
        await seed(session, env[3], profile="expanded")
    encoder = await index(env)
    async with env[2].state.sessions.begin() as session:
        hits = await retrieve_products(
            session,
            actor(env[3]),
            query,
            ProductQuery(query=query, mode="vector"),
            encoder,
            config=SearchConfig(top_k=10, candidates=10),
        )
    _, key, word = KIND_ATTRIBUTES[kind]
    assert len(hits) >= 2
    assert all(h.product.category == category and word in h.product.attributes[key] for h in hits)
    c = user_constraints(
        MultiRequest(request_id=uuid4(), thread_id=uuid4(), message="推荐" + query + "，不要购买。")
    )
    assert c.product_needs.product_kind == kind


@pytest.mark.parametrize(
    "message,kind",
    [
        ("推荐适合家庭或者办公室的咖啡机", "coffee_machine"),
        ("找用于居家或健身房的哑铃", "dumbbell"),
        ("推荐适合通勤或者公路车骑行的头盔", "helmet"),
    ],
)
def test_alternative_usage_does_not_erase_explicit_product_kind(message, kind):
    from agentmall.catalog.categories import infer_product_kind

    assert infer_product_kind(message) == kind
