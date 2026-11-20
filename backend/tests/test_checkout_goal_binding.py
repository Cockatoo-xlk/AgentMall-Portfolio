"""A verified receipt can close only the specific purchase and its own review."""

from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from t09_helpers import durable_env as durable_env

from agentmall.agents.context import Constraints, MultiRequest, ProductNeeds, user_constraints
from agentmall.agents.goal_receipts import completed_single_checkout
from agentmall.agents.specialist_tools import product_allowed
from agentmall.catalog.profiles import expanded_products
from agentmall.catalog.schemas import ProductDTO


@pytest.fixture(scope="module")
def catalog():
    return {
        p.sku: ProductDTO(
            id=uuid5(NAMESPACE_URL, p.sku),
            name=p.name,
            category=p.category,
            attributes=p.attributes,
            description=p.description,
            price_cents=p.price_cents,
            available=p.on_hand,
            catalog_version=1,
        )
        for p in expanded_products()
    }


def receipt_item(product, quantity=1):
    return {
        "product_id": str(product.id),
        "name_snapshot": product.name,
        "attributes_snapshot": product.attributes,
        "catalog_version": product.catalog_version,
        "unit_price_cents": product.price_cents,
        "quantity": quantity,
    }


def checked_out(message, product, *other_candidates, constraints=None, quantity=1):
    request = MultiRequest(
        request_id=uuid4(), thread_id=uuid4(), message=message, constraints=constraints
    )
    pid = str(uuid4())
    facts = {
        ("product", str(p.id)): p.model_dump(mode="json") for p in (product, *other_candidates)
    }
    facts[("proposal", pid)] = {
        "proposal_id": pid,
        "action_type": "CHECKOUT",
        "status": "EXECUTED",
        "snapshot": {
            "schema_version": 1,
            "currency": "CNY",
            "policy_version": "demo-v1",
            "address_label": "demo_dorm",
            "items": [receipt_item(product, quantity)],
            "total_cents": quantity * product.price_cents,
        },
        "result": {
            "action_id": pid,
            "status": "PENDING_PAYMENT",
            "resource_id": str(uuid4()),
        },
    }
    runtime = SimpleNamespace(
        input=request,
        constraints=user_constraints(request),
        exclusions=set(),
        thread_snapshot={},
        facts=facts,
        pending={},
        completed={},
        errors=[],
    )
    return runtime, pid


@pytest.mark.parametrize(
    "kind,sku,allowed",
    [
        ("风扇", "home_appliance-05", True),
        ("风扇", "home_appliance-06", False),
        ("加湿器", "home_appliance-06", True),
        ("加湿器", "home_appliance-05", False),
        ("电水壶", "home_appliance-01", True),
        ("电水壶", "home_appliance-03", False),
        ("咖啡机", "home_appliance-01", False),
        ("相机", "home_appliance-06", False),
        ("C10 相机", "camera-01", False),
        ("C10 相机", "camera-10", True),
        ("骑行手套", "cycling-01", False),
        ("骑行手套", "cycling-05", True),
        ("健身阻力带", "fitness-01", False),
        ("健身阻力带", "fitness-05", True),
        ("瑜伽垫", "fitness-08", False),
        ("瑜伽垫", "fitness-07", True),
        ("空气炸锅", "home_appliance-08", False),
        ("空气炸锅", "home_appliance-09", True),
    ],
)
@pytest.mark.parametrize("stage", ["candidate", "receipt"])
def test_purchase_type_binds_to_the_actual_catalog_item(catalog, kind, sku, allowed, stage):
    message = f"请购买一台{kind}，送演示宿舍。"
    product = catalog[sku]
    runtime, pid = checked_out(message, product, catalog["home_appliance-05"])
    if stage == "candidate":
        assert product_allowed(runtime, product) is allowed
    else:
        assert completed_single_checkout(runtime, message, {pid}) == (pid if allowed else None)


def test_item_without_subtype_evidence_cannot_finish_a_named_purchase(catalog):
    message = "请购买一台风扇，送演示宿舍。"
    unknown = catalog["home_appliance-06"].model_copy(
        update={"name": "桌面 A6 家电", "attributes": {"usage": "桌面"}}
    )
    runtime, pid = checked_out(message, unknown, catalog["home_appliance-05"])
    assert completed_single_checkout(runtime, message, {pid}) is None


def test_extra_checkout_line_cannot_prove_a_single_product_request(catalog):
    message = "请购买一台风扇，送演示宿舍。"
    fan, humidifier = catalog["home_appliance-05"], catalog["home_appliance-06"]
    runtime, pid = checked_out(message, fan, humidifier)
    snapshot = runtime.facts[("proposal", pid)]["snapshot"]
    snapshot["items"].append(receipt_item(humidifier))
    snapshot["total_cents"] += humidifier.price_cents
    assert completed_single_checkout(runtime, message, {pid}) is None


