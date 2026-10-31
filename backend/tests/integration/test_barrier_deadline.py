"""Controlled observer overhead must not spend twelve sequential lock deadlines."""

from sqlalchemy import text

from . import harness
from .test_business_invariants import test_twelve_checkout_replays_and_conflicts as checkout_case


async def test_twelve_waiters_with_controlled_observer_cost(
    env, buyer, product, evidence, monkeypatch
):
    original = harness.waiters

    async def observed(env, blocker, count, tasks, report):
        await original(env, blocker, count, tasks, report)
        if count < 12:
            with env[1].connect() as conn:
                before = conn.scalar(text("SELECT clock_timestamp()"))
                conn.execute(text("SELECT pg_sleep(0.3)"))
                after = conn.scalar(text("SELECT clock_timestamp()"))
            report["events"].append(
                {
                    "phase": "CONTROLLED_OBSERVER_COST",
                    "count": count,
                    "before": before,
                    "after": after,
                }
            )

    monkeypatch.setattr(harness, "waiters", observed)
    await checkout_case(env, buyer, product, evidence, "same_key")
