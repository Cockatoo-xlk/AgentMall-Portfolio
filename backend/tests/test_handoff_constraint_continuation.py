"""RECONSTRUCTED_FIXTURE, not the missing historical DeepSeek ToolCall."""

import copy

import pytest
from conftest import row
from multiagent_helpers import payload, route
from t09_helpers import confirm, resume, two_proposals
from t09_helpers import durable_env as durable_env


def drifting(field, value, subtask="replacement"):
    return route(
        "shopping",
        "find_products",
        subtask,
        change=lambda task: task["constraints"].update({field: value}),
    )


@pytest.mark.parametrize("second_drift", [False, True])
async def test_return_resume_keeps_constraints_and_independent_confirmations(
    durable_env, buyer, product, second_drift
):
    env = durable_env
    tid, first, _ = await two_proposals(env, buyer, product)
    # delivered_order consumed checkout AND payment confirmations during setup.
    before_confirmations = row(
        env[1], "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL"
    )["n"]
    assert first["status"] == "WAITING_INPUT"
    models = env[2].state.multi_models
    canonical = copy.deepcopy(payload(models["supervisor"].seen[0])["canonical_constraints"])
    assert canonical["purchase_requested"] and canonical["return_requested"]
    assert canonical["exclude_original"] and canonical["exclude_product_ids"] == [product]
    assert canonical["max_price_cents"] == 50000 and canonical["quantity"] == 1
    original_request = row(env[1], "SELECT request_payload FROM agent_runs")["request_payload"]
    models["supervisor"].script.insert(0, drifting("quantity", 2))
    if second_drift:
        models["supervisor"].script[-1] = drifting("quantity", 2, "late_drift")
    cid1 = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
    second = (await resume(env, buyer, tid, first, cid1)).json()
    assert second["status"] == "WAITING_INPUT", second
    assert second["pending_confirmation"]["action_type"] == "CHECKOUT"
    assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert all(payload(m)["canonical_constraints"] == canonical for m in models["supervisor"].seen)
    assert (
        payload(models["supervisor"].seen[3])["orchestration_feedback"]["error_code"]
        == "HANDOFF_CONSTRAINT_CHANGED"
    )
    assert (await resume(env, buyer, tid, second, cid1)).status_code == 409
    cid2 = await confirm(env, buyer, second["pending_confirmation"]["proposal_id"])
    assert cid1 != cid2
    done = (await resume(env, buyer, tid, second, cid2)).json()
    assert done["status"] == ("PARTIAL" if second_drift else "COMPLETED"), done
    assert done["budget"]["models"] == 10
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 2
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 1
    assert (
        row(env[1], "SELECT count(*) n FROM confirmations WHERE consumed_at IS NOT NULL")["n"]
        == before_confirmations + 2
    )
    for confirmation in (cid1, cid2):
        assert (
            row(env[1], "SELECT consumed_at FROM confirmations WHERE id=:id", id=confirmation)[
                "consumed_at"
            ]
            is not None
        )
    record = row(env[1], "SELECT request_payload,budget FROM agent_runs")
    assert record["request_payload"] == original_request
    assert record["budget"]["orchestration_repair"]["error_code"] == "HANDOFF_CONSTRAINT_CHANGED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_price_cents", 99999),
        ("quantity", 2),
        ("exclude_product_ids", []),
        ("address_label", "demo_home"),
        ("purchase_requested", False),
        ("noise_preference", None),
    ],
)
async def test_still_drifting_tasks_are_rejected_without_losing_case(
    durable_env, buyer, product, field, value
):
    env = durable_env
    tid, first, _ = await two_proposals(env, buyer, product)
    models = env[2].state.multi_models
    models["supervisor"].script = [drifting(field, value), drifting(field, value)]
    cid = await confirm(env, buyer, first["pending_confirmation"]["proposal_id"])
    done = (await resume(env, buyer, tid, first, cid)).json()
    assert done["status"] == "PARTIAL"
    assert "HANDOFF_CONSTRAINT_CHANGED" in done["result"]["error_codes"]
    assert done["budget"]["models"] == 6
    assert done["budget"]["delegations"] == 2
    assert not models["shopping"].seen
    assert row(env[1], "SELECT count(*) n FROM orders")["n"] == 1
    assert row(env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
    assert (
        row(env[1], "SELECT count(*) n FROM action_proposals WHERE action_type='CHECKOUT'")["n"]
        == 1
    )  # original order only


@pytest.mark.parametrize("cap", [3, 4, 6])
async def test_constraint_correction_cannot_extend_model_budget(
    durable_env, buyer, product, monkeypatch, cap
):
    from agentmall.agents import run_service
    from agentmall.agents.budgets import Limits
    from agentmall.agents.durable_budget import DurableBudget

    monkeypatch.setattr(
        run_service, "DurableBudget", lambda fence: DurableBudget(fence, Limits(models=cap))
    )
    tid, first, _ = await two_proposals(durable_env, buyer, product)
    if cap == 3:
        # The completed assessment leaves no room for a preparation at three calls.
        # Keep that boundary covered: never grant a free preparation call.
        assert first["status"] == "PARTIAL", first
        assert first["budget"]["models"] == cap
        assert "BUDGET_EXCEEDED" in first["result"]["error_codes"]
        assert row(durable_env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
        assert (
            row(
                durable_env[1],
                "SELECT count(*) n FROM action_proposals WHERE action_type='RETURN_REQUEST'",
            )["n"]
            == 0
        )
        return
    assert first["status"] == "WAITING_INPUT"
    models = durable_env[2].state.multi_models
    models["supervisor"].script.insert(0, drifting("quantity", 2))
    cid = await confirm(durable_env, buyer, first["pending_confirmation"]["proposal_id"])
    done = (await resume(durable_env, buyer, tid, first, cid)).json()
    assert done["budget"]["models"] == cap
    assert "BUDGET_EXCEEDED" in done["result"]["error_codes"]
    assert row(durable_env[1], "SELECT status FROM aftersales_cases")["status"] == "REQUESTED"
    assert not models["shopping"].seen
