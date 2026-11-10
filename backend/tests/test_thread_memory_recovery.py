import asyncio
import json
import os
import sys
from uuid import uuid4

from conftest import ROOT, row
from multiagent_helpers import install, make_models, route
from t09_helpers import durable_env as durable_env
from t09_helpers import thread
from test_thread_memory import read, turn


async def test_sigkill_after_atomic_memory_commit_recovers_original_snapshot(
    durable_env, buyer, tmp_path
):
    env = durable_env
    await install(env, make_models(supervisor=[route("finish")]), indexed=False)
    tid = await thread(env, buyer)
    rid = str(uuid4())
    task = {
        "schema": env[3].db_schema,
        "checkpoint": env[3].checkpoint_schema,
        "thread": tid,
        "marker": str(tmp_path / "marker"),
        "body": {"request_id": rid, "message": "300元以内静音键盘", "expected_context_version": 0},
    }
    config = tmp_path / "task.json"
    config.write_text(json.dumps(task))
    with (tmp_path / "child.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "backend/tests/t16_memory_worker.py"),
            str(config),
            cwd=ROOT,
            env=dict(os.environ),
            stdout=log,
            stderr=log,
        )
        try:
            async with asyncio.timeout(20):
                while not (tmp_path / "marker").exists():
                    if process.returncode is not None:
                        raise AssertionError((tmp_path / "child.log").read_text())
                    await asyncio.sleep(0.03)
            before = await read(env, buyer, tid)
            assert before["context"]["version"] == 1
            assert before["runs"][0]["status"] == "RUNNING"
            assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
            process.kill()
            assert await process.wait() == -9
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    run = before["runs"][0]
    recovered = await env[0].post(
        f"/api/v1/agent/threads/{tid}/runs/{run['id']}/recover",
        headers=buyer,
        json={"request_id": rid},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "COMPLETED"
    assert recovered.json()["context_snapshot"] == run["context_snapshot"]
    assert (await read(env, buyer, tid))["context"]["version"] == 1
    replay = await turn(env, buyer, tid, "300元以内静音键盘", 0, request_id=rid)
    assert replay.status_code == 200
    assert replay.json()["budget"] == recovered.json()["budget"]
    assert row(env[1], "SELECT count(*) n FROM agent_runs")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM agent_candidate_sets")["n"] == 0
    print(
        "T16 SIGKILL=-9 boundary=context+run committed before activation; "
        "original snapshot recovered once"
    )
