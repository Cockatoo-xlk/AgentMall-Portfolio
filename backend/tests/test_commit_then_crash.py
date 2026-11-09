import asyncio
import json
import os
import sys
from uuid import uuid4

import pytest
from conftest import ROOT, row
from t09_helpers import confirm, thread  # noqa: F401
from t09_helpers import durable_env as durable_env


async def child(env, tmp_path, task, kill=False, probe=None):
    task = {
        **task,
        "schema": env[3].db_schema,
        "checkpoint": env[3].checkpoint_schema,
        "marker": str(tmp_path / "marker"),
        "output": str(tmp_path / "output"),
    }
    for name in ("marker", "output"):
        path = tmp_path / name
        if path.exists():
            path.unlink()
    config = tmp_path / "task.json"
    config.write_text(json.dumps(task))
    log = tmp_path / "child.log"
    with log.open("w") as stream:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "backend/tests/t09_worker.py"),
            str(config),
            env=dict(os.environ),
            stdout=stream,
            stderr=stream,
            cwd=ROOT,
        )
        try:
            if kill:
                async with asyncio.timeout(20):
                    while not (tmp_path / "marker").exists():
                        if process.returncode is not None:
                            raise AssertionError(log.read_text())
                        await asyncio.sleep(0.03)
                if probe is not None:
                    await probe()
                process.kill()
                assert await process.wait() == -9
                return None
            async with asyncio.timeout(20):
                code = await process.wait()
            assert code == 0, log.read_text()
            return json.loads((tmp_path / "output").read_text())
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


def purchase_task(tid, pid, request_id):
    return {
        "product": pid,
        "path": f"/api/v1/agent/threads/{tid}/runs",
        "body": {"request_id": request_id, "message": f"准备购买一件 {pid}，送演示宿舍"},
    }


@pytest.mark.parametrize("boundary", ["before_proposal", "proposal_committed"])
async def test_real_process_kill_proposal_window(durable_env, buyer, product, tmp_path, boundary):
    env = durable_env
    tid = await thread(env, buyer)
    task = purchase_task(tid, product, str(uuid4()))

    async def conflict():
        response = await env[0].post(task["path"], headers=buyer, json=task["body"])
        assert response.status_code == 409, response.text

    await child(env, tmp_path, {**task, "boundary": boundary}, kill=True, probe=conflict)
    expected = 0 if boundary == "before_proposal" else 1
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == expected
    before = row(env[1], "SELECT budget->'used' AS used FROM agent_runs")["used"]
    recovered = await child(env, tmp_path, task)
    assert recovered["status"] == 200, recovered
    run = recovered["body"]
    assert run["status"] == "WAITING_INPUT", run
    assert run["epoch"] == 2
    assert run["budget"]["models"] >= before["models"]
    assert row(env[1], "SELECT count(*) n FROM action_proposals")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 0
    print(f"PROCESS_KILL {boundary}: SIGKILL=-9 reopened=0 proposals=1 orders=0 epoch=2")


@pytest.mark.parametrize(
    "boundary",
    ["confirmed_before_execute", "business_committed", "node_journal_saved", "checkpoint_saved"],
)
async def test_real_process_kill_and_resume_original_receipt(
    durable_env, buyer, product, tmp_path, boundary
):
    env = durable_env
    tid = await thread(env, buyer)
    run = (await child(env, tmp_path, purchase_task(tid, product, str(uuid4()))))["body"]
    assert run["status"] == "WAITING_INPUT", run
    pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, pid)
    body = {
        "request_id": str(uuid4()),
        "run_id": run["id"],
        "interrupt_id": run["pending_confirmation"]["interrupt_id"],
        "proposal_id": pid,
        "confirmation_id": cid,
    }
    task = {"path": f"/api/v1/agent/threads/{tid}/resume", "body": body, "product": product}

    async def conflict():
        response = await env[0].post(task["path"], headers=buyer, json=task["body"])
        assert response.status_code == 409, response.text

    await child(env, tmp_path, {**task, "boundary": boundary}, kill=True, probe=conflict)
    expected = 0 if boundary == "confirmed_before_execute" else 1
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == expected
    original = row(env[1], "SELECT min(id::text) id FROM orders")["id"]
    recovered = await child(env, tmp_path, task)
    assert recovered["status"] == 200, recovered
    assert recovered["body"]["status"] == "COMPLETED", recovered
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert row(env[1], "SELECT sum(reserved) n FROM products")["n"] == 1
    final_id = row(env[1], "SELECT id::text id FROM orders")["id"]
    if original:
        assert final_id == original
    replay = await child(env, tmp_path, task)
    assert replay["body"] == recovered["body"]
    # L3 asks Supervisor to finish only after the user decision; replay above
    # still proves the same response and budget, without another model request.
    assert recovered["body"]["budget"]["models"] == run["budget"]["models"] + 1
    assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
    print(
        f"PROCESS_KILL {boundary}: SIGKILL=-9 reopened=0 order={final_id} "
        "orders=1 reserved=1 refunds=0"
    )


