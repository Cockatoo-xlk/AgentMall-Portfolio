from datetime import datetime

from checkout_helpers import prepare, timed_proposal
from conftest import row


async def test_proposal_clock_uses_postgres_and_does_not_change_snapshot(env, buyer, product):
    client, db, _, _ = env
    proposal = await prepare(client, buyer, product)
    immutable = row(db, "SELECT canonical_payload,payload_hash,expires_at FROM action_proposals")
    before = row(db, "SELECT clock_timestamp() AS stamp")["stamp"]
    response = await client.get("/api/v1/proposals/" + proposal["proposal_id"], headers=buyer)
    after = row(db, "SELECT clock_timestamp() AS stamp")["stamp"]
    assert response.status_code == 200
    stamp = datetime.fromisoformat(response.headers["X-Server-Time"].replace("Z", "+00:00"))
    assert before <= stamp <= after
    assert (
        row(db, "SELECT canonical_payload,payload_hash,expires_at FROM action_proposals")
        == immutable
    )
    assert "server_time" not in response.json()
    assert "server_time" not in response.json()["canonical_payload"]


async def test_expired_proposal_returns_authoritative_time_without_consumption(env, buyer, product):
    client, db, _, _ = env
    proposal = await prepare(client, buyer, product)
    proposal = timed_proposal(db, proposal, -1)
    response = await client.get("/api/v1/proposals/" + proposal["proposal_id"], headers=buyer)
    body = response.json()
    assert body["status"] == "EXPIRED"
    assert datetime.fromisoformat(
        response.headers["X-Server-Time"].replace("Z", "+00:00")
    ) > datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    denied = await client.post(
        "/api/v1/proposals/" + proposal["proposal_id"] + "/confirmations",
        headers=buyer,
        json={"decision": "approve"},
    )
    assert denied.status_code == 409
    assert row(db, "SELECT count(*) AS n FROM orders")["n"] == 0
    assert row(db, "SELECT count(*) AS n FROM confirmations")["n"] == 0
