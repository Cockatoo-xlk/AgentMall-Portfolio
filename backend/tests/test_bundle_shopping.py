"""Bundle recommendations and authorization over real owned PostgreSQL fixtures."""

from uuid import uuid4

import pytest
from bundle_helpers import install_bundle_sdk
from conftest import row
from t09_helpers import confirm, resume, thread
from t09_helpers import durable_env as durable_env
from test_thread_memory import read, turn

from agentmall.agents.context import MultiRequest, user_constraints

MESSAGE = (
    "预算5000元，帮我搭配一套居家办公设备，包括27英寸显示器、无线键盘、"
    "鼠标和耳机。先推荐，不要购买。"
)


def test_bundle_request_keeps_scoped_requirements_and_global_budget():
    constraints = user_constraints(
        MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=MESSAGE)
    )
    bundle = getattr(constraints, "bundle", None)
    assert bundle is not None
    assert bundle.budget_cents == 500000
    parts = {p.category: p for p in bundle.parts}
    assert set(parts) == {"monitor", "keyboard", "mouse", "headphones"}
    assert parts["monitor"].requirements.screen_inches == "27"
    assert parts["keyboard"].requirements.connection == "无线"
    assert parts["mouse"].requirements.connection is None
    assert parts["headphones"].requirements.screen_inches is None
    assert constraints.max_price_cents is None
    assert constraints.purchase_requested is False


@pytest.mark.parametrize(
    "message",
    [
        "预算5000元，搭配一套显示器、键盘和打印机，不要购买。",
        "帮我搭配一套显示器和键盘，不要购买。",
        "预算5000元，搭配一套有线无线键盘和鼠标，不要购买。",
        "预算5000元，搭配一套显示器、键盘、鼠标、耳机、手机和平板，不要购买。",
        "预算5000元，组合500元以内200元以内键盘和鼠标，先推荐，不要购买。",
        "预算5000元，组合27英寸32英寸显示器和鼠标，先推荐，不要购买。",
        "预算5000元，全部无线，包括键盘和鼠标，不要购买。",
        "预算5000元，组合键盘和鼠标，先推荐打印机，不要购买。",
    ],
)
def test_unrepresentable_bundle_requirements_clarify_without_dropping_items(message):
    from agentmall.infra.errors import DomainError

    with pytest.raises(DomainError):
        user_constraints(MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=message))


def test_planner_uses_whole_budget_and_stable_id_ties_without_dropping_categories():
    from agentmall.agents.bundle_contracts import parse_bundle
    from agentmall.agents.bundle_planner import choose_bundle

    spec = parse_bundle("预算300元，组合无线键盘和鼠标，先推荐，不要购买。")

    def item(category, price, identifier):
        return dict(
            id=str(__import__("uuid").UUID(int=identifier)),
            name="合成" + category,
            category=category,
            attributes={"connection": "无线"},
            description="合成目录",
            price_cents=price,
            currency="CNY",
            available=5,
            catalog_version=1,
        )

    pools = {
        "keyboard": [item("keyboard", 20000, 2), item("keyboard", 20000, 1)],
        "mouse": [item("mouse", 15000, 3)],
    }
    assert choose_bundle(spec, pools)["status"] == "NO_FEASIBLE_BUNDLE"
    pools["mouse"].append(item("mouse", 9000, 4))
    result = choose_bundle(spec, pools)
    assert result["total_cents"] == 29000
    assert result["items"][0]["id"] == str(__import__("uuid").UUID(int=1))
    assert len(result["items"]) == 2
    assert choose_bundle(spec, {"keyboard": pools["keyboard"]})["missing_categories"] == ["mouse"]


