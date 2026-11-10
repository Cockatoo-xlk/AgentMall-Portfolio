import asyncio
import json
from uuid import uuid4

import pytest
from multiagent_helpers import ai, call, final, install, make_models, route
from sqlalchemy import text
from t09_helpers import confirm, purchase_models, resume, start, thread
from t09_helpers import durable_env as durable_env


def frames(body):
    return [
        (
            next(line[7:] for line in frame.splitlines() if line.startswith("event: ")),
            json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: "))),
        )
        for frame in body.split("\n\n")
        if "event: " in frame
    ]


async def test_stream_scope_filter_and_cursor(durable_env, buyer, buyer2):
    client, db, _, _ = durable_env
    await install(durable_env, make_models(supervisor=[route("finish")]), indexed=False)
    tid = await thread(durable_env, buyer)
    run = (await start(durable_env, buyer, tid, message="结束测试")).json()
    root = f"/api/v1/agent/runs/{run['id']}/events"
    assert (await client.get(root + "/stream")).status_code == 401
    assert (await client.get(root + "/stream", headers=buyer2)).status_code == 404
    with db.begin() as conn:
        conn.execute(text("UPDATE agent_threads SET store_id=:store"), {"store": uuid4()})
    assert (await client.get(root + "/stream", headers=buyer)).status_code == 404
    with db.begin() as conn:
        conn.execute(
            text("UPDATE agent_threads SET store_id=:store"),
            {"store": durable_env[3].storefront_id},
        )
        conn.execute(
            text(
                "UPDATE run_events SET payload_summary = payload_summary || "
                """'{"prompt":"private-prompt","checkpoint":"private-checkpoint","jwt":"private-jwt"}'::jsonb"""
            )
        )
    response = await client.get(root + "/stream?after_seq=1", headers=buyer)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "private-" not in response.text
    received = frames(response.text)
    page = (await client.get(root + "?after_seq=1", headers=buyer)).json()
    assert [event for kind, event in received if kind == "run_event"] == page["items"]
    assert received[-1] == ("run_status", {"status": "COMPLETED"})
    last = await client.get(f"{root}/stream?after_seq={page['next_seq']}", headers=buyer)
    assert frames(last.text) == [("run_status", {"status": "COMPLETED"})]


async def test_disconnect_releases_reader_without_cancelling_running_work(durable_env, buyer):
    env = durable_env
    entered, release, disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def shopping(_messages):
        entered.set()
        await release.wait()
        return ai(call("retrieve_products", {"query": "静音键盘"}))

    await install(
        env,
        make_models(
            supervisor=[route("shopping", "find_products"), route("finish")],
            shopping=[shopping, final()],
        ),
    )
    tid = await thread(env, buyer)
    request_id = str(uuid4())
    execution = asyncio.create_task(start(env, buyer, tid, request_id, "推荐静音键盘"))
    reader = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        latest = (await env[0].get(f"/api/v1/agent/threads/{tid}", headers=buyer)).json()["runs"][0]
        assert latest["request_id"] == request_id and latest["status"] == "RUNNING"
        sent = asyncio.Queue()
        path = f"/api/v1/agent/runs/{latest['id']}/events/stream"

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        reader = asyncio.create_task(
            env[2](
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "root_path": "",
                    "query_string": b"",
                    "headers": [
                        (key.lower().encode(), value.encode()) for key, value in buyer.items()
                    ],
                    "client": ("127.0.0.1", 50000),
                    "server": ("test", 80),
                },
                receive,
                sent.put,
            )
        )
        assert (await asyncio.wait_for(sent.get(), 3))["status"] == 200
        before = []
        while not any(kind == "run_status" for kind, _ in before):
            message = await asyncio.wait_for(sent.get(), 3)
            assert message.get("more_body"), message
            before += frames(message["body"].decode())
        assert any(
            kind == "run_event" and event["event_type"] == "handoff" for kind, event in before
        )
        assert before[-1] == ("run_status", {"status": "RUNNING"})
        assert not execution.done()
        disconnected.set()
        await asyncio.wait_for(reader, 2)
        assert env[2].state.engine.pool.checkedout() == 0
        assert not execution.done()
        release.set()
        assert (await execution).json()["status"] == "COMPLETED"
        cursor = max(event["seq"] for kind, event in before if kind == "run_event")
        after = await env[0].get(f"{path}?after_seq={cursor}", headers=buyer)
        seqs = [event["seq"] for kind, event in frames(after.text) if kind == "run_event"]
        assert seqs == list(range(cursor + 1, cursor + 1 + len(seqs))) and seqs
        assert frames(after.text)[-1] == ("run_status", {"status": "COMPLETED"})
    finally:
        disconnected.set()
        release.set()
        if reader:
            await asyncio.gather(reader, return_exceptions=True)
        await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.parametrize("status", ["PARTIAL", "FAILED"])
async def test_stream_closes_on_terminal_run_status(durable_env, buyer, status):
    env = durable_env
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    with env[1].begin() as conn:
        conn.execute(text("UPDATE agent_runs SET status=:status"), {"status": status})
    response = await env[0].get(f"/api/v1/agent/runs/{run['id']}/events/stream", headers=buyer)
    assert frames(response.text)[-1] == ("run_status", {"status": status})


async def test_waiting_stream_times_out_and_resumes_at_cursor(durable_env, buyer, monkeypatch):
    from agentmall.agents import event_stream

    env = durable_env
    await purchase_models(env)
    tid = await thread(env, buyer)
    run = (await start(env, buyer, tid)).json()
    path = f"/api/v1/agent/runs/{run['id']}/events/stream"
    monkeypatch.setattr(event_stream, "WINDOW_SECONDS", 0.12)
    monkeypatch.setattr(event_stream, "HEARTBEAT_SECONDS", 0)
    first = await asyncio.wait_for(env[0].get(path, headers=buyer), 1)
    assert frames(first.text)[-1] == ("run_status", {"status": "WAITING_INPUT"})
    assert ": heartbeat" in first.text
    cursor = max(event["seq"] for kind, event in frames(first.text) if kind == "run_event")
    assert env[2].state.engine.pool.checkedout() == 0
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    assert (await resume(env, buyer, tid, run, cid)).json()["status"] == "COMPLETED"
    second = await env[0].get(f"{path}?after_seq={cursor}", headers=buyer)
    after = [event for kind, event in frames(second.text) if kind == "run_event"]
    assert after[0]["seq"] == cursor + 1
    assert any(event["event_type"] == "resume_received" for event in after)
    assert frames(second.text)[-1] == ("run_status", {"status": "COMPLETED"})
