"""Explicit bounded expiry scans; never launched by the API or seed entrypoints."""

import argparse
import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from agentmall.infra.config import Settings
from agentmall.infra.db import database
from agentmall.orders.lifecycle import expire_order
from agentmall.orders.models import Order


async def scan_once(sessions, *, limit=100):
    if not 1 <= limit <= 1000:
        raise ValueError("scan batch must be 1..1000")
    # Candidate scan never keeps locks across orders or while sleeping.
    async with sessions.begin() as session:
        ids = list(
            await session.scalars(
                select(Order.id)
                .where(
                    Order.status == "PENDING_PAYMENT", Order.expires_at <= func.clock_timestamp()
                )
                .order_by(Order.expires_at, Order.id)
                .limit(limit)
            )
        )
    changed, failed = 0, []
    for order_id in ids:
        try:
            async with sessions.begin() as session:
                result = await expire_order(session, order_id)
            changed += int(result.changed)
        except DBAPIError:
            # Failed order rolls back independently; a later scan can retry it.
            failed.append(str(order_id))
    return {"candidates": len(ids), "expired": changed, "failed_order_ids": failed}


async def run(*, once, interval, limit, settings=None):
    engine, sessions = database(settings or Settings())
    try:
        while True:
            result = await scan_once(sessions, limit=limit)
            print(json.dumps(result), flush=True)
            if once:
                return 1 if result["failed_order_ids"] else 0
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--interval", type=int, choices=range(1, 3601), metavar="SECONDS")
    parser.add_argument("--limit", type=int, choices=range(1, 1001), default=100, metavar="1..1000")
    args = parser.parse_args()
    try:
        return asyncio.run(run(once=args.once, interval=args.interval, limit=args.limit))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