@pytest.mark.parametrize("mode", ["multi", "single"])
async def test_expanded_bundle_recommend_checkout_and_replay(durable_env, buyer, tmp_path, mode):
    env = durable_env
    provider, program = await install_bundle_sdk(env, tmp_path / "mock")
    try:
        tid = await thread(env, buyer, mode)
        first = await turn(env, buyer, tid, MESSAGE, 0)
        assert first.status_code == 201, first.text
        assert first.json()["status"] == "COMPLETED", __import__("json").dumps(
            first.json(), ensure_ascii=False
        )
        view = (await read(env, buyer, tid))["context"]
        assert len(view["bundles"]) == 1, view
        bundle = view["bundles"][0]
        assert bundle["valid"] and len(bundle["items"]) == 4
        assert bundle["total_cents"] <= 500000
        assert {i["category"] for i in bundle["items"]} == {
            "monitor",
            "keyboard",
            "mouse",
            "headphones",
        }
        assert (
            next(i for i in bundle["items"] if i["category"] == "monitor")["attributes"][
                "screen_inches"
            ]
            == "27"
        )
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
        body = {
            "request_id": str(uuid4()),
            "message": "就买这套，每样一件，送演示宿舍。",
            "expected_context_version": view["version"],
        }
        response = await env[0].post(f"/api/v1/agent/threads/{tid}/runs", headers=buyer, json=body)
        assert response.status_code == 201, response.text
        waiting = response.json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
        pid = waiting["pending_confirmation"]["proposal_id"]
        proposal = (await env[0].get(f"/api/v1/proposals/{pid}", headers=buyer)).json()
        assert len(proposal["canonical_payload"]["items"]) == 4, proposal
        assert proposal["canonical_payload"]["total_cents"] == bundle["total_cents"]
        from sqlalchemy import text

        with env[1].connect() as conn:
            before = {
                str(r["id"]): (r["on_hand"], r["reserved"])
                for r in conn.execute(text("SELECT id,on_hand,reserved FROM products")).mappings()
            }
        cid = await confirm(env, buyer, pid)
        rid = str(uuid4())
        done = await resume(env, buyer, tid, waiting, cid, rid)
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "COMPLETED", done.json()
        assert (await resume(env, buyer, tid, waiting, cid, rid)).json() == done.json()
        order = row(env[1], "SELECT id,status,total_cents FROM orders")
        assert (
            order["status"] == "PENDING_PAYMENT" and order["total_cents"] == bundle["total_cents"]
        )
        assert row(env[1], "SELECT count(*) AS n FROM order_items")["n"] == 4
        assert row(env[1], "SELECT count(*) AS n FROM payments")["n"] == 0
        assert (
            row(env[1], "SELECT count(*) AS n FROM confirmations WHERE consumed_at IS NOT NULL")[
                "n"
            ]
            == 1
        )
        selected = {i["id"] for i in bundle["items"]}
        with env[1].connect() as conn:
            from sqlalchemy import text

            for r in conn.execute(text("SELECT id,on_hand,reserved FROM products")).mappings():
                old = before[str(r["id"])]
                assert (r["on_hand"], r["reserved"]) == (
                    old[0],
                    old[1] + (1 if str(r["id"]) in selected else 0),
                )
        events = (
            await env[0].get(f"/api/v1/agent/runs/{first.json()['id']}/events", headers=buyer)
        ).json()["items"]
        assert any(e["event_type"] == "bundle_computed" for e in events)
        from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

        async with checkpoint_saver(env[3]) as saver:
            saved = await saver.aget_tuple(checkpoint_config(tid, waiting["id"]))
            assert saved and saved.checkpoint["channel_values"]["next"] == "done"
            assert not saved.pending_writes
        with env[1].connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                execution = (
                    conn.execute(
                        text(
                            "SELECT action_id, result FROM idempotency_requests "
                            "WHERE operation='execute_checkout' AND completed_at IS NOT NULL"
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(execution) == 1 and str(execution[0]["action_id"]) == pid
                assert execution[0]["result"]["order_id"] == str(order["id"])
                sequences = (
                    conn.execute(
                        text(
                            "SELECT run_id,count(*) AS n,min(seq) AS first,max(seq) AS last "
                            "FROM run_events GROUP BY run_id"
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(sequences) == 2 and all(
                    s["first"] == 1 and s["last"] == s["n"] for s in sequences
                )
        import json
        import os
        from pathlib import Path

        if output := os.environ.get("AGENTMALL_BUNDLE_EVIDENCE_DIR"):
            target = Path(output)
            import asyncio

            await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True, mode=0o700)
            receipt = {
                "mode": mode,
                "model": "MOCK_TRANSPORT",
                "embedding": "FIXTURE",
                "catalog_skus": 120,
                "bundle": bundle,
                "order": dict(order),
                "orders": 1,
                "order_items": 4,
                "payments": 0,
                "consumed_confirmations": 1,
                "replay_did_not_duplicate": True,
                "all_inventory_checked": True,
                "idempotency_receipts": len(execution),
                "events": [dict(s) for s in sequences],
                "checkpoint_next": "done",
                "pending_writes": 0,
                "provider_requests": 0,
            }
            await asyncio.to_thread(
                (target / f"bundle-{mode}.json").write_text,
                json.dumps(receipt, default=str, ensure_ascii=False, indent=2) + "\n",
            )
    finally:
        await provider.close()


async def offered(env, buyer, tmp_path, message=MESSAGE):
    provider, program = await install_bundle_sdk(env, tmp_path / uuid4().hex)
    tid = await thread(env, buyer)
    response = await turn(env, buyer, tid, message, 0)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "COMPLETED", response.json()
    return provider, program, tid, (await read(env, buyer, tid))["context"]


async def test_no_feasible_complete_bundle_has_no_partial_purchase(durable_env, buyer, tmp_path):
    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path, MESSAGE.replace("5000元", "1元"))
    try:
        assert view["bundles"] == []
        assert view["bundle_status"]["status"] == "NO_FEASIBLE_BUNDLE"
        assert view["bundle_status"]["minimum_retrieved_total_cents"] > 100
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
    finally:
        await provider.close()


@pytest.mark.parametrize("mutation", ["price", "stock", "version", "inactive", "expired"])
async def test_old_bundle_rejected_before_any_proposal(durable_env, buyer, tmp_path, mutation):
    from sqlalchemy import text

    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        bundle = view["bundles"][0]
        with env[1].begin() as conn:
            if mutation == "expired":
                conn.execute(
                    text(
                        "UPDATE agent_candidate_sets SET details=jsonb_set(details,'{expires_at}',"
                        "to_jsonb('2000-01-01T00:00:00+00:00'::text)) WHERE id=:id"
                    ),
                    {"id": bundle["bundle_id"]},
                )
            else:
                assignment = {
                    "price": "price_cents=99999999",
                    "stock": "on_hand=reserved",
                    "version": "catalog_version=catalog_version+1",
                    "inactive": "active=false",
                }[mutation]
                conn.execute(
                    text(f"UPDATE products SET {assignment} WHERE id=:id"),
                    {"id": bundle["items"][0]["id"]},
                )
        response = await turn(env, buyer, tid, "就买这套，每样一件，送演示宿舍。", view["version"])
        assert response.status_code == (404 if mutation == "inactive" else 409), response.text
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
        assert not (await read(env, buyer, tid))["context"]["bundles"][0]["valid"]
    finally:
        await provider.close()


@pytest.mark.parametrize("mutation", ["stock", "price", "rollback"])
async def test_one_changed_item_or_database_failure_rolls_back_entire_bundle(
    durable_env, buyer, tmp_path, monkeypatch, mutation
):
    from sqlalchemy import text

    from agentmall.orders import service as order_service

    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        waiting = (
            await turn(env, buyer, tid, "就买这套，每样一件，送演示宿舍。", view["version"])
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        bundle = view["bundles"][0]
        if mutation == "rollback":

            async def fail(*args, **kwargs):
                raise RuntimeError("synthetic pre-commit failure")

            monkeypatch.setattr(order_service, "write_order_event", fail)
        else:
            assignment = (
                "on_hand=reserved"
                if mutation == "stock"
                else "price_cents=price_cents+1, catalog_version=catalog_version+1"
            )
            with env[1].begin() as conn:
                conn.execute(
                    text(f"UPDATE products SET {assignment} WHERE id=:id"),
                    {"id": bundle["items"][-1]["id"]},
                )
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        result = await resume(env, buyer, tid, waiting, cid)
        assert result.status_code == 200, result.text
        assert result.json()["status"] != "COMPLETED", result.json()
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
        assert row(env[1], "SELECT sum(reserved) AS n FROM products")["n"] == 0
        assert (
            row(env[1], "SELECT count(*) AS n FROM confirmations WHERE consumed_at IS NOT NULL")[
                "n"
            ]
            == 0
        )
        assert row(env[1], "SELECT count(*) AS n FROM payments")["n"] == 0
    finally:
        await provider.close()


async def test_bundle_scope_ambiguity_quantities_and_context_version(
    durable_env, buyer, buyer2, tmp_path
):
    from sqlalchemy import text

    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        bid = view["bundles"][0]["bundle_id"]
        assert (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer2)).status_code == 404
        for message, extra in [
            ("就买这套，送演示宿舍。", {}),
            ("就买这套，每样一件。", {}),
            ("不要购买这套，每样一件，送演示宿舍。", {"bundle_id": bid}),
            (
                "就买这套，每样两件，送演示宿舍。",
                {"bundle_quantities": {"keyboard": 1, "mouse": 1, "monitor": 1, "headphones": 1}},
            ),
            ("就买这套，每样一件，送演示宿舍。", {"expected_context_version": view["version"] - 1}),
        ]:
            version = extra.pop("expected_context_version", view["version"])
            response = await turn(env, buyer, tid, message, version, **extra)
            assert response.status_code == 409, response.text
        # Two offered snapshots require explicit selection; never pick the first.
        duplicate = str(uuid4())
        with env[1].begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_candidate_sets "
                    "(id,thread_id,run_id,preferences_digest,items,kind,details) "
                    "SELECT :new,thread_id,run_id,preferences_digest,items,kind,details "
                    "FROM agent_candidate_sets WHERE id=:old"
                ),
                {"new": duplicate, "old": bid},
            )
            conn.execute(
                text(
                    "UPDATE agent_thread_contexts SET offered_ids=cast(:ids AS jsonb) "
                    "WHERE thread_id=:tid"
                ),
                {"ids": __import__("json").dumps([bid, duplicate]), "tid": tid},
            )
        response = await turn(env, buyer, tid, "就买这套，每样一件，送演示宿舍。", view["version"])
        assert (
            response.status_code == 409 and response.json()["code"] == "BUNDLE_SELECTION_REQUIRED"
        ), response.text
        response = await turn(env, buyer, tid, "买那个，每样一件，送演示宿舍。", view["version"])
        assert response.status_code == 409, response.text
        other = await thread(env, buyer)
        assert (
            await turn(env, buyer, other, "就买这套，每样一件，送演示宿舍。", 0, bundle_id=bid)
        ).status_code == 409
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
    finally:
        await provider.close()


async def test_model_cannot_add_skus_or_prepare_single_checkout_in_bundle(
    durable_env, buyer, tmp_path
):
    from types import SimpleNamespace

    from agentmall.agents.bundle_tools import prepare
    from agentmall.agents.context import Constraints, HandoffEnvelope
    from agentmall.agents.specialist_tools import SpecialistTools
    from agentmall.infra.errors import DomainError

    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        envelope = HandoffEnvelope(
            subtask_id="hostile",
            target="order",
            goal="prepare_checkout",
            read_only=False,
            constraints=Constraints(
                bundle=user_constraints(
                    MultiRequest(request_id=uuid4(), thread_id=uuid4(), message=MESSAGE)
                ).bundle
            ),
            remaining_budget=__import__("agentmall.agents.budgets", fromlist=["GraphBudget"])
            .GraphBudget()
            .snapshot(),
        )
        # Actual strict tool schema rejects model-supplied SKU lists and quantities.
        from pydantic import ValidationError

        from agentmall.agents.specialist_tools import BundlePrepareInput

        with pytest.raises(ValidationError):
            BundlePrepareInput.model_validate(
                {
                    "bundle_id": view["bundles"][0]["bundle_id"],
                    "items": [{"product_id": str(uuid4()), "quantity": 1}],
                }
            )
        fake = SimpleNamespace(
            constraints=envelope.constraints,
            thread_snapshot={"selected_bundle": {"bundle_id": view["bundles"][0]["bundle_id"]}},
            checkout_blocker=lambda: "PURCHASE_NOT_REQUESTED",
        )
        with pytest.raises(DomainError):
            await prepare(
                SpecialistTools(fake, envelope),
                BundlePrepareInput(bundle_id=view["bundles"][0]["bundle_id"]),
            )
        # Foreign scope cannot validate even if supplied a correct item snapshot/hash.
        from agentmall.agents.bundle_planner import verify_bundle
        from agentmall.agents.models import CandidateSet

        async with env[2].state.sessions.begin() as session:
            from sqlalchemy import select

            from agentmall.identity.models import User
            from agentmall.identity.service import actor_for

            actor = actor_for(
                await session.scalar(select(User).where(User.login == "buyer1")), env[3]
            )
            record = await session.get(CandidateSet, view["bundles"][0]["bundle_id"])
            with pytest.raises(DomainError):
                await verify_bundle(
                    session, actor, record.items, {**record.details, "store_id": str(uuid4())}
                )
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
    finally:
        await provider.close()


async def test_competing_confirmations_reserve_all_or_nothing(durable_env, buyer, tmp_path):
    import asyncio

    from sqlalchemy import text

    env = durable_env
    provider, _ = await install_bundle_sdk(env, tmp_path / "concurrency")
    try:
        waits = []
        for _ in range(2):
            tid = await thread(env, buyer)
            first = await turn(env, buyer, tid, MESSAGE, 0)
            assert first.json()["status"] == "COMPLETED", first.json()
            view = (await read(env, buyer, tid))["context"]
            waiting = (
                await turn(env, buyer, tid, "就买这套，每样一件，送演示宿舍。", view["version"])
            ).json()
            assert waiting["status"] == "WAITING_INPUT", waiting
            cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
            waits.append((tid, waiting, cid))
        # Both proposals quote the same bounded, deterministically selected SKU set.
        ids = [i["id"] for i in view["bundles"][0]["items"]]
        with env[1].begin() as conn:
            conn.execute(
                text("UPDATE products SET on_hand=reserved+1 WHERE id=ANY(cast(:ids AS uuid[]))"),
                {"ids": ids},
            )
        results = await asyncio.gather(*(resume(env, buyer, *w) for w in waits))
        assert all(r.status_code == 200 for r in results), [r.text for r in results]
        assert sorted(r.json()["status"] for r in results) == ["COMPLETED", "PARTIAL"]
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 1
        assert row(env[1], "SELECT count(*) AS n FROM order_items")["n"] == 4
        assert row(env[1], "SELECT sum(reserved) AS n FROM products")["n"] == 4
        assert (
            row(env[1], "SELECT count(*) AS n FROM confirmations WHERE consumed_at IS NOT NULL")[
                "n"
            ]
            == 1
        )
        assert row(env[1], "SELECT count(*) AS n FROM payments")["n"] == 0
    finally:
        await provider.close()


async def test_five_categories_and_explicit_quantities_use_same_atomic_checkout(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, _, tid, view = await offered(
        env,
        buyer,
        tmp_path,
        "预算20000元，组合手机、显示器、无线键盘、鼠标和耳机，每样两件，先推荐，不要购买。",
    )
    try:
        bundle = view["bundles"][0]
        assert len(bundle["items"]) == 5 and all(i["quantity"] == 2 for i in bundle["items"])
        waiting = (
            await turn(env, buyer, tid, "就买这套，每样两件，送演示宿舍。", view["version"])
        ).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        cid = await confirm(env, buyer, waiting["pending_confirmation"]["proposal_id"])
        done = await resume(env, buyer, tid, waiting, cid)
        assert done.json()["status"] == "COMPLETED", done.json()
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 1
        assert row(env[1], "SELECT sum(quantity) AS n FROM order_items")["n"] == 10
        assert row(env[1], "SELECT sum(reserved) AS n FROM products")["n"] == 10
    finally:
        await provider.close()


async def test_bundle_updates_clear_and_replay_never_inherit_purchase_grant(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        response = await turn(env, buyer, tid, "改成有线的，预算6000元。", view["version"])
        assert response.status_code == 409, response.text
        assert (await read(env, buyer, tid))["context"]["version"] == view["version"]
        # An explicit budget-only replacement invalidates the old visible bundle.
        rid = str(uuid4())
        body = {
            "request_id": rid,
            "message": "预算提高到6000元，重新推荐，不要购买。",
            "expected_context_version": view["version"],
        }
        response = await env[0].post(f"/api/v1/agent/threads/{tid}/runs", headers=buyer, json=body)
        assert response.json()["status"] == "COMPLETED", response.text
        after = (await read(env, buyer, tid))["context"]
        assert after["preferences"]["bundle"]["budget_cents"] == 600000
        assert after["bundles"][0]["bundle_id"] != view["bundles"][0]["bundle_id"]
        assert (
            await env[0].post(f"/api/v1/agent/threads/{tid}/runs", headers=buyer, json=body)
        ).json() == response.json()
        assert (await read(env, buyer, tid))["context"]["version"] == after["version"]
        stale = await turn(
            env,
            buyer,
            tid,
            "就买这套，每样一件，送演示宿舍。",
            after["version"],
            bundle_id=view["bundles"][0]["bundle_id"],
        )
        assert stale.status_code == 409, stale.text
        patch = await env[0].patch(
            f"/api/v1/agent/threads/{tid}/context",
            headers=buyer,
            json={
                "request_id": str(uuid4()),
                "expected_version": after["version"],
                "operations": [{"op": "CLEAR", "field": "bundle"}],
            },
        )
        assert patch.status_code == 200, patch.text
        assert not (await read(env, buyer, tid))["context"]["preferences"]
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "extra",
    [
        {"message": "就买这套，每样一件，送演示宿舍，500元以内。"},
        {"message": "就买这套，每样一件，送演示宿舍，必须87键。"},
        {"message": "就买这套，每样一件，送演示宿舍，必须薄膜。"},
        {"message": "就买这套，每样一件，送演示宿舍，必须旗舰CPU。"},
        {"constraints": {"max_price_cents": 50000}},
        {"constraints": {"product_needs": {"layout": "87键"}}},
        {"constraints": {"quantity": 2}},
        {"constraints": {"address_label": "demo_home"}},
    ],
)
async def test_purchase_cannot_drop_new_hard_requirements(durable_env, buyer, tmp_path, extra):
    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        body = {
            "request_id": str(uuid4()),
            "message": "就买这套，每样一件，送演示宿舍。",
            "expected_context_version": view["version"],
            **extra,
        }
        response = await env[0].post(f"/api/v1/agent/threads/{tid}/runs", headers=buyer, json=body)
        assert response.status_code == 409, response.text
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
    finally:
        await provider.close()


async def test_clarification_invalidates_old_composition_before_new_retrieval(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, program = await install_bundle_sdk(env, tmp_path / "clarification")
    program.clarify_budget = 500000
    try:
        tid = await thread(env, buyer)
        waiting = (await turn(env, buyer, tid, MESSAGE, 0)).json()
        assert waiting["status"] == "WAITING_INPUT", waiting
        assert waiting["pending_confirmation"]["type"] == "clarification"
        body = {
            "request_id": str(uuid4()),
            "run_id": waiting["id"],
            "interrupt_id": waiting["pending_confirmation"]["interrupt_id"],
            "clarification": "预算提高到6000元，重新推荐，不要购买。",
        }
        response = await env[0].post(
            f"/api/v1/agent/threads/{tid}/resume", headers=buyer, json=body
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "COMPLETED", response.json()
        context = (await read(env, buyer, tid))["context"]
        assert context["bundle_status"]["budget_cents"] == 600000, context
        assert context["bundles"] and all(b["budget_cents"] == 600000 for b in context["bundles"])
        assert all(p["status"] == "done" for p in response.json()["result"]["results"])
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
    finally:
        await provider.close()


def test_checkpoint_delta_persists_invalidated_maps_without_changing_other_fields():
    from agentmall.agents.state import delta, merge_state

    before = {
        "facts": {"old": {"price": 1}},
        "candidate_lists": {"old": {}},
        "references": {"old": {}},
        "errors": [],
        "pending": {},
        "completed": {},
    }
    after = {**before, "facts": {"new": {"price": 2}}, "candidate_lists": {}, "references": {}}
    patch = delta(before, after)
    assert merge_state(before, patch) == after
    assert merge_state(before, patch) == merge_state(merge_state(before, patch), patch)


async def test_zero_budget_update_is_rejected_before_any_context_or_run_write(
    durable_env, buyer, tmp_path
):
    env = durable_env
    provider, _, tid, view = await offered(env, buyer, tmp_path)
    try:
        response = await turn(env, buyer, tid, "预算0元。", view["version"])
        assert response.status_code == 409, response.text
        assert (await read(env, buyer, tid))["context"] == view
        assert row(env[1], "SELECT count(*) AS n FROM agent_runs")["n"] == 1
        assert row(env[1], "SELECT count(*) AS n FROM agent_runs WHERE status='RUNNING'")["n"] == 0
    finally:
        await provider.close()


@pytest.mark.parametrize("message", ["预算提高到6000", "预算五千元"])
def test_unparsed_budget_never_silently_keeps_old_amount(message):
    from agentmall.agents.bundle_contracts import budget_in_text
    from agentmall.infra.errors import DomainError

    with pytest.raises(DomainError):
        budget_in_text(message)


def test_legacy_single_tool_allowlist_excludes_bundle_tools():
    from types import SimpleNamespace

    from agentmall.agents.context import Constraints
    from agentmall.agents.runtime import RunContext
    from agentmall.agents.specialist_tools import ALLOWLISTS

    names = RunContext.tool_allowlist(
        SimpleNamespace(single=True, constraints=Constraints()), "order"
    )
    assert set(names) == {name for allowed in ALLOWLISTS.values() for name in allowed}
    assert "retrieve_bundle_candidates" not in names and "prepare_bundle_checkout" not in names


async def test_actual_mock_tool_cannot_purchase_an_unselected_bundle(durable_env, buyer, tmp_path):
    env = durable_env
    provider, program, tid, view = await offered(env, buyer, tmp_path)
    program.purchase_bundle_id = str(uuid4())
    try:
        result = await turn(env, buyer, tid, "就买这套，每样一件，送演示宿舍。", view["version"])
        assert result.status_code == 201, result.text
        assert result.json()["status"] == "PARTIAL", result.json()
        assert "BUNDLE_SELECTION_REQUIRED" in result.json()["result"]["error_codes"]
        assert row(env[1], "SELECT count(*) AS n FROM action_proposals")["n"] == 0
        assert row(env[1], "SELECT count(*) AS n FROM orders")["n"] == 0
        assert row(env[1], "SELECT sum(reserved) AS n FROM products")["n"] == 0
    finally:
        await provider.close()
