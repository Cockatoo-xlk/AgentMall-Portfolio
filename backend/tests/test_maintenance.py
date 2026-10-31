"""Run the real maintenance executable only against this fixture's owned schema."""

import asyncio
import json
import os
import sys

import pytest
from conftest import ROOT, row
from lifecycle_helpers import create_order, timed_order
from sqlalchemy import text


def process_env(settings):
    return {
        **os.environ,
        "AGENTMALL_DATABASE_URL": settings.database_url.get_secret_value(),
        "AGENTMALL_DB_SCHEMA": settings.db_schema,
    }


async def run_once(settings):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "agentmall.maintenance",
        "--once",
        cwd=ROOT,
        env=process_env(settings),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 10)
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
    assert proc.returncode == 0, err.decode()
    return json.loads(out)


async def test_once_restart_and_interval_release_only_once(env, buyer, product):
    client, db, _, settings = env
    order = await create_order(client, buyer, product, quantity=2)
    timed_order(db, order["id"], -1)
    first = await run_once(settings)
    assert first == {"candidates": 1, "expired": 1, "failed_order_ids": []}
    second = await run_once(settings)  # Fresh process, same persistent DB.
    assert second == {"candidates": 0, "expired": 0, "failed_order_ids": []}
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "agentmall.maintenance",
        "--interval",
        "1",
        cwd=ROOT,
        env=process_env(settings),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        for _ in range(2):
            report = json.loads(await asyncio.wait_for(proc.stdout.readline(), 5))
            assert report["expired"] == 0
    finally:
        if proc.returncode is None:
            proc.terminate()
        await asyncio.wait_for(proc.wait(), 5)
    assert row(db, "SELECT on_hand,reserved FROM products WHERE id=:id", id=product) == {
        "on_hand": 20,
        "reserved": 0,
    }
    assert (
        row(db, "SELECT count(*) n FROM business_events WHERE event_type='ORDER_EXPIRED'")["n"] == 1
    )


async def test_sweep_one_order_failure_does_not_rollback_another(env, buyer, product):
    from agentmall.maintenance import scan_once

    client, db, app, _ = env
    first = await create_order(client, buyer, product)
    second = await create_order(client, buyer, product)
    for order in (first, second):
        timed_order(db, order["id"], -1)
    with db.begin() as connection:
        connection.execute(
            text(f"""CREATE FUNCTION fail_one_expiry() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.id='{first["id"]}'::uuid AND NEW.status='EXPIRED' THEN
          RAISE EXCEPTION 'synthetic expiry fault' USING ERRCODE='40001';
        END IF; RETURN NEW; END $$;
        CREATE TRIGGER test_fail_expiry BEFORE UPDATE ON orders
        FOR EACH ROW EXECUTE FUNCTION fail_one_expiry();""")
        )
    report = await scan_once(app.state.sessions)
    assert report == {"candidates": 2, "expired": 1, "failed_order_ids": [first["id"]]}
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 1
    with db.begin() as connection:
        connection.execute(text("DROP TRIGGER test_fail_expiry ON orders"))
    assert (await scan_once(app.state.sessions))["expired"] == 1
    assert row(db, "SELECT reserved FROM products WHERE id=:id", id=product)["reserved"] == 0


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--interval", "0"],
        ["--interval", "-1"],
        ["--once", "--interval", "30"],
        ["--once", "--limit", "0"],
    ],
)
async def test_cli_rejects_unbounded_or_invalid_mode(args):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "agentmall.maintenance",
        *args,
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(proc.communicate(), 5)
    assert proc.returncode == 2
