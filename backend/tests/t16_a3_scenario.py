"""The exact three-turn scenario using unchanged ContextSDK and real domain APIs."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from multiturn_helpers import ContextSDK
from t16_a3_oracle import capture, checkpoints, validate

from agentmall.main import create_app
from agentmall.playground.app import attach_models
from agentmall.playground.environment import private_write
from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint
from agentmall.seed import DEMO_PASSWORD

MESSAGES = [
    "推荐300元以内的静音键盘，不要购买。",
    "我改主意了，要支持无线连接的，预算提高到400元。",
    "就买刚才推荐的第二款，一件，送演示宿舍。",
]


async def run(settings, environment_id, encoder, state_dir):
    from integration.oracle import inspect_database

    app = create_app(settings)
    app.state.retrieval_encoder = encoder
    program = ContextSDK()
    policy = PlaygroundPolicy(
        enabled=True,
        evidence_mode="MOCK_TRANSPORT",
        session_id=uuid4(),
        environment_id=environment_id,
        source_sha256=source_fingerprint(),
        price_checked_at=datetime.now(UTC),
        max_model_calls=24,
        max_cost_cny="5",
        max_wall_seconds=900,
        max_input_tokens=2097152,
        max_output_tokens=36000,
    )
    private_write(state_dir / "mock-policy.json", policy.model_dump(mode="json"))
    provider = attach_models(
        app, policy, state_dir, "SYNTHETIC-MOCK-NO-REAL-KEY", program.transport
    )
    baseline = capture(settings)
    general_before = inspect_database((None, None, None, settings))
    assert general_before["violations"] == []
    runs, requests = [], []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:

            async def login():
                result = await client.post(
                    "/api/v1/auth/login", json={"login": "buyer1", "password": DEMO_PASSWORD}
                )
                assert result.status_code == 200
                return {"Authorization": "Bearer " + result.json()["access_token"]}

            headers = await login()
            me = (await client.get("/api/v1/me", headers=headers)).json()
            tr = await client.post("/api/v1/agent/threads", headers=headers, json={"mode": "multi"})
            assert tr.status_code == 201
            tid = tr.json()["id"]

            async def context():
                result = await client.get("/api/v1/agent/threads/" + tid, headers=headers)
                assert result.status_code == 200
                return result.json()["context"]

            version, current = 0, None
            for i, message in enumerate(MESSAGES):
                body = {
                    "request_id": str(uuid4()),
                    "message": message,
                    "expected_context_version": version,
                }
                if i == 2:
                    listing = current["candidate_sets"][0]
                    assert listing["valid"] and len(listing["items"]) >= 2
                    target = listing["items"][1]
                    body["candidate_set_id"] = listing["id"]
                response = await client.post(
                    f"/api/v1/agent/threads/{tid}/runs", headers=headers, json=body
                )
                assert response.status_code == 201, response.text
                result = response.json()
                current = await context()
                version = current["version"]
                requests.append(body)
                runs.append(
                    {
                        "run_id": result["id"],
                        "status": result["status"],
                        "context": current,
                        "input": message,
                    }
                )
                if i < 2:
                    assert (
                        result["status"] == "COMPLETED"
                        and result["result"]["status"] != "needs_input"
                    )
                    offered = current["candidate_sets"][0]
                    assert offered["valid"] and len(offered["items"]) >= (1 if i == 0 else 2)
                    facts = capture(settings)
                    assert all(
                        not facts[t]
                        for t in ["orders", "action_proposals", "confirmations", "payments"]
                    )
                    if i == 1:
                        assert current["preferences"]["max_price_cents"] == 40000
                        assert (
                            current["preferences"]["category"] == "keyboard"
                            and current["preferences"]["noise_preference"] == "quiet"
                        )
                        first = runs[0]["context"]["candidate_sets"][0]["id"]
                        assert offered["id"] != first
                        assert not any(
                            s["id"] == first and s["valid"] for s in current["candidate_sets"]
                        )
                else:
                    assert result["status"] == "WAITING_INPUT"
                    assert result["context_snapshot"]["selected"][0]["id"] == target["id"]
                    waiting = result

            historical = await client.get("/api/v1/agent/threads/" + tid, headers=headers)
            assert historical.status_code == 200
            old_run = next(r for r in historical.json()["runs"] if r["id"] == runs[0]["run_id"])
            assert old_run["result"]["entity_refs"]
            assert old_run["context_snapshot"]["constraints"]["max_price_cents"] == 30000
            before = capture(settings)
            assert (
                len(before["action_proposals"]) == 1
                and not before["orders"]
                and not before["confirmations"]
                and not before["payments"]
            )
            # Start replay, then fresh login and normal authenticated Thread recovery.
            repeated = await client.post(
                f"/api/v1/agent/threads/{tid}/runs", headers=headers, json=requests[-1]
            )
            assert repeated.status_code == 200 and repeated.json()["id"] == waiting["id"]
            headers = await login()
            recovered = await context()
            assert (
                recovered["version"] == version
                and recovered["candidate_sets"][0]["items"][1]["id"] == target["id"]
            )
            pending = waiting["pending_confirmation"]
            pid = pending["proposal_id"]
            proposal = await client.get("/api/v1/proposals/" + pid, headers=headers)
            assert proposal.status_code == 200
            item = proposal.json()["canonical_payload"]["items"][0]
            assert item["product_id"] == target["id"] and item["quantity"] == 1
            confirmed = await client.post(
                f"/api/v1/proposals/{pid}/confirmations",
                headers=headers,
                json={"decision": "approve"},
            )
            assert confirmed.status_code == 201
            cid = confirmed.json()["confirmation_id"]
            resume = {
                "request_id": str(uuid4()),
                "run_id": waiting["id"],
                "interrupt_id": pending["interrupt_id"],
                "proposal_id": pid,
                "confirmation_id": cid,
            }
            done = await client.post(
                f"/api/v1/agent/threads/{tid}/resume", headers=headers, json=resume
            )
            assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
            wire = len(program.requests)
            repeated = await client.post(
                f"/api/v1/agent/threads/{tid}/resume", headers=headers, json=resume
            )
            assert repeated.status_code == 200 and len(program.requests) == wire
            replay = await client.post(
                f"/api/v1/agent/threads/{tid}/runs", headers=headers, json=requests[-1]
            )
            assert replay.status_code == 200 and replay.json()["id"] == waiting["id"]

        expected = {
            "user_id": me["user_id"],
            "store_id": me["store_id"],
            "thread_id": tid,
            "run_ids": [r["run_id"] for r in runs],
            "proposal_id": pid,
            "confirmation_id": cid,
            "product_id": target["id"],
            "quantity": 1,
            "price_cents": item["unit_price_cents"],
            "address_label": "demo_dorm",
            "proposal_snapshot": before["action_proposals"][0],
            "inventory": {
                p["id"]: {"on_hand": p["on_hand"], "reserved": p["reserved"]}
                for p in baseline["products"]
            },
        }
        data = capture(settings)
        cp, cp_count = await checkpoints(settings, tid, expected["run_ids"])
        violations = validate(data, expected, cp)
        general = inspect_database((None, None, None, settings), general_before)
        assert not violations and not general["violations"], (violations, general["violations"])
        ledger = provider.ledger.read()
        assert (
            len(ledger["attempts"]) == wire and len({a["run_id"] for a in ledger["attempts"]}) == 3
        )
        # Prove the oracle detects errors without persisting an invalid business state.
        from copy import deepcopy

        corrupted = deepcopy(data)
        next(p for p in corrupted["products"] if p["id"] == target["id"])["reserved"] = 0
        assert "RESERVATION" in validate(corrupted, expected, cp)
        return {
            "status": "PASS",
            "mode": "MOCK_TRANSPORT_REAL_BGE_PG_CHECKPOINT",
            "environment_id": str(environment_id),
            "schemas": [settings.db_schema, settings.checkpoint_schema],
            "source_fingerprint": source_fingerprint(),
            "expected": expected,
            "observed": data,
            "checkpoints": cp,
            "checkpoint_rows": cp_count,
            "violations": violations,
            "general_oracle": general,
            "stages": runs,
            "before_confirmation": before,
            "mock_requests": wire,
            "mock_session_id": str(policy.session_id),
            "mock_policy_sha256": policy.binding,
            "shared_ledger_runs": sorted({a["run_id"] for a in ledger["attempts"]}),
            "repeat_added_model_requests": len(program.requests) - wire,
            "oracle_fault_control": (
                "RESERVATION detected from a deliberately corrupted copy of actual DB evidence; "
                "no invalid DB write"
            ),
            "confirmation_actor": (
                "Independent explicit offline test operator via normal authenticated "
                "Confirmation API"
            ),
            "real_provider_requests": 0,
        }
    finally:
        await provider.close()
        await app.state.engine.dispose()