@pytest.mark.parametrize("explicit_choice", ["model", "product_id", "selected"])
def test_mismatched_selected_item_cannot_be_closed_by_another_receipt(catalog, explicit_choice):
    selected, purchased = catalog["camera-10"], catalog["camera-01"]
    message = {
        "model": "请购买一台 C10 相机，送演示宿舍。",
        "product_id": f"请购买{selected.id}一台，送演示宿舍。",
        "selected": "请购买一台相机，送演示宿舍。",
    }[explicit_choice]
    runtime, pid = checked_out(message, purchased, selected)
    if explicit_choice == "selected":
        runtime.thread_snapshot["selected"] = [{"id": str(selected.id)}]
    assert completed_single_checkout(runtime, message, {pid}) is None


@pytest.mark.parametrize("same_item", [True, False])
def test_replacement_purpose_preserves_explicit_purchase_identity(catalog, same_item):
    selected = catalog["camera-10"]
    purchased = selected if same_item else catalog["camera-01"]
    message = f"请购买{selected.id}作为替代品，数量为一台，送演示宿舍。"
    runtime, pid = checked_out(message, purchased, selected)
    assert completed_single_checkout(runtime, message, {pid}) == (pid if same_item else None)


@pytest.mark.parametrize(
    "tail,checkout_only",
    [
        ("", True),
        ("。先给我购买提案，我核对商品、数量、金额和库存后再决定。", True),
        ("再帮我摄像", False),
        ("，再帮我摄像", False),
        ("。然后帮我摄像", False),
        ("再给我摄影", False),
        ("再帮我记笔记", False),
    ],
)
def test_purchase_object_and_independent_activity_have_distinct_scope(catalog, tail, checkout_only):
    message = f"请购买一台相机{tail}，送演示宿舍。"
    runtime, pid = checked_out(message, catalog["camera-01"])
    assert completed_single_checkout(runtime, message, {pid}) == (pid if checkout_only else None)


@pytest.mark.parametrize(
    "selection,purchase,checkout_only",
    [
        ("推荐相机", "准备购买两台", True),
        ("推荐相机", "准备购买两台，再帮我查订单", False),
        ("推荐相机", "准备购买两台相机", False),
        ("推荐并比较相机", "准备购买两台", False),
        ("推荐三台相机", "准备购买两台", False),
    ],
)
def test_checkout_can_complete_an_implicit_product_selection(
    catalog, selection, purchase, checkout_only
):
    product = catalog["camera-01"]
    message = f"预算{product.price_cents // 100 * 2}元，{selection}，{purchase}，送演示宿舍"
    runtime, pid = checked_out(message, product, quantity=2)
    assert completed_single_checkout(runtime, message, {pid}) == (pid if checkout_only else None)


@pytest.mark.parametrize("stage", ["search", "get", "prepare"])
@pytest.mark.parametrize(
    "subject,wanted,wrong,category",
    [
        ("风扇", "home_appliance-05", "home_appliance-06", "home_appliance"),
        ("C10 相机", "camera-10", "camera-01", "camera"),
    ],
)
async def test_legacy_tools_enforce_requested_product(env, stage, subject, wanted, wrong, category):
    from retrieval_helpers import actor
    from sqlalchemy import func, select

    from agentmall.actions.models import ActionProposal
    from agentmall.agents.tools import ToolContext
    from agentmall.catalog.service import get_product
    from agentmall.seed import seed

    _, _, app, settings = env
    buyer = actor(settings)
    wanted_id = uuid5(settings.storefront_id, f"expanded-120-v1:{wanted}")
    wrong_id = uuid5(settings.storefront_id, f"expanded-120-v1:{wrong}")
    request = MultiRequest(
        request_id=uuid4(), thread_id=uuid4(), message=f"请购买一台{subject}，送演示宿舍。"
    )
    context = ToolContext(buyer, request.request_id, app.state.sessions, user_constraints(request))
    async with app.state.sessions.begin() as session:
        await seed(session, settings, profile="expanded")
        wrong_item = await get_product(session, buyer, wrong_id)

    if stage == "search":
        for limit in (20, 1):
            result = await context.execute(
                "search_products", {"category": category, "limit": limit}
            )
            assert result["ok"]
            assert [p["id"] for p in result["items"]] == [str(wanted_id)]
    elif stage == "get":
        result = await context.execute("get_product", {"product_id": str(wrong_id)})
        assert result.get("error_code") == "CONSTRAINT_MISMATCH"
        assert str(wrong_id) not in context.observed
        assert (await context.execute("get_product", {"product_id": str(wanted_id)}))["ok"]
    else:
        # Isolate the write guard. Seeing a valid SKU is only one prerequisite.
        context.observed[str(wrong_id)] = wrong_item
        result = await context.execute(
            "prepare_checkout",
            {
                "items": [{"product_id": str(wrong_id), "quantity": 1}],
                "address_label": "demo_dorm",
            },
        )
        async with app.state.sessions.begin() as session:
            proposals = await session.scalar(select(func.count()).select_from(ActionProposal))
        assert (result.get("error_code"), proposals) == ("CONSTRAINT_MISMATCH", 0)
        assert (await context.execute("get_product", {"product_id": str(wanted_id)}))["ok"]
        correct = await context.execute(
            "prepare_checkout",
            {
                "items": [{"product_id": str(wanted_id), "quantity": 1}],
                "address_label": "demo_dorm",
            },
        )
        assert correct["ok"] and correct["status"] == "PENDING"
        assert correct["canonical_payload"]["items"][0]["product_id"] == str(wanted_id)