async def test_return_receipt_recovers_after_real_process_kill(
    durable_env, buyer, product, tmp_path
):
    from aftersales_helpers import delivered_order

    env = durable_env
    order = await delivered_order(env[0], buyer, product)
    tid = await thread(env, buyer)
    task = {
        "order": order["id"],
        "product": product,
        "path": f"/api/v1/agent/threads/{tid}/runs",
        "body": {"request_id": str(uuid4()), "message": f"订单 {order['id']} 有质量问题，申请退货"},
    }
    run = (await child(env, tmp_path, task))["body"]
    assert run["status"] == "WAITING_INPUT", (
        run.get("last_error"),
        run.get("result", {}).get("error_codes"),
    )
    cid = await confirm(env, buyer, run["pending_confirmation"]["proposal_id"])
    resume_task = {
        **task,
        "path": f"/api/v1/agent/threads/{tid}/resume",
        "body": {
            "request_id": str(uuid4()),
            "run_id": run["id"],
            "interrupt_id": run["pending_confirmation"]["interrupt_id"],
            "proposal_id": run["pending_confirmation"]["proposal_id"],
            "confirmation_id": cid,
        },
    }
    await child(env, tmp_path, {**resume_task, "boundary": "business_committed"}, kill=True)
    first = row(env[1], "SELECT id::text id FROM aftersales_cases")["id"]
    recovered = await child(env, tmp_path, resume_task)
    assert recovered["body"]["status"] == "COMPLETED", recovered
    assert row(env[1], "SELECT id::text id FROM aftersales_cases")["id"] == first
    assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    print(f"PROCESS_KILL RETURN_REQUEST: case={first} cases=1 refunds=0 orders=1")


async def test_old_resume_after_new_interrupt_checkpoint_does_not_consume_second_proposal(
    durable_env, buyer, product, tmp_path
):
    from t09_helpers import two_proposals

    env = durable_env
    tid, run, order = await two_proposals(env, buyer, product)
    first_pid = run["pending_confirmation"]["proposal_id"]
    cid = await confirm(env, buyer, first_pid)
    body = {
        "request_id": str(uuid4()),
        "run_id": run["id"],
        "interrupt_id": run["pending_confirmation"]["interrupt_id"],
        "proposal_id": first_pid,
        "confirmation_id": cid,
    }
    replacement = row(
        env[1],
        "SELECT id::text id FROM products WHERE id != :original AND category='keyboard' "
        "AND attributes->>'noise'='较安静' AND price_cents <= 50000 ORDER BY id LIMIT 1",
        original=product,
    )["id"]
    task = {
        "path": f"/api/v1/agent/threads/{tid}/resume",
        "body": body,
        "product": replacement,
        "return_replace": True,
    }
    await child(env, tmp_path, {**task, "boundary": "checkpoint_saved"}, kill=True)
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    recovered = await child(env, tmp_path, task)
    assert recovered["status"] == 200, recovered
    next_run = recovered["body"]
    assert next_run["status"] == "WAITING_INPUT", next_run
    assert next_run["pending_confirmation"]["proposal_id"] != first_pid
    assert next_run["pending_confirmation"]["interrupt_id"] != body["interrupt_id"]
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    second = await confirm(env, buyer, next_run["pending_confirmation"]["proposal_id"])
    final_task = {
        **task,
        "body": {
            **body,
            "request_id": str(uuid4()),
            "interrupt_id": next_run["pending_confirmation"]["interrupt_id"],
            "proposal_id": next_run["pending_confirmation"]["proposal_id"],
            "confirmation_id": second,
        },
    }
    done = await child(env, tmp_path, final_task)
    assert done["body"]["status"] == "COMPLETED", done
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0
    print(
        "PROCESS_KILL second interrupt saved: old resume reconciled; "
        "second action separately approved"
    )
