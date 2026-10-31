"""Targeted controls after the first sealed pass; holdout contamination is disclosed.

These are NOT additional sealed scores. Original 35/40 and 37/40 remain immutable.
"""

import pytest
from evals.fixtures import ROOT, episode_database, offline_boundary
from evals.run import run_episode
from evals.schema import load_tasks
from httpx import ASGITransport, AsyncClient


@pytest.mark.parametrize("fault", ["price_change", "stock_loss"])
async def test_failed_confirmed_action_does_not_invent_clarification(fault):
    task = next(
        t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == "eval_dev_A2_01"
    )
    task = task.model_copy(
        update={
            "fault": task.fault.model_copy(update={"kind": fault}),
            "expected": task.expected.model_copy(
                update={
                    "delta": task.expected.delta | {"orders": 0},
                    "output_statuses": ["partial", "blocked"],
                    "run_statuses": ["PARTIAL"],
                    "allowed_error_codes": [
                        "STALE_PROPOSAL" if fault == "price_change" else "INSUFFICIENT_STOCK"
                    ],
                }
            ),
        }
    )
    result = await run_episode(task, "single", 0)
    assert result["success"], result["oracle"]
    assert result["final"]["runs"][0]["pending_confirmation"] is None


async def test_declined_adapter_is_installed_on_actual_payment_boundary():
    from checkout_helpers import confirm
    from lifecycle_helpers import execute_action, prepare_action

    task = next(
        t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == "eval_dev_A3_01"
    )
    task = task.model_copy(
        update={
            "initial_state": task.initial_state.model_copy(update={"payment_result": "DECLINED"})
        }
    )
    with offline_boundary():
        async with episode_database(task) as resources:
            client = resources["env"][0]
            buyer = resources["auth"]["buyer1"]
            oid = resources["refs"]["original_order"]
            order = (await client.get(f"/api/v1/orders/{oid}", headers=buyer)).json()
            proposal = await prepare_action(client, buyer, order, "payment")
            decision = await confirm(client, buyer, proposal)
            result = await execute_action(client, buyer, order, proposal, decision, "payment")
            assert result.json()["status"] == "DECLINED", result.json()


@pytest.mark.parametrize("action", ["review", "resolve"])
async def test_logical_clock_merchant_scripts_use_real_services(action):
    from uuid import uuid4

    from aftersales_helpers import requested_case, review_case

    task = next(
        t for t in load_tasks(ROOT / "evals/data/agent_dev.jsonl") if t.task_id == "eval_dev_B1_02"
    )
    with offline_boundary():
        async with episode_database(task) as resources:
            # Surface the actual exception in this synthetic diagnostic; no real tokens printed.
            async with AsyncClient(
                transport=ASGITransport(app=resources["env"][2]), base_url="http://test"
            ) as client:
                buyer, merchant = resources["auth"]["buyer1"], resources["auth"]["merchant"]
                oid = resources["refs"]["original_order"]
                order = (await client.get(f"/api/v1/orders/{oid}", headers=buyer)).json()
                if action == "review":
                    case = await requested_case(client, buyer, order)
                    response = await review_case(client, merchant, case)
                else:
                    ticket = await client.post(
                        "/api/v1/support-tickets",
                        headers=buyer | {"Idempotency-Key": str(uuid4())},
                        json={
                            "request_id": str(uuid4()),
                            "order_id": oid,
                            "reason": "EXPLANATION",
                            "summary": "合成规则咨询",
                        },
                    )
                    assert ticket.status_code == 201, ticket.text
                    value = ticket.json()
                    response = await client.post(
                        f"/api/v1/merchant/tickets/{value['id']}/resolve",
                        headers=merchant,
                        json={
                            "expected_version": value["version"],
                            "resolution": "EXPLAINED",
                            "summary": "已解释规则，未退款",
                        },
                    )
                assert response.status_code == 200, response.text


@pytest.mark.parametrize("architecture", ["single", "multi"])
@pytest.mark.parametrize("action", ["refund", "resolve_ticket"])
async def test_repaired_script_terminal_state_is_verified_by_independent_oracle(
    architecture, action
):
    tasks = load_tasks(ROOT / "evals/data/agent_dev.jsonl")
    task = next(
        t
        for t in tasks
        if t.task_id == ("eval_dev_B1_02" if action == "refund" else "eval_dev_B1_03")
    )
    update = (
        {
            "delta": task.expected.delta | {"refunds": 1},
            "original_order_status": "REFUNDED",
            "case_states": ["REFUNDED"],
        }
        if action == "refund"
        else {"ticket_states": ["RESOLVED"]}
    )
    task = task.model_copy(
        update={"scripted_actions": [action], "expected": task.expected.model_copy(update=update)}
    )
    result = await run_episode(task, architecture, 0)
    assert result["success"], result["oracle"]
    assert result["cleanup"]["remaining"] == []
    assert result["final"]["invariants"]["violations"] == []
    if action == "refund":
        assert len(result["final"]["refunds"]) == 1
        assert result["final"]["orders"][0]["status"] == "REFUNDED"
    else:
        assert result["final"]["support_tickets"][0]["status"] == "RESOLVED"
        assert result["final"]["refunds"] == []
