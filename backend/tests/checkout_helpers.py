from datetime import timedelta
from uuid import uuid4

from sqlalchemy import MetaData, Table, text


def request_body(product, quantity=1, **overrides):
    return {
        "request_id": str(uuid4()),
        "proposal_slot": "checkout",
        "address_label": "demo_dorm",
        "items": [{"product_id": product, "quantity": quantity}],
        **overrides,
    }


async def prepare(client, buyer, product=None, *, body=None, key=None, expected=201):
    body = body if body is not None else request_body(product)
    key = key or str(uuid4())
    r = await client.post(
        "/api/v1/checkout/proposals", headers={**buyer, "Idempotency-Key": key}, json=body
    )
    assert r.status_code == expected, r.text
    return r.json()


async def confirm(client, buyer, proposal, decision="approve", expected=201):
    r = await client.post(
        f"/api/v1/proposals/{proposal['proposal_id']}/confirmations",
        headers=buyer,
        json={"decision": decision},
    )
    assert r.status_code == expected, r.text
    return r.json()


async def execute(client, buyer, proposal, confirmation, key=None):
    return await client.post(
        "/api/v1/orders",
        headers={**buyer, "Idempotency-Key": key or str(uuid4())},
        json={
            "proposal_id": proposal["proposal_id"],
            "confirmation_id": confirmation["confirmation_id"],
        },
    )


def counts(db):
    with db.connect() as c:
        return {
            table: c.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("orders", "order_items", "business_events", "idempotency_requests")
        }


def timed_proposal(db, proposal, seconds):
    """Insert an independent immutable fixture, without updating an existing proposal."""
    table = Table("action_proposals", MetaData(), autoload_with=db)
    with db.begin() as c:
        data = dict(
            c.execute(table.select().where(table.c.id == proposal["proposal_id"])).mappings().one()
        )
        now = c.scalar(text("SELECT clock_timestamp()"))
        data.update(
            id=uuid4(),
            origin_request_id=uuid4(),
            expires_at=now + timedelta(seconds=seconds),
            created_at=now - timedelta(minutes=6),
            updated_at=now - timedelta(minutes=6),
        )
        c.execute(table.insert().values(**data))
        return {
            **proposal,
            "proposal_id": str(data["id"]),
            "expires_at": data["expires_at"].isoformat(),
        }