@pytest.mark.parametrize(
    "message",
    [
        "请购买一台风扇，不要加湿器，送演示宿舍。",
        "请买一台不是加湿器的风扇，送演示宿舍。",
    ],
)
def test_declined_subtype_never_replaces_the_affirmative_purchase(catalog, message):
    fan, humidifier = catalog["home_appliance-05"], catalog["home_appliance-06"]
    runtime, _ = checked_out(message, humidifier)
    assert product_allowed(runtime, fan)
    assert not product_allowed(runtime, humidifier)


@pytest.mark.parametrize(
    "message",
    [
        "请购买一台风扇还是加湿器，送演示宿舍。",
        "请购买一台家电，不要加湿器，送演示宿舍。",
        "请买一台相机，型号不是 C10，送演示宿舍。",
        "请购买一台 C10 或 C1 相机，送演示宿舍。",
    ],
)
def test_unresolved_purchase_subject_requires_clarification(message):
    from agentmall.infra.errors import DomainError

    with pytest.raises(DomainError) as error:
        user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_compatible_typed_price_keeps_the_item_type_and_conflict_is_rejected(catalog):
    from agentmall.infra.errors import DomainError

    message = "请购买一台风扇，送演示宿舍。"
    humidifier = catalog["home_appliance-06"]
    compatible = Constraints(product_needs=ProductNeeds(unit_price_cents=humidifier.price_cents))
    runtime, _ = checked_out(message, humidifier, constraints=compatible)
    assert not product_allowed(runtime, humidifier)
    conflicting = Constraints(product_needs=ProductNeeds(product_kind="humidifier"))
    with pytest.raises(DomainError) as error:
        checked_out(message, humidifier, constraints=conflicting)
    assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"


def test_model_selection_applies_to_this_purchase_across_thread_resolution(catalog):
    from agentmall.agents.memory import resolve_preferences
    from agentmall.agents.run_schemas import RunCreate

    def request(message):
        return RunCreate(request_id=uuid4(), message=message)

    prefs, now = resolve_preferences({}, request("请购买一台 Ｃ１０ 相机，送演示宿舍。"))
    runtime = SimpleNamespace(constraints=Constraints.model_validate(now), exclusions=set())
    assert product_allowed(runtime, catalog["camera-10"])
    assert not product_allowed(runtime, catalog["camera-01"])
    _, later = resolve_preferences(prefs, request("请购买一台相机，送演示宿舍。"))
    runtime.constraints = Constraints.model_validate(later)
    assert product_allowed(runtime, catalog["camera-01"])


def test_read_only_alternatives_can_remain_a_broad_catalogue_request():
    c = user_constraints(
        MultiRequest(request_id=uuid4(), thread_id=uuid4(), message="推荐风扇或加湿器。")
    )
    assert c.category == "home_appliance" and c.product_needs.product_kind is None
    assert not c.purchase_requested


@pytest.mark.parametrize("subject", ["相机镜头", "压力锅"])
def test_unrecognized_specific_purchase_is_not_an_arbitrary_catalogue_candidate(catalog, subject):
    from agentmall.infra.errors import DomainError

    candidate = catalog["camera-01"] if subject.startswith("相机") else catalog["home_appliance-05"]
    try:
        runtime, _ = checked_out(f"请购买一台{subject}，送演示宿舍。", candidate)
    except DomainError as error:
        assert error.code == "CONTEXT_CLARIFICATION_REQUIRED"
    else:
        assert not product_allowed(runtime, candidate)


