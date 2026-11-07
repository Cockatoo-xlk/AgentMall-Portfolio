"""T16: real PostgreSQL context receipts, never model-authored preference state."""

from uuid import uuid4

import pytest
from conftest import row
from multiagent_helpers import ai, call, final, install, make_models, route
from t09_helpers import durable_env as durable_env
from t09_helpers import thread


async def read(env, buyer, tid):
    response = await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)
    assert response.status_code == 200, response.text
    return response.json()


async def turn(env, buyer, tid, message, version, **extra):
    return await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "message": message,
            "expected_context_version": version,
            **extra,
        },
    )


async def test_budget_replace_clear_and_old_run_snapshot_are_independent(durable_env, buyer):
    env = durable_env
    await install(
        env,
        make_models(
            supervisor=[route("shopping", "find_products", "initial"), *[route("finish")] * 3],
            shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        ),
    )
    tid = await thread(env, buyer)
    first = await turn(env, buyer, tid, "推荐一款300元以内的静音键盘", 0)
    assert first.status_code == 201, first.text
    original = first.json()
    assert original["status"] == "COMPLETED", original
    context = (await read(env, buyer, tid))["context"]
    assert context["preferences"] == {
        "category": "keyboard",
        "max_price_cents": 30000,
        "noise_preference": "quiet",
    }
    second = await turn(env, buyer, tid, "改成无线的，预算提高到400元", context["version"])
    assert second.status_code == 201, second.text
    context = (await read(env, buyer, tid))["context"]
    assert context["preferences"]["max_price_cents"] == 40000
    assert context["preferences"]["product_needs"]["connection"] == "无线"
    assert second.json()["constraints"]["noise_preference"] == "quiet"
    third = await turn(env, buyer, tid, "忘记之前的预算，不要无线了", context["version"])
    assert third.status_code == 201, third.text
    context = (await read(env, buyer, tid))["context"]
    assert "max_price_cents" not in context["preferences"]
    assert not context["preferences"].get("product_needs", {}).get("connection")
    old = next(r for r in (await read(env, buyer, tid))["runs"] if r["id"] == original["id"])
    assert old["context_snapshot"] == original["context_snapshot"]
    assert old["constraints"]["max_price_cents"] == 30000

    # A genuine clarification updates structured state, not concatenated old monetary prose.
    await install(env, make_models(supervisor=[route("clarify"), route("finish")]), indexed=False)
    clarified_tid = await thread(env, buyer)
    waiting = (await turn(env, buyer, clarified_tid, "准备购买预算200元静音键盘", 0)).json()
    assert waiting["pending_confirmation"]["type"] == "clarification"
    busy = await env[0].patch(
        f"/api/v1/agent/threads/{clarified_tid}/context",
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "operations": [{"op": "CLEAR", "field": "max_price_cents"}],
        },
    )
    assert busy.status_code == 409 and busy.json()["code"] == "THREAD_BUSY"
    body = {
        "request_id": str(uuid4()),
        "run_id": waiting["id"],
        "interrupt_id": waiting["pending_confirmation"]["interrupt_id"],
        "clarification": "预算提高到300元",
    }
    done = await env[0].post(
        f"/api/v1/agent/threads/{clarified_tid}/resume", headers=buyer, json=body
    )
    assert done.status_code == 200, done.text
    assert done.json()["constraints"]["max_price_cents"] == 30000
    assert done.json()["constraints"]["purchase_requested"] is True
    assert done.json()["context_snapshot"]["constraints"]["max_price_cents"] == 20000
    assert (await read(env, buyer, clarified_tid))["context"]["preferences"][
        "max_price_cents"
    ] == 30000
    assert (
        await env[0].post(f"/api/v1/agent/threads/{clarified_tid}/resume", headers=buyer, json=body)
    ).json() == done.json()


async def test_replay_does_not_reapply_memory_and_stale_tab_cannot_overwrite(durable_env, buyer):
    env = durable_env
    await install(env, make_models(supervisor=[route("finish")] * 2), indexed=False)
    tid = await thread(env, buyer)
    rid = str(uuid4())
    first = await turn(env, buyer, tid, "键盘预算300元", 0, request_id=rid)
    assert first.status_code == 201, first.text
    before = (await read(env, buyer, tid))["context"]
    replay = await turn(env, buyer, tid, "键盘预算300元", 0, request_id=rid)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert (await read(env, buyer, tid))["context"] == before
    stale = await turn(env, buyer, tid, "预算400元", 0)
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_CONTEXT"
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 1


