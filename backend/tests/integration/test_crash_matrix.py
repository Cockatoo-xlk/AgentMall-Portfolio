"""T11 composes faults with other actions and T10 recovery; no copied SIGKILL cases."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from checkout_helpers import confirm, execute, prepare, request_body
from lifecycle_helpers import create_order, execute_action, prepare_action, timed_order
from multiagent_helpers import install, make_models, route
from sqlalchemy import text
from t09_helpers import confirm as graph_confirm
from t09_helpers import purchase_models, resume, start, thread, two_proposals
from test_lifecycle_http import loopback_server

from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

from .harness import DropResponse, race, scalar, verify, wait_clock
from .oracle import fingerprints, inspect_database, reader
from .test_business_invariants import maintenance


def recovery_url(tid, run):
    return f"/api/v1/agent/threads/{tid}/runs/{run['id']}/recover"


async def cp_state(env, tid, run):
    async with checkpoint_saver(env[3]) as saver:
        value = await saver.aget_tuple(checkpoint_config(tid, UUID(run["id"])))
        assert value is not None
        state = value.checkpoint["channel_values"]
        return {
            "checkpoint_id": value.checkpoint["id"],
            "round": state.get("round"),
            "next": state.get("next"),
            "handled": state.get("handled"),
            "pending_action": state.get("pending_action"),
            "pending_writes": len(value.pending_writes or []),
        }


async def event_oracle(env, auth, run):
    items, cursor = [], 0
    for _ in range(100):
        response = await env[0].get(
            f"/api/v1/agent/runs/{run['id']}/events",
            headers=auth,
            params={"after_seq": cursor, "limit": 3},
        )
        assert response.status_code == 200
        page = response.json()
        if not page["items"]:
            break
        assert page["next_seq"] > cursor
        items.extend(page["items"])
        cursor = page["next_seq"]
    else:
        pytest.fail("event pagination did not terminate")
    with reader(env) as conn:
        persisted = [
            dict(r)
            for r in conn.execute(
                text("SELECT seq,event_type,agent FROM run_events WHERE run_id=:id ORDER BY seq"),
                {"id": run["id"]},
            ).mappings()
        ]
    assert [{k: e[k] for k in ("seq", "event_type", "agent")} for e in items] == persisted
    # Repeated overlapping reads rebuild exactly the same (run,seq) map.
    rebuilt = {e["seq"]: e for e in items}
    again = await env[0].get(
        f"/api/v1/agent/runs/{run['id']}/events",
        headers=auth,
        params={"after_seq": max(0, cursor - 4), "limit": 100},
    )
    for e in again.json()["items"]:
        assert rebuilt[e["seq"]] == e
    return persisted


async def test_precommit_multisku_failure_with_competitor_and_same_action_retry(
    env, buyer, buyer2, product, evidence, monkeypatch
):
    from agentmall.orders import service

    evidence["case_id"] = "F01"
    client = env[0]
    second = str(
        scalar(env, "SELECT id FROM products WHERE id!=:id AND active LIMIT 1", id=product)
    )
    p = await prepare(
        client,
        buyer,
        body=request_body(
            product,
            items=[{"product_id": product, "quantity": 2}, {"product_id": second, "quantity": 1}],
        ),
    )
    c = await confirm(client, buyer, p)
    peer = await prepare(client, buyer2, product)
    cc = await confirm(client, buyer2, peer)
    original = service.write_order_event
    fired = False

    async def fail_target(session, order, now):
        nonlocal fired
        await original(session, order, now)
        if str(order.proposal_id) == p["proposal_id"] and not fired:
            fired = True
            raise RuntimeError("T11 precommit target fault after full write set")

    monkeypatch.setattr(service, "write_order_event", fail_target)
    key = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env[2], raise_app_exceptions=False),
        base_url="http://test",
    ) as faulty:

        async def expected_failure():
            response = await execute(faulty, buyer, p, c, key)
            assert response.status_code == 500
            evidence["injected_http_status"] = response.status_code
            return response

        results = await race(
            env,
            evidence,
            "SELECT id FROM products WHERE id=:id FOR UPDATE",
            {"id": product},
            [
                ("fails-before-commit", expected_failure),
                ("independent-buyer", lambda: execute(client, buyer2, peer, cc)),
            ],
            ordered=True,
            injected_http_failures={"fails-before-commit": 500},
        )
    assert fired and results[1].status_code == 201
    mid = inspect_database(env, evidence["initial"])
    assert mid["violations"] == [] and mid["counts"]["orders"] == 1
    assert (
        scalar(
            env,
            "SELECT count(*) FROM idempotency_requests WHERE action_id=:id",
            id=p["proposal_id"],
        )
        == 0
    )
    assert (
        scalar(env, "SELECT consumed_at FROM confirmations WHERE id=:id", id=c["confirmation_id"])
        is None
    )
    evidence["after_rollback"] = mid
    monkeypatch.setattr(service, "write_order_event", original)
    retried = await execute(client, buyer, p, c, key)
    assert retried.status_code == 201
    assert verify(env, evidence)["counts"]["orders"] == 2


async def test_checkout_response_loss_then_cancel_and_historical_receipt(
    env, buyer, product, evidence
):
    evidence["case_id"] = "F02"
    async with loopback_server(env[2]) as client:
        p = await prepare(client, buyer, product)
        c = await confirm(client, buyer, p)
        key, lost = str(uuid4()), DropResponse()
        async with httpx.AsyncClient(
            base_url=client.base_url, transport=lost, timeout=10
        ) as faulty:
            with pytest.raises(httpx.ReadError, match="T11 controlled"):
                await execute(faulty, buyer, p, c, key)
        evidence["after_response_loss"] = inspect_database(env, evidence["initial"])
        proposal = (await client.get(f"/api/v1/proposals/{p['proposal_id']}", headers=buyer)).json()
        assert proposal["result"] == lost.receipt
        order = (
            await client.get(f"/api/v1/orders/{lost.receipt['order_id']}", headers=buyer)
        ).json()
        cancel = await prepare_action(client, buyer, order, "cancel")
        approval = await confirm(client, buyer, cancel)
        closed = await execute_action(client, buyer, order, cancel, approval, "cancel")
        assert closed.status_code == 200 and closed.json()["status"] == "CANCELLED"
        replay = await execute(client, buyer, p, c, key)
        assert replay.status_code == 200 and replay.json() == lost.receipt
        current = await client.get(f"/api/v1/orders/{order['id']}", headers=buyer)
        assert current.json()["status"] == "CANCELLED"
        evidence["historical_receipt"] = replay.json()
        evidence["current_status"] = current.json()["status"]
    state = verify(env, evidence)
    assert state["counts"]["orders"] == 1 and state["inventory"][product]["reserved"] == 0


async def test_two_proposal_recover_race_lost_reply_and_export_failure(
    durable_env, buyer, product, evidence, monkeypatch
):
    from agentmall.agents import durable_graph, run_service

    env = durable_env
    evidence["case_id"] = "F03_F06_F08"
    tid, run, order = await two_proposals(env, buyer, product)
    first_id = run["pending_confirmation"]["proposal_id"]
    cid = await graph_confirm(env, buyer, first_id)
    rid = str(uuid4())
    original_execute = durable_graph.execute_confirmation
    fired = False

    async def commit_gap(runtime, payload):
        nonlocal fired
        await original_execute(runtime, payload)
        if not fired:
            fired = True
            raise RuntimeError("T11 case committed; execute node journal and checkpoint absent")

    monkeypatch.setattr(durable_graph, "execute_confirmation", commit_gap)
    partial = await resume(env, buyer, tid, run, cid, rid)
    assert partial.status_code == 200 and partial.json()["status"] == "PARTIAL"
    evidence["gap"] = {
        "run": partial.json(),
        "checkpoint": await cp_state(env, tid, run),
        "database": inspect_database(env, evidence["initial"]),
    }
    assert evidence["gap"]["database"]["counts"]["aftersales_cases"] == 1
    assert first_id not in evidence["gap"]["checkpoint"]["handled"]
    monkeypatch.setattr(durable_graph, "execute_confirmation", original_execute)
    entered, release = asyncio.Event(), asyncio.Event()
    original_save = run_service.NodeStore.save

    async def pause_recover(self, key, output, trace):
        if key == "execute_confirmed:" + first_id:
            entered.set()
            await release.wait()
        return await original_save(self, key, output, trace)

    monkeypatch.setattr(run_service.NodeStore, "save", pause_recover)
    exports = []

    async def failed_export(trace):
        exports.append(trace["run_id"])
        raise RuntimeError("T11 optional exporter unavailable")

    env[2].state.trace_exporter = failed_export
    lost = DropResponse()
    url = recovery_url(tid, run)
    async with loopback_server(env[2]) as network:
        async with httpx.AsyncClient(
            base_url=network.base_url, transport=lost, timeout=10
        ) as faulty:

            async def recover_lost():
                with pytest.raises(httpx.ReadError, match="T11 controlled"):
                    await faulty.post(url, headers=buyer, json={"request_id": run["request_id"]})

            task = asyncio.create_task(recover_lost())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                competing = await asyncio.gather(
                    start(env, buyer, tid),
                    resume(env, buyer, tid, run, cid, rid),
                    env[0].post(url, headers=buyer, json={"request_id": run["request_id"]}),
                )
                evidence["competing_calls"] = [r.json() for r in competing]
                assert all(
                    r.status_code == 409 and r.json()["code"] == "THREAD_BUSY" for r in competing
                )
                evidence["active_advisory_locks"] = scalar(
                    env,
                    "SELECT count(*) FROM pg_locks l "
                    "JOIN pg_stat_activity a USING(pid) WHERE l.locktype='advisory' AND l.granted "
                    "AND a.application_name=:name",
                    name=f"agentmall:lock:{tid}",
                )
                assert evidence["active_advisory_locks"] == 1
            finally:
                release.set()
                await asyncio.wait_for(task, 10)
    assert lost.receipt["status"] == "WAITING_INPUT" and exports
    recovered = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()["runs"][0]
    assert recovered == lost.receipt
    assert recovered["pending_confirmation"]["proposal_id"] != first_id
    assert (
        recovered["pending_confirmation"]["interrupt_id"]
        != run["pending_confirmation"]["interrupt_id"]
    )
    for key, code in [(rid, 200), (str(uuid4()), 409)]:
        old = await resume(env, buyer, tid, run, cid, key)
        assert old.status_code == code
    wrong = await resume(env, buyer, tid, recovered, cid)
    assert wrong.status_code == 409
    assert scalar(env, "SELECT count(*) FROM orders") == 1
    # Retry the same recovery identity; it only returns the second pending interrupt.
    # The preceding unfinished old Resume journal may reconcile a new execution epoch;
    # that is not a new Run or approval. Compare with the current persisted view.
    current = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()["runs"][0]
    assert current["id"] == recovered["id"]
    assert current["pending_confirmation"] == recovered["pending_confirmation"]
    assert current["budget"] == recovered["budget"]
    again = await env[0].post(url, headers=buyer, json={"request_id": run["request_id"]})
    assert again.json() == current
    next_cid = await graph_confirm(env, buyer, recovered["pending_confirmation"]["proposal_id"])
    assert next_cid != cid
    done = await resume(env, buyer, tid, recovered, next_cid)
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    evidence["checkpoint_final"] = await cp_state(env, tid, done.json())
    evidence["run_events"] = await event_oracle(env, buyer, done.json())
    evidence["export_failures"] = len(exports)
    assert all(done.json()["budget"][k] >= v for k, v in run["budget"].items())
    state = verify(env, evidence)
    assert state["counts"]["orders"] == 2 and state["counts"]["aftersales_cases"] == 1
    assert state["counts"]["agent_runs"] == 1 and state["counts"]["refunds"] == 0


async def test_saved_checkpoint_answer_failure_then_reference_recovery(
    durable_env, buyer, evidence, monkeypatch
):
    from agentmall.agents import run_service

    env = durable_env
    evidence["case_id"] = "F04"
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    cid = await graph_confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    original = run_service.render

    def broken(*args, **kwargs):
        raise RuntimeError("T11 final rendering failed after checkpoint saved")

    monkeypatch.setattr(run_service, "render", broken)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env[2], raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await resume((client, *env[1:]), buyer, tid, run, cid)
    assert response.status_code == 500
    before = inspect_database(env, evidence["initial"])
    assert before["counts"]["orders"] == 1 and before["runs"][0]["status"] == "RUNNING"
    evidence["checkpoint_before_recover"] = await cp_state(env, tid, run)
    assert evidence["checkpoint_before_recover"]["next"] == "done"
    monkeypatch.setattr(run_service, "render", original)
    done = await env[0].post(
        recovery_url(tid, run), headers=buyer, json={"request_id": run["request_id"]}
    )
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    assert done.json()["budget"] == before["runs"][0]["budget"]["used"]
    evidence["run_events"] = await event_oracle(env, buyer, done.json())
    assert verify(env, evidence)["counts"]["orders"] == 1


async def test_paused_maintenance_expired_pending_still_reserved(
    env, buyer, buyer2, product, evidence
):
    evidence["case_id"] = "F05"
    order = await create_order(env[0], buyer, product, quantity=2)
    await create_order(env[0], buyer2, product, quantity=3)
    p = await prepare_action(env[0], buyer, order, "payment")
    c = await confirm(env[0], buyer, p)
    expires = timed_order(env[1], order["id"], 0.2)
    await wait_clock(env, expires)
    before = inspect_database(env, evidence["initial"])
    assert before["violations"] == [] and before["inventory"][product]["reserved"] == 5
    evidence["expired_before_maintenance"] = before
    # A direct payment after natural expiry must reconcile expiry even with scanner stopped.
    response = await execute_action(env[0], buyer, order, p, c, "payment")
    assert response.status_code == 200 and response.json()["status"] == "EXPIRED"
    assert not (await maintenance(env, order)).changed
    assert not (await maintenance(env, order)).changed
    state = verify(env, evidence)
    assert state["inventory"][product]["reserved"] == 3 and state["counts"]["payments"] == 0
    assert (
        scalar(
            env,
            "SELECT count(*) FROM business_events WHERE aggregate_id=:id AND "
            "event_type='ORDER_EXPIRED'",
            id=order["id"],
        )
        == 1
    )


async def test_lost_lock_recover_new_epoch_rejects_old_business_and_saver(
    durable_env, buyer, evidence, monkeypatch
):
    from agentmall.agents import durable_graph
    from agentmall.infra.errors import DomainError

    env = durable_env
    evidence["case_id"] = "F07"
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    cid = await graph_confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    entered, release = asyncio.Event(), asyncio.Event()
    original = durable_graph.execute_confirmation
    fences = []

    async def delayed(runtime, payload):
        fences.append(runtime.guard.__self__)
        entered.set()
        await release.wait()
        return await original(runtime, payload)

    monkeypatch.setattr(durable_graph, "execute_confirmation", delayed)
    old = asyncio.create_task(resume(env, buyer, tid, run, cid, str(uuid4())))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        old_fence = fences[0]
        with env[1].begin() as c:
            owned = c.scalar(
                text("SELECT application_name FROM pg_stat_activity WHERE pid=:pid"),
                {"pid": old_fence.pid},
            )
            assert owned == f"agentmall:lock:{tid}"
            assert c.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": old_fence.pid})
        monkeypatch.setattr(durable_graph, "execute_confirmation", original)
        done = await env[0].post(
            recovery_url(tid, run), headers=buyer, json={"request_id": run["request_id"]}
        )
        assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
        assert done.json()["epoch"] == old_fence.epoch + 1
        evidence["takeover"] = {
            "terminated_owned_pid": old_fence.pid,
            "old_epoch": old_fence.epoch,
            "new_epoch": done.json()["epoch"],
        }
        before = fingerprints(env, checkpoint=True)
    finally:
        release.set()
        stale = await asyncio.wait_for(old, 5)
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_EXECUTOR"
    # Attempt both official saver write paths with the exact stale fence after takeover.
    async with checkpoint_saver(env[3], old_fence) as saver:
        value = await saver.aget_tuple(checkpoint_config(tid, UUID(run["id"])))
        for write in (
            lambda: saver.aput(value.config, value.checkpoint, value.metadata, {}),
            lambda: saver.aput_writes(
                value.config, [("t11_stale", "must_not_persist")], "t11-stale-task"
            ),
        ):
            with pytest.raises(DomainError) as failure:
                await write()
            assert failure.value.code == "STALE_EXECUTOR"
    after = fingerprints(env, checkpoint=True)
    assert after == before
    evidence["stale_writes"] = {
        "business_http": stale.status_code,
        "checkpoint_denials": 2,
        "before": before,
        "after": after,
    }
    evidence["checkpoint_final"] = await cp_state(env, tid, done.json())
    evidence["run_events"] = await event_oracle(env, buyer, done.json())
    assert all(done.json()["budget"][k] >= v for k, v in run["budget"].items())
    assert verify(env, evidence)["counts"]["orders"] == 1


async def test_parallel_threads_start_resume_recover_and_event_reread(durable_env, buyer, evidence):
    env = durable_env
    evidence["case_id"] = "R01"
    ready, release = asyncio.Event(), asyncio.Event()
    arrived = 0

    async def delayed(messages):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await release.wait()
        return route("finish")(messages)

    await install(env, make_models(supervisor=[delayed, delayed]), indexed=False)
    tids = [await thread(env, buyer), await thread(env, buyer)]
    requests = [str(uuid4()), str(uuid4())]
    tasks = [
        asyncio.create_task(start(env, buyer, t, r)) for t, r in zip(tids, requests, strict=True)
    ]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        with reader(env) as c:
            evidence["parallel_locks"] = [
                dict(r)
                for r in c.execute(
                    text(
                        "SELECT a.pid,a.application_name,l.granted FROM pg_locks l JOIN "
                        "pg_stat_activity a USING(pid) "
                        "WHERE l.locktype='advisory' AND l.granted AND a.application_name IN "
                        "(:a,:b)"
                    ),
                    {"a": f"agentmall:lock:{tids[0]}", "b": f"agentmall:lock:{tids[1]}"},
                ).mappings()
            ]
        assert len(evidence["parallel_locks"]) == 2
        run = (await env[0].get(f"/api/v1/agent/threads/{tids[0]}", headers=buyer)).json()["runs"][
            0
        ]
        responses = await asyncio.gather(
            start(env, buyer, tids[0], requests[0]),
            env[0].post(
                f"/api/v1/agent/threads/{tids[0]}/resume",
                headers=buyer,
                json={
                    "request_id": str(uuid4()),
                    "run_id": run["id"],
                    "interrupt_id": "not-yet-issued",
                    "clarification": "irrelevant",
                },
            ),
            env[0].post(
                recovery_url(tids[0], run), headers=buyer, json={"request_id": requests[0]}
            ),
        )
        assert all(r.status_code == 409 and r.json()["code"] == "THREAD_BUSY" for r in responses)
        evidence["conflicts"] = [r.json() for r in responses]
    finally:
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    assert all(r.status_code == 201 and r.json()["status"] == "COMPLETED" for r in results)
    evidence["run_events"] = [await event_oracle(env, buyer, r.json()) for r in results]
    state = verify(env, evidence)
    assert state["counts"]["agent_runs"] == state["counts"]["agent_threads"] == 2
    assert state["counts"]["orders"] == 0
