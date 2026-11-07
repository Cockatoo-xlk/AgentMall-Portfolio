"""Revision contracts over real owned PostgreSQL and official checkpoints; Mock only."""

from uuid import uuid4

import pytest
from bundle_helpers import install_bundle_sdk
from conftest import row
from sqlalchemy import text
from t09_helpers import confirm, resume, thread
from t09_helpers import durable_env as durable_env
from test_bundle_shopping import MESSAGE
from test_thread_memory import read, turn


async def initial(env, buyer, tmp_path, message=MESSAGE):
    provider, program = await install_bundle_sdk(env, tmp_path / "mock")
    tid = await thread(env, buyer)
    response = await turn(env, buyer, tid, message, 0)
    assert response.status_code == 201, response.text
    context = (await read(env, buyer, tid))["context"]
    assert len(context["bundles"]) == 1
    return provider, program, tid, context, context["bundles"][0]


async def edit(env, buyer, tid, context, message, **extra):
    return await turn(env, buyer, tid, message, context["version"], **extra)


@pytest.mark.parametrize(
    "message,refresh,categories",
    [
        ("键盘必须支持无线连接。", {"keyboard"}, {"monitor", "keyboard", "mouse", "headphones"}),
        (
            "显示器不要换，再加一个音箱。",
            {"speaker"},
            {"monitor", "keyboard", "mouse", "headphones", "speaker"},
        ),
        ("不要鼠标了。", set(), {"monitor", "keyboard", "headphones"}),
        ("总预算提高到6000元。", set(), {"monitor", "keyboard", "mouse", "headphones"}),
        ("显示器一台，耳机两副。", set(), {"monitor", "keyboard", "mouse", "headphones"}),
    ],
)
async def test_incremental_edit_reuses_exact_other_skus(
    durable_env, buyer, tmp_path, monkeypatch, message, refresh, categories
):
    env = durable_env
    provider, program, tid, context, old = await initial(
        env, buyer, tmp_path, MESSAGE.replace("无线键盘", "键盘")
    )
    from agentmall.agents import bundle_tools

    original = bundle_tools.retrieve_products
    queries = []

    async def traced(session, actor, query, filters, encoder):
        queries.append(filters.category)
        return await original(session, actor, query, filters, encoder)

    monkeypatch.setattr(bundle_tools, "retrieve_products", traced)
    try:
        response = await edit(env, buyer, tid, context, message)
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "COMPLETED", response.text
        current = (await read(env, buyer, tid))["context"]
        new = current["bundles"][0]
        assert set(queries) == refresh and len(queries) == len(refresh)
        assert {i["category"] for i in new["items"]} == categories
        old_ids = {i["category"]: i["id"] for i in old["items"]}
        for item in new["items"]:
            if item["category"] not in refresh:
                assert item["id"] == old_ids[item["category"]]
        assert (
            new["bundle_id"] != old["bundle_id"]
            and new["revision"]["source_bundle_id"] == old["bundle_id"]
        )
        assert new["valid"] and new["total_cents"] <= new["budget_cents"]
        assert any(x["bundle_id"] == old["bundle_id"] for x in current["bundle_history"])
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    finally:
        await provider.close()