async def test_context_patch_idempotence_and_owner_isolation(durable_env, buyer, buyer2):
    env = durable_env
    tid = await thread(env, buyer)
    body = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "operations": [{"op": "SET", "field": "max_price_cents", "value": 40000}],
    }
    url = f"/api/v1/agent/threads/{tid}/context"
    denied = await env[0].patch(url, headers=buyer2, json=body)
    assert denied.status_code == 404
    assert (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer2)).status_code == 404
    first = await env[0].patch(url, headers=buyer, json=body)
    assert first.status_code == 200, first.text
    assert (await env[0].patch(url, headers=buyer, json=body)).json() == first.json()
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 0
    other = await thread(env, buyer)
    assert (await read(env, buyer, other))["context"]["preferences"] == {}


@pytest.mark.parametrize("message", ["预算300元，不超过400元", "有线键盘，还要无线键盘"])
async def test_same_message_contradiction_never_updates_context(durable_env, buyer, message):
    env = durable_env
    tid = await thread(env, buyer)
    response = await turn(env, buyer, tid, message, 0)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "CONTEXT_CLARIFICATION_REQUIRED"
    assert (await read(env, buyer, tid))["context"]["version"] == 0
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 0


async def test_patch_rejects_authorization_fields_and_preserves_other_nested_preferences(
    durable_env, buyer
):
    env = durable_env
    tid = await thread(env, buyer)
    url = f"/api/v1/agent/threads/{tid}/context"
    body = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "operations": [
            {"op": "SET", "field": "connection", "value": "无线"},
            {"op": "SET", "field": "layout", "value": "87键"},
        ],
    }
    first = await env[0].patch(url, headers=buyer, json=body)
    assert first.status_code == 200, first.text
    cleared = await env[0].patch(
        url,
        headers=buyer,
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "operations": [{"op": "CLEAR", "field": "connection"}],
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["preferences"] == {"product_needs": {"layout": "87键"}}
    for field in ("purchase_requested", "confirmation_id", "actor_id", "store_id"):
        invalid = await env[0].patch(
            url,
            headers=buyer,
            json={
                "request_id": str(uuid4()),
                "expected_version": 2,
                "operations": [{"op": "SET", "field": field, "value": "synthetic"}],
            },
        )
        assert invalid.status_code == 422
    assert (await read(env, buyer, tid))["context"]["version"] == 2


async def test_model_disabled_keeps_explicit_preference_but_no_candidates_or_orders(
    durable_env, buyer
):
    env = durable_env
    tid = await thread(env, buyer)
    result = await turn(env, buyer, tid, "推荐300元以内静音键盘", 0)
    assert result.status_code == 201, result.text
    assert result.json()["last_error"] == "MODEL_DISABLED"
    context = (await read(env, buyer, tid))["context"]
    assert context["preferences"]["max_price_cents"] == 30000
    assert context["candidate_sets"] == []
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0


async def test_store_scope_cannot_read_or_mutate_another_thread_context(durable_env, buyer):
    from uuid import UUID

    from retrieval_helpers import actor

    from agentmall.agents.memory import patch_context
    from agentmall.agents.run_schemas import ContextPatch
    from agentmall.agents.run_service import get_thread
    from agentmall.infra.errors import DomainError

    env = durable_env
    tid = await thread(env, buyer)
    foreign = actor(env[3], store=uuid4())
    with pytest.raises(DomainError) as denied:
        await get_thread(env[2], foreign, UUID(tid))
    assert denied.value.status == 404
    with pytest.raises(DomainError) as denied:
        await patch_context(
            env[2],
            foreign,
            UUID(tid),
            ContextPatch(
                request_id=uuid4(),
                expected_version=0,
                operations=[{"op": "SET", "field": "max_price_cents", "value": 40000}],
            ),
        )
    assert denied.value.status == 404
    assert (await read(env, buyer, tid))["context"]["version"] == 0


async def test_legacy_client_cannot_guess_ordinal_or_send_unbound_candidate(durable_env, buyer):
    env = durable_env
    tid = await thread(env, buyer)
    for extra in ({}, {"candidate_set_id": str(uuid4())}):
        response = await env[0].post(
            f"/api/v1/agent/threads/{tid}/runs",
            headers=buyer,
            json={"request_id": str(uuid4()), "message": "帮我买第二款，一件，送演示宿舍", **extra},
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "CONTEXT_VERSION_REQUIRED"
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 0