@pytest.mark.parametrize(
    "damage", ["name_only", "quantity", "address", "unit", "total", "no_product"]
)
def test_fast_close_requires_the_complete_economic_and_item_binding(catalog, damage):
    camera = catalog["camera-01"]
    message = f"请购买两台单价{camera.price_cents // 100}元的相机，送演示宿舍。"
    runtime, pid = checked_out(message, camera)
    snapshot = runtime.facts[("proposal", pid)]["snapshot"]
    item = snapshot["items"][0]
    item["quantity"] = 2
    snapshot["total_cents"] = 2 * camera.price_cents
    if damage == "name_only":
        snapshot["items"] = [{"name_snapshot": "相机"}]
    elif damage == "quantity":
        item["quantity"] = 1
        snapshot["total_cents"] = camera.price_cents
    elif damage == "address":
        snapshot["address_label"] = "demo_home"
    elif damage == "unit":
        item["unit_price_cents"] += 100
        snapshot["total_cents"] += 200
    elif damage == "total":
        snapshot["total_cents"] += 1
    else:
        del runtime.facts[("product", str(camera.id))]
    assert completed_single_checkout(runtime, message, {pid}) is None


@pytest.mark.parametrize("stage", ["get", "prepare"])
async def test_legacy_read_and_write_cannot_bypass_connection_or_stock(env, stage):
    from retrieval_helpers import actor
    from sqlalchemy import update

    from agentmall.agents.tools import ToolContext
    from agentmall.catalog.models import Product
    from agentmall.catalog.service import get_product

    _, _, app, settings = env
    buyer = actor(settings)
    product_id = uuid5(settings.storefront_id, "synthetic-sku-01")
    async with app.state.sessions.begin() as session:
        keyboard = await get_product(session, buyer, product_id)
    for message in (
        "请购买一件无线键盘，送演示宿舍。",
        "请购买一件有线键盘，送演示宿舍。",
    ):
        if "有线" in message:
            async with app.state.sessions.begin() as session:
                await session.execute(
                    update(Product).where(Product.id == product_id).values(on_hand=0)
                )
        request = MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message)
        context = ToolContext(
            buyer, request.request_id, app.state.sessions, user_constraints(request)
        )
        if stage == "get":
            result = await context.execute("get_product", {"product_id": str(product_id)})
        else:
            context.observed[str(product_id)] = keyboard
            result = await context.execute(
                "prepare_checkout",
                {
                    "items": [{"product_id": str(product_id), "quantity": 1}],
                    "address_label": "demo_dorm",
                },
            )
        assert result.get("error_code") == "CONSTRAINT_MISMATCH"


@pytest.mark.parametrize(
    "message,sku,expected",
    [
        ("请购买一台相机，另外查询 C10 的物流，送演示宿舍。", "camera-01", True),
        ("请购买一台 C1 相机再帮我查询 C10 的物流，送演示宿舍。", "camera-01", True),
        ("请购买一台 C1 相机，查询 C10 的物流，送演示宿舍。", "camera-10", False),
        ("请购买一台风扇，另外查询加湿器的物流，送演示宿舍。", "home_appliance-05", True),
    ],
)
def test_independent_read_subject_is_not_the_purchase_target(catalog, message, sku, expected):
    runtime, _ = checked_out(message, catalog[sku])
    assert runtime.constraints.purchase_requested
    assert product_allowed(runtime, catalog[sku]) is expected


async def test_legacy_stock_inquiry_can_read_referenced_sold_out_sku(env):
    from retrieval_helpers import actor
    from sqlalchemy import update

    from agentmall.agents.tools import ToolContext
    from agentmall.catalog.models import Product

    _, _, app, settings = env
    ident = uuid5(settings.storefront_id, "synthetic-sku-01")
    async with app.state.sessions.begin() as session:
        await session.execute(update(Product).where(Product.id == ident).values(on_hand=0))
    request = MultiRequest(
        request_id=uuid4(), thread_id=uuid4(), message=f"请查商品 {ident} 的库存。"
    )
    context = ToolContext(
        actor(settings), request.request_id, app.state.sessions, user_constraints(request)
    )
    result = await context.execute("get_product", {"product_id": str(ident)})
    assert result["ok"] and result["id"] == str(ident) and result["available"] == 0


