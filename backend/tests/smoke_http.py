"""Explicit local HTTP smoke. Leaves one synthetic order; stable keys make reruns safe.

Run from repository root with the local API already listening on port 8000:
  uv run --project backend python backend/tests/smoke_http.py
"""

import json

import httpx


def main():
    statuses = {}
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", trust_env=False) as client:
        login = client.post(
            "/auth/login", json={"login": "buyer1", "password": "AgentMall-demo-2026!"}
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        products = client.get(
            "/products", params={"category": "keyboard", "max_price_cents": 30000}
        )
        products.raise_for_status()
        pid = products.json()["items"][0]["id"]
        proposal = client.post(
            "/checkout/proposals",
            headers={"Idempotency-Key": "t02-http-prepare-v1"},
            json={
                "request_id": "00000000-0000-0000-0000-000000002002",
                "proposal_slot": "http-smoke",
                "address_label": "demo_dorm",
                "items": [{"product_id": pid, "quantity": 1}],
            },
        )
        proposal.raise_for_status()
        proposal_id = proposal.json()["proposal_id"]
        statuses["proposal"] = proposal.status_code
        confirmation = client.post(
            f"/proposals/{proposal_id}/confirmations", json={"decision": "approve"}
        )
        confirmation.raise_for_status()
        statuses["confirmation"] = confirmation.status_code
        body = {
            "proposal_id": proposal_id,
            "confirmation_id": confirmation.json()["confirmation_id"],
        }
        order = client.post("/orders", headers={"Idempotency-Key": "t02-http-order-v1"}, json=body)
        order.raise_for_status()
        statuses["order"] = order.status_code
        replay = client.post("/orders", headers={"Idempotency-Key": "t02-http-order-v1"}, json=body)
        assert replay.status_code == 200 and replay.json() == order.json()
        statuses["replay"] = replay.status_code
        order_id = order.json()["order_id"]
        detail = client.get(f"/orders/{order_id}")
        detail.raise_for_status()
        assert detail.json()["status"] == "PENDING_PAYMENT"
        assert detail.json()["total_cents"] == proposal.json()["canonical_payload"]["total_cents"]
        recovered = client.get(f"/proposals/{proposal_id}")
        assert recovered.json()["result"] == order.json()
        other = client.post(
            "/auth/login", json={"login": "buyer2", "password": "AgentMall-demo-2026!"}
        )
        other.raise_for_status()
        denied = client.get(
            f"/orders/{order_id}",
            headers={"Authorization": "Bearer " + other.json()["access_token"]},
        )
        assert denied.status_code == 404
        statuses["cross_user"] = denied.status_code
        print(
            json.dumps(
                {
                    "statuses": statuses,
                    "proposal_id": proposal_id,
                    "order_id": order_id,
                    "product_id": pid,
                    "total_cents": detail.json()["total_cents"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
