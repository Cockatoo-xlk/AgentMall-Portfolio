"""Real disposable PG, explicit synthetic operator decisions, no Live task execution."""

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from evals.smoke_assertions import score_verified
from evals.smoke_runner import SmokeBatch, SmokeStopped
from evals.smoke_session import SmokeSession, sql_facts
from test_v217_live1_integration import SingleWire
from test_v217_live1_transport import price
from test_v217_smoke_contract import proposal

from agentmall.seed import DEMO_PASSWORD


async def test_initial_provider_unknown_keeps_run_queryable_and_exports_read_only(env, tmp_path):
    from retrieval_helpers import FixtureEncoder

    p = proposal()
    p["tasks"][0]["user_request"] = "推荐一款300元以内静音键盘，仅供选择，不购买。"
    gate = SmokeBatch(tmp_path / "batch.json", p, "f" * 64)
    gate.arm("contract-A")
    s = SmokeSession(gate, tmp_path / "unknown")
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(503, json={"error": "synthetic-contract"})

    try:
        await s.initialize(
            env[3].database_url.get_secret_value(),
            price(),
            encoder_factory=FixtureEncoder,
            transport_factory=lambda role: httpx.MockTransport(fail),
        )
        with pytest.raises(SmokeStopped):
            await s.start()
        assert gate.read()["stop_code"]
        _, evidence = await s.freeze_export_verify()
        assert evidence["run"]["id"] == sql_facts(s.settings)["runs"][0]["id"]
        assert evidence["ledger"]["attempts"][0]["state"] == "STOPPED"
        assert score_verified(s.directory)["status"] == "NOT_SCORED"
        assert len(calls) == 1
        assert evidence["after"]["orders"] == []
    finally:
        await s.close()


@pytest.fixture
async def pending_purchase(env, tmp_path):
    from retrieval_helpers import FixtureEncoder

    p = proposal()
    p["tasks"][0]["user_request"] = "推荐一款300元以内静音键盘，仅供选择，不购买。"
    p["tasks"][1]["user_request"] = "预算600元，推荐静音键盘，准备购买两件，送演示宿舍。"
    gate = SmokeBatch(tmp_path / "batch.json", p, "d" * 64)
    sessions = []
    for task in p["tasks"][:2]:
        gate.arm(task["id"])
        s = SmokeSession(gate, tmp_path / task["id"])
        sessions.append(s)
        await s.initialize(
            env[3].database_url.get_secret_value(),
            price(),
            encoder_factory=FixtureEncoder,
            transport_factory=SingleWire().transport,
        )
        run = await s.start()
        if task["id"] == "contract-A":
            assert run["status"] == "COMPLETED"
            h, _ = await s.freeze_export_verify()
            gate.verified(h)
            await s.close()
            await s.cleanup("CONTRACT_TEST_ONLY-fixture-prelude")
    try:
        assert run["status"] == "WAITING_INPUT"
        yield s, gate
    finally:
        for s in sessions:
            await s.close()


async def test_explicit_rejection_has_no_transaction_and_known_fail_can_finalize(pending_purchase):
    s, gate = pending_purchase
    inspection = await s.inspect()
    c = await s.decide(inspection, "reject", operator="TEST_OPERATOR_CODEX")
    done = await s.resume(inspection, c["confirmation_id"], str(uuid4()))
    assert done["status"] == "COMPLETED"
    assert sql_facts(s.settings)["orders"] == []
    h, _ = await s.freeze_export_verify()
    result = score_verified(s.directory)
    assert result["status"] == "FAIL" and "ORDER_DELTA" in result["violations"]
    gate.verified(h)
    await s.close()
    await s.cleanup("CONTRACT_TEST_ONLY-explicit-independent-cleanup")


async def test_expired_snapshot_refuses_approval_without_new_model_or_order(
    pending_purchase, monkeypatch
):
    from agentmall.actions import service

    s, _ = pending_purchase
    inspection = await s.inspect()
    original = service.database_now

    async def future(session):
        return await original(session) + timedelta(days=1)

    monkeypatch.setattr(service, "database_now", future)
    calls = len(s.provider.ledger.read()["attempts"])
    with pytest.raises(SmokeStopped, match="PROPOSAL_SNAPSHOT_CHANGED"):
        await s.decide(inspection, "approve", operator="TEST_OPERATOR_CODEX")
    assert sql_facts(s.settings)["orders"] == []
    assert sql_facts(s.settings)["confirmations"] == []
    assert len(s.provider.ledger.read()["attempts"]) == calls


async def test_unknown_confirmation_write_halts_and_blocks_cleanup(pending_purchase, monkeypatch):
    s, gate = pending_purchase
    inspection = await s.inspect()
    original = s.client.request

    async def fail(method, path, **kwargs):
        if method == "POST" and path.endswith("/confirmations"):
            return httpx.Response(503, json={"code": "DATABASE_UNAVAILABLE"})
        return await original(method, path, **kwargs)

    monkeypatch.setattr(s.client, "request", fail)
    with pytest.raises(SmokeStopped, match="BUSINESS_WRITE_UNKNOWN"):
        await s.decide(inspection, "approve", operator="TEST_OPERATOR_CODEX")
    assert gate.read()["stop_code"] == "BUSINESS_WRITE_UNKNOWN"
    assert sql_facts(s.settings)["orders"] == []
    await s.freeze_export_verify()
    await s.close()
    with pytest.raises(SmokeStopped, match="CLEANUP_ADMISSION_REJECTED"):
        await s.cleanup("CONTRACT_TEST_ONLY-must-preserve")
    with pytest.raises(SmokeStopped):
        gate.arm("contract-C")


async def test_cross_actor_get_is_global_stop_not_a_new_task(pending_purchase):
    s, gate = pending_purchase
    login = await s.client.post(
        "/api/v1/auth/login", json={"login": "buyer2", "password": DEMO_PASSWORD}
    )
    s.operator.auth = {"Authorization": "Bearer " + login.json()["access_token"]}
    with pytest.raises(SmokeStopped, match="ACTOR_OR_STORE_REJECTED"):
        await s.inspect()
    assert gate.read()["stop_code"] == "ACTOR_OR_STORE_REJECTED"
    assert sql_facts(s.settings)["orders"] == []


async def test_freezing_waiting_run_permanently_closes_operator_write_path(pending_purchase):
    s, _ = pending_purchase
    inspection = await s.inspect()
    await s.freeze_export_verify()
    with pytest.raises(SmokeStopped, match="SESSION_FROZEN"):
        await s.decide(inspection, "approve", operator="TEST_OPERATOR_CODEX")
    assert sql_facts(s.settings)["confirmations"] == []
    assert sql_facts(s.settings)["orders"] == []