async def test_cheaper_replacement_and_two_edits_then_safe_purchase(
    durable_env, buyer, tmp_path, monkeypatch
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        ear = next(i for i in old["items"] if i["category"] == "headphones")
        # A legitimate cheaper current catalogue fact, not a mocked tool answer.
        with env[1].begin() as c:
            alternative = c.scalar(
                text(
                    "SELECT id FROM products WHERE category='headphones' AND id<>:id AND active "
                    "ORDER BY id LIMIT 1"
                ),
                {"id": ear["id"]},
            )
            c.execute(
                text(
                    "UPDATE products SET price_cents=:price,"
                    "catalog_version=catalog_version+1 WHERE id=:id"
                ),
                {"price": ear["price_cents"] - 100, "id": alternative},
            )
        from retrieval_helpers import index

        await index(env)
        from agentmall.agents import bundle_tools

        original = bundle_tools.retrieve_products
        queries = []

        async def traced(session, actor, query, filters, encoder):
            queries.append(filters.category)
            return await original(session, actor, query, filters, encoder)

        monkeypatch.setattr(bundle_tools, "retrieve_products", traced)
        request_id = str(uuid4())
        response = await edit(env, buyer, tid, context, "耳机换个便宜的。", request_id=request_id)
        assert response.status_code == 201, response.text
        current = (await read(env, buyer, tid))["context"]
        new = current["bundles"][0]
        assert queries == ["headphones"]
        replacement = next(i for i in new["items"] if i["category"] == "headphones")
        assert replacement["id"] != ear["id"] and replacement["price_cents"] < ear["price_cents"]
        assert (
            row(env[1], "SELECT price_cents FROM products WHERE id=:id", id=replacement["id"])[
                "price_cents"
            ]
            == replacement["price_cents"]
        )
        for item in new["items"]:
            if item["category"] != "headphones":
                assert item["id"] == next(
                    i["id"] for i in old["items"] if i["category"] == item["category"]
                )
        replay = await edit(env, buyer, tid, context, "耳机换个便宜的。", request_id=request_id)
        assert replay.status_code == 200
        assert (
            row(env[1], "SELECT count(*) n FROM agent_candidate_sets WHERE kind='bundle'")["n"] == 2
        )
        assert (await read(env, buyer, tid))["context"]["version"] == current["version"]
        second = await edit(env, buyer, tid, current, "显示器不要换，再加一个音箱。")
        assert second.status_code == 201, second.text
        latest = (await read(env, buyer, tid))["context"]
        offer = latest["bundles"][0]
        assert len(offer["items"]) == 5
        stale = await edit(
            env, buyer, tid, latest, "就买这套，每样一件，送演示宿舍。", bundle_id=old["bundle_id"]
        )
        assert stale.status_code == 409 and stale.json()["code"] == "STALE_BUNDLE"
        buying = await edit(
            env,
            buyer,
            tid,
            latest,
            "就买修改后的这套，每样一件，送演示宿舍。",
            bundle_id=offer["bundle_id"],
        )
        assert buying.status_code == 201, buying.text
        waiting = buying.json()
        assert waiting["status"] == "WAITING_INPUT"
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
        busy = await edit(env, buyer, tid, (await read(env, buyer, tid))["context"], "不要鼠标了。")
        assert busy.status_code == 409 and busy.json()["code"] == "THREAD_BUSY"
        confirmation = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        request = str(uuid4())
        done = await resume(env, buyer, tid, waiting, confirmation, request_id=request)
        assert done.status_code == 200 and done.json()["status"] == "COMPLETED", done.text
        again = await resume(env, buyer, tid, waiting, confirmation, request_id=request)
        assert again.status_code == 200
        assert row(env[1], "SELECT count(*) n FROM orders WHERE status='PENDING_PAYMENT'")["n"] == 1
        assert row(env[1], "SELECT count(*) n FROM order_items")["n"] == 5
        assert row(env[1], "SELECT count(*) n FROM payments")["n"] == 0
        with env[1].connect() as c:
            actual = (
                c.execute(
                    text(
                        "SELECT i.product_id,i.quantity,p.reserved FROM order_items i "
                        "JOIN products p ON p.id=i.product_id"
                    )
                )
                .mappings()
                .all()
            )
        assert {str(i["product_id"]) for i in actual} == {i["id"] for i in offer["items"]}
        assert all(i["quantity"] == 1 and i["reserved"] == 1 for i in actual)
        events = (
            await env[0].get(
                f"/api/v1/agent/runs/{second.json()['id']}/events",
                headers=buyer,
                params={"limit": 100},
            )
        ).json()["items"]
        assert "bundle_replanned" in {e["event_type"] for e in events}
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

        async with checkpoint_saver(env[3]) as saver:
            cp = await saver.aget_tuple(checkpoint_config(tid, done.json()["id"]))
            assert cp is not None and not cp.pending_writes
        restored = (await read(env, buyer, tid))["context"]
        assert restored["preferences"] == latest["preferences"]
    finally:
        await provider.close()


async def test_insufficient_budget_clears_offer_keeps_requirements_and_rejects_old_selection(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        result = await edit(env, buyer, tid, context, "总预算降低到1元。")
        assert result.status_code == 201, result.text
        current = (await read(env, buyer, tid))["context"]
        assert not current["bundles"] and len(current["preferences"]["bundle"]["parts"]) == 4
        assert current["bundle_status"]["status"] == "NO_FEASIBLE_BUNDLE"
        assert current["bundle_status"]["revision"]["new_total_cents"] is None
        stale = await edit(
            env, buyer, tid, current, "就买这套，每样一件，送演示宿舍。", bundle_id=old["bundle_id"]
        )
        assert stale.status_code == 409
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "mutation",
    ["active=false", "on_hand=reserved", "price_cents=999999,catalog_version=catalog_version+1"],
)
async def test_reused_sku_is_revalidated_not_silently_replaced(
    durable_env, buyer, tmp_path, mutation
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        monitor = next(i for i in old["items"] if i["category"] == "monitor")
        with env[1].begin() as c:
            c.execute(
                text("UPDATE products SET " + mutation + " WHERE id=:id"), {"id": monitor["id"]}
            )
        response = await edit(env, buyer, tid, context, "显示器不要换。")
        assert response.status_code == 201, response.text
        current = (await read(env, buyer, tid))["context"]
        assert not current["bundles"] and current["bundle_status"]["status"] == "NO_FEASIBLE_BUNDLE"
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
        assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 0
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "operations",
    [
        [
            {"operation_type": "REMOVE", "target_category": "keyboard"},
            {"operation_type": "KEEP", "target_category": "keyboard"},
        ],
        [{"operation_type": "ADD", "target_category": "monitor"}],
        [
            {"operation_type": "REMOVE", "target_category": "monitor"},
            {"operation_type": "REMOVE", "target_category": "mouse"},
            {"operation_type": "REMOVE", "target_category": "headphones"},
        ],
        [
            {"operation_type": "ADD", "target_category": "speaker"},
            {"operation_type": "ADD", "target_category": "camera"},
        ],
        [
            {"operation_type": "KEEP", "target_category": "monitor"},
            {
                "operation_type": "SET_CONSTRAINT",
                "target_category": "monitor",
                "new_constraints": {"screen_inches": "32"},
            },
        ],
    ],
)
async def test_conflicting_structured_delta_rolls_back_all_context_changes(
    durable_env, buyer, tmp_path, operations
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        body = {
            "source_bundle_id": old["bundle_id"],
            "expected_context_version": context["version"],
            "operations": operations,
        }
        response = await edit(env, buyer, tid, context, "应用组合修改", bundle_revision=body)
        assert response.status_code == 409, response.text
        assert (await read(env, buyer, tid))["context"] == context
        assert (
            row(env[1], "SELECT count(*) n FROM agent_candidate_sets WHERE kind='bundle'")["n"] == 1
        )
    finally:
        await provider.close()


async def test_structured_delta_scope_stale_version_and_text_ambiguity(
    durable_env, buyer, buyer2, tmp_path
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        body = {
            "source_bundle_id": old["bundle_id"],
            "expected_context_version": context["version"],
            "operations": [
                {
                    "operation_type": "UPDATE_QUANTITY",
                    "target_category": "headphones",
                    "requested_quantity": 2,
                },
                {"operation_type": "UPDATE_BUDGET", "budget_cents": 600001},
            ],
        }
        cross = await edit(env, buyer2, tid, context, "应用组合修改", bundle_revision=body)
        assert cross.status_code == 404
        other = await thread(env, buyer)
        foreign = await turn(env, buyer, other, "应用组合修改", 0, bundle_revision=body)
        assert foreign.status_code == 409
        for text_value in [
            "显示器换个更好的。",
            "键盘必须支持神奇协议。",
            "耳机换便宜的，就买这套。",
            "那个不要了。",
        ]:
            response = await edit(env, buyer, tid, context, text_value)
            assert response.status_code == 409, response.text
            assert (await read(env, buyer, tid))["context"] == context
        ok = await edit(env, buyer, tid, context, "应用组合修改", bundle_revision=body)
        assert ok.status_code == 201, ok.text
        current = (await read(env, buyer, tid))["context"]
        assert current["preferences"]["bundle"]["budget_cents"] == 600001
        assert {i["category"]: i["quantity"] for i in current["bundles"][0]["items"]} == {
            "monitor": 1,
            "keyboard": 1,
            "mouse": 1,
            "headphones": 2,
        }
        stale = await edit(env, buyer, tid, context, "不要鼠标了。")
        assert stale.status_code == 409 and stale.json()["code"] == "STALE_CONTEXT"
        assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    finally:
        await provider.close()


async def test_failed_replan_can_be_revised_without_buying_historical_source(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        first = await edit(env, buyer, tid, context, "总预算降低到1元。")
        assert first.status_code == 201
        current = (await read(env, buyer, tid))["context"]
        assert current["bundles"] == []
        second = await edit(env, buyer, tid, current, "总预算提高到6000元。")
        assert second.status_code == 201, second.text
        restored = (await read(env, buyer, tid))["context"]
        assert len(restored["bundles"]) == 1
        assert restored["bundles"][0]["bundle_id"] != old["bundle_id"]
        assert restored["preferences"]["bundle"]["budget_cents"] == 600000
    finally:
        await provider.close()


def test_cheaper_predicate_survives_a_separate_price_constraint_regardless_of_order():
    from agentmall.agents.bundle_contracts import parse_bundle
    from agentmall.agents.bundle_revision import BundleOperation, apply_revision

    spec = parse_bundle("预算5000元，组合键盘和耳机，不要购买。")
    items = [
        {"category": "keyboard", "id": str(uuid4()), "price_cents": 10000},
        {"category": "headphones", "id": str(uuid4()), "price_cents": 12000},
    ]
    ops = [
        BundleOperation(operation_type="REPLACE", target_category="headphones", cheaper=True),
        BundleOperation(
            operation_type="SET_CONSTRAINT",
            target_category="headphones",
            new_constraints={"max_price_cents": 50000},
        ),
    ]
    for operations in [ops, list(reversed(ops))]:
        new, _, _ = apply_revision(spec, items, operations)
        assert (
            next(p for p in new.parts if p.category == "headphones").requirements.max_price_cents
            == 11999
        )


async def test_failed_add_replacement_obligations_survive_budget_only_recovery(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        response = await edit(
            env, buyer, tid, context, "耳机换一个，再加一个音箱，总预算降低到1元。"
        )
        assert response.status_code == 201, response.text
        failed = (await read(env, buyer, tid))["context"]
        assert not failed["bundles"]
        changes = failed["bundle_status"]["revision"]["changes"]
        assert {c["category"] for c in changes} == {
            "monitor",
            "keyboard",
            "mouse",
            "headphones",
            "speaker",
        }
        assert next(c for c in changes if c["category"] == "speaker")["status"] == "UNRESOLVED"
        recovery = await edit(env, buyer, tid, failed, "总预算提高到6000元。")
        assert recovery.status_code == 201, recovery.text
        current = (await read(env, buyer, tid))["context"]
        assert len(current["bundles"]) == 1
        offer = current["bundles"][0]
        assert (
            next(i for i in offer["items"] if i["category"] == "headphones")["id"]
            != next(i for i in old["items"] if i["category"] == "headphones")["id"]
        )
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    finally:
        await provider.close()


async def test_typed_edit_cannot_ignore_an_unparsed_hard_specification(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        body = {
            "source_bundle_id": old["bundle_id"],
            "expected_context_version": context["version"],
            "operations": [{"operation_type": "KEEP", "target_category": "monitor"}],
        }
        response = await edit(env, buyer, tid, context, "耳机要防水", bundle_revision=body)
        assert response.status_code == 409, response.text
        assert (await read(env, buyer, tid))["context"] == context
    finally:
        await provider.close()


async def test_concurrent_revision_requests_accept_only_one_context_version(
    durable_env, buyer, tmp_path
):
    import asyncio

    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        results = await asyncio.gather(
            edit(env, buyer, tid, context, "不要鼠标了。"),
            edit(env, buyer, tid, context, "总预算提高到6000元。"),
        )
        assert sorted(r.status_code for r in results) == [201, 409]
        assert (
            row(env[1], "SELECT count(*) n FROM agent_candidate_sets WHERE kind='bundle'")["n"] == 2
        )
        assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 2
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    finally:
        await provider.close()


async def test_reassigned_store_cannot_use_original_thread_bundle(durable_env, buyer, tmp_path):
    env = durable_env
    provider, program, tid, context, old = await initial(env, buyer, tmp_path)
    try:
        # Existing Store row from another owner's fixture is not needed: ownership
        # rejects before candidate reading when this Thread's Store differs.
        with env[1].begin() as c:
            c.execute(
                text("UPDATE agent_threads SET store_id=:store WHERE id=:id"),
                {"store": str(uuid4()), "id": tid},
            )
        response = await edit(env, buyer, tid, context, "不要鼠标了。")
        assert response.status_code == 404
        assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 0
    finally:
        await provider.close()
