"""CONTRACT_TEST_ONLY. Synthetic clocks/credentials; no Smoke evaluation episodes."""

import importlib
import importlib.util
import json
from uuid import uuid4

import pytest
from test_v217_smoke_contract import proposal


def implementation():
    assert importlib.util.find_spec("evals.smoke_runner"), "Smoke execution gates are missing"
    return importlib.import_module("evals.smoke_runner")


def gate(tmp_path):
    now = [1000.0]
    return implementation().SmokeBatch(
        tmp_path / "batch.json", proposal(), "a" * 64, clock=lambda: now[0]
    ), now


def test_live_without_owner_cannot_create_ledger_or_read_credentials(tmp_path):
    m = implementation()
    with pytest.raises(m.SmokeStopped, match="OWNER_AUTHORIZATION_REQUIRED"):
        m.SmokeBatch(tmp_path / "batch.json", proposal(), "a" * 64, mode="LIVE_DEEPSEEK")
    assert not list(tmp_path.iterdir())


def test_authorization_wait_does_not_start_outer_and_outer_precedes_setup(tmp_path):
    g, clock = gate(tmp_path)
    clock[0] += 500
    assert g.read()["tasks"] == []
    current = g.arm("contract-A")
    assert current["outer_started_at"] == clock[0]
    assert current["episode_started_at"] is None
    assert g.remaining() == 300
    clock[0] += 299
    assert g.remaining() == 1
    clock[0] += 2
    with pytest.raises(implementation().SmokeStopped, match="OUTER_EXPIRED"):
        g.check()
    assert g.read()["stop_code"] == "OUTER_EXPIRED"


def test_episode_includes_both_hitl_waits_and_cannot_reset(tmp_path):
    g, clock = gate(tmp_path)
    g.arm("contract-A")
    g.initialized(str(uuid4()), "test_" + uuid4().hex, "cp_" + uuid4().hex)
    g.start_episode()
    clock[0] += 44
    g.check()
    clock[0] += 44
    g.check()
    assert g.remaining() == 2
    with pytest.raises(implementation().SmokeStopped, match="EPISODE_ALREADY_STARTED"):
        g.start_episode()
    clock[0] += 3
    with pytest.raises(implementation().SmokeStopped, match="EPISODE_EXPIRED"):
        g.check()


def test_restart_is_read_only_and_order_and_full_fee_hold_are_durable(tmp_path):
    g, _ = gate(tmp_path)
    with pytest.raises(implementation().SmokeStopped, match="TASK_ORDER"):
        g.arm("contract-B")
    # Rejected preflight is not an authorized execution or fee consumption.
    assert g.read()["tasks"] == []
    g.arm("contract-A")
    assert g.read()["task_fee_holds_cny"] == "2.50"
    other = implementation().SmokeBatch(tmp_path / "batch.json", proposal(), "a" * 64)
    with pytest.raises(implementation().SmokeStopped, match="READ_ONLY_REATTACH"):
        other.arm("contract-A")
    assert other.read()["tasks"] == g.read()["tasks"]


def test_unknown_is_irreversible_and_retains_original_receipt(tmp_path):
    g, _ = gate(tmp_path)
    g.arm("contract-A")
    g.stop("BUSINESS_WRITE_UNKNOWN")
    with pytest.raises(implementation().SmokeStopped, match="BUSINESS_WRITE_UNKNOWN"):
        g.check()
    with pytest.raises(implementation().SmokeStopped):
        g.arm("contract-B")
    assert len(json.loads((tmp_path / "batch.json").read_text())["tasks"]) == 1


def test_completed_episode_does_not_consume_export_or_next_task_time(tmp_path):
    g, clock = gate(tmp_path)
    g.arm("contract-A")
    g.initialized(str(uuid4()), "test_" + uuid4().hex, "cp_" + uuid4().hex)
    g.start_episode()
    clock[0] += 85
    assert hasattr(g, "end_episode"), "Episode completion boundary is missing"
    g.end_episode()
    clock[0] += 30
    g.check()  # Export still belongs to Outer300; HITL was already counted in85.
    assert g.remaining() == 185
    g.verified("c" * 64)
    clock[0] += 500
    g.arm("contract-B")
    assert g.remaining() == 300
    assert g.read()["task_fee_holds_cny"] == "5.00"


def test_freeze_export_verify_required_before_scoring_and_cleanup(tmp_path):
    m = implementation()
    with pytest.raises(m.SmokeStopped, match="VERIFIED_EVIDENCE_REQUIRED"):
        m.load_verified(tmp_path)


def test_anonymous_fd_synthetic_credential_is_single_use_and_never_logged():
    import os

    m = implementation()
    read, write = os.pipe()
    os.write(write, b"synthetic-contract-secret\n")
    os.close(write)
    source = m.FdCredential(read)
    assert source.take() == "synthetic-contract-secret"
    with pytest.raises(m.SmokeStopped, match="CREDENTIAL_ALREADY_USED"):
        source.take()
    with pytest.raises(OSError):
        os.fstat(read)


def test_incompatible_business_inputs_cannot_be_called_live_ready():
    m = implementation()
    assert hasattr(m, "static_admission"), "Executable input compatibility admission missing"
    p = proposal()
    p["tasks"][1]["user_request"] = "预算199元，准备购买两件静音键盘，送演示宿舍。"
    p["tasks"][2]["user_request"] = "不要退货，只准备购买一件静音键盘，送演示宿舍。"
    report = m.static_admission(p)
    assert report["state"] == "BLOCKED"
    assert "B_TOTAL_PRICE_CONFLICT" in report["codes"]
    assert "C_RETURN_INTENT_UNSUPPORTED" in report["codes"]