@pytest.mark.parametrize(
    "managed,structured_connection,legacy_storage",
    [
        (False, None, False),
        (True, None, False),
        (True, None, True),
        (False, "有线", False),
        (True, "有线", False),
    ],
    ids=["direct", "thread", "old-expanded-thread", "conflict-direct", "conflict-thread"],
)
async def test_partial_product_needs_merge_at_run_entry(
    durable_env, buyer, managed, structured_connection, legacy_storage
):
    from uuid import UUID

    from multiagent_helpers import final
    from t09_helpers import thread
    from test_baseline_fairness import SingleModel

    client, _, app, _ = durable_env
    tid = await thread(durable_env, buyer, "single")
    app.state.durable_single_model = SingleModel(
        role="order", script=[final('{"terminal":"clarify"}')]
    )
    needs = {"max_unit_price_cents": 9800}
    if structured_connection is not None:
        needs["connection"] = structured_connection
    payload = {
        "request_id": str(uuid4()),
        "message": "请帮我买一只无线鼠标，单价88元，总预算100元，送演示家庭。",
        "constraints": {"product_needs": needs},
    }
    if managed:
        payload["expected_context_version"] = 0
    response = await client.post(f"/api/v1/agent/threads/{tid}/runs", headers=buyer, json=payload)
    if structured_connection == "有线":
        assert (
            response.status_code == 409
            and response.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
        )
        return
    assert response.status_code == 201, response.text
    constraints = response.json()["constraints"]
    assert constraints["category"] == "mouse"
    assert constraints["purchase_requested"] and constraints["quantity"] == 1
    assert constraints["address_label"] == "demo_home" and constraints["max_price_cents"] == 10000
    result = constraints["product_needs"]
    assert result["connection"] == "无线" and result["unit_price_cents"] == 8800
    assert result["max_unit_price_cents"] == 9800

    if legacy_storage:
        from agentmall.actions.service import payload_hash
        from agentmall.agents.models import AgentRun

        expanded = Constraints.model_validate(payload["constraints"]).model_dump(mode="json")
        assert response.json()["input_digest"] == payload_hash({**payload, "constraints": expanded})
        async with app.state.sessions.begin() as session:
            run = await session.get(AgentRun, UUID(response.json()["id"]))
            run.request_payload = {**run.request_payload, "constraints": expanded}

    url = f"/api/v1/agent/threads/{tid}/runs"
    replay = await client.post(url, headers=buyer, json=payload)
    assert replay.status_code == 200 and replay.json()["id"] == response.json()["id"]
    withdrawn = {**payload, "constraints": {**payload["constraints"], "purchase_requested": False}}
    replay = await client.post(url, headers=buyer, json=withdrawn)
    assert replay.status_code == 409 and replay.json()["code"] == "IDEMPOTENCY_CONFLICT"
    if legacy_storage:
        # Resubmitting the historical expanded template explicitly denies all its default actions.
        replay = await client.post(url, headers=buyer, json={**payload, "constraints": expanded})
        assert replay.status_code == 409 and replay.json()["code"] == "IDEMPOTENCY_CONFLICT"
    withdrawn["request_id"] = str(uuid4())
    other = await thread(durable_env, buyer, "single")
    rejected = await client.post(
        f"/api/v1/agent/threads/{other}/runs", headers=buyer, json=withdrawn
    )
    assert (
        rejected.status_code == 409 and rejected.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
    )


@pytest.mark.parametrize(
    "message,conflict",
    [
        ("请购买两件键盘，送演示宿舍。", False),
        ("请购买两件键盘，地址为演示宿舍。", False),
        ("请购买两件键盘，收货地址是：演示宿舍。", False),
        ("请购买两件宿舍静音键盘，送演示宿舍。", True),
    ],
)
def test_shipping_label_is_independent_of_product_usage(message, conflict):
    from agentmall.infra.errors import DomainError

    request = MultiRequest(
        request_id=uuid4(),
        thread_id=uuid4(),
        message=message,
        constraints=Constraints(product_needs=ProductNeeds(usage="办公")),
    )
    if conflict:
        with pytest.raises(DomainError) as error:
            user_constraints(request)
        assert error.value.code == "CONTEXT_CLARIFICATION_REQUIRED"
    else:
        constraints = user_constraints(request)
        assert constraints.address_label == "demo_dorm"
        assert constraints.product_needs.usage == "办公"


@pytest.mark.parametrize(
    "address,expected",
    [
        ("收货地址是：演示家庭", "送演示家庭"),
        ("地址为演示宿舍。", "送演示宿舍。"),
        ("地址为合成测试路17号", "[REDACTED]"),
        ("地址为演示宿舍 17号", "[REDACTED]"),
    ],
)
def test_run_persists_only_a_complete_demo_address_label(address, expected):
    from agentmall.agents.run_service import sanitized

    assert sanitized(address) == expected
