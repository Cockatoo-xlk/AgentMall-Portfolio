"""Independent-review counterexamples. Real pipe, API boundary and frozen scorer."""

import copy
import os

import httpx
import pytest
from evals.smoke_runner import SmokeOperator, SmokeStopped, export_evidence
from test_v217_live1_transport import initialized, price


async def test_partial_pipe_input_does_not_block_deadlines_and_preserves_buffer():
    from evals import smoke_cli

    assert hasattr(smoke_cli, "ConsoleInput"), "Nonblocking buffered input is missing"
    reader, writer = os.pipe()
    try:
        source = smoke_cli.ConsoleInput(reader)
        os.write(writer, b'{"op":')
        with pytest.raises(TimeoutError):
            await source.line(0.02)
        os.write(writer, b'"inspect"}\n{"op":"freeze"}\n')
        assert await source.line(0.5) == '{"op":"inspect"}\n'
        assert await source.line(0.5) == '{"op":"freeze"}\n'
        os.close(writer)
        writer = None
        assert await source.line(0.5) == ""
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)


@pytest.mark.parametrize(
    "code", ["ACTOR_CHANGED", "DATABASE_UNAVAILABLE", "BUDGET_EXCEEDED", "CONTEXT_SCOPE_VIOLATION"]
)
async def test_http200_fatal_run_stops_entire_batch(tmp_path, code):
    m, gate, app, scope = initialized(tmp_path)
    provider = await m.attach_smoke_models(
        app,
        gate,
        tmp_path,
        price(),
        lambda role: httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    body = {
        "id": str(scope.run_id),
        "thread_id": str(scope.thread_id),
        "status": "PARTIAL",
        "last_error": code,
        "result": {"error_codes": [code]},
    }
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
            base_url="http://127.0.0.1",
        ) as client:
            operator = SmokeOperator(client, {}, gate, provider.ledger)
            with pytest.raises(SmokeStopped, match=code):
                await operator.start(str(scope.thread_id), "request", "CONTRACT_TEST_ONLY")
        assert gate.read()["stop_code"] == code
    finally:
        await provider.close()


@pytest.mark.parametrize("fault", ["ledger", "auth"])
async def test_cached_api_receipt_does_not_bypass_ledger_or_actor_checks(tmp_path, fault):
    m, gate, app, _ = initialized(tmp_path)
    provider = await m.attach_smoke_models(
        app,
        gate,
        tmp_path,
        price(),
        lambda role: httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(201, json={"id": "contract-thread"})

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://127.0.0.1"
        ) as client:
            operator = SmokeOperator(
                client, {"Authorization": "synthetic-buyer1"}, gate, provider.ledger
            )
            assert await operator.create_thread() == "contract-thread"
            if fault == "ledger":
                (tmp_path / "ledger.json").write_text("{}")
            else:
                operator.auth = {"Authorization": "synthetic-buyer2"}
            with pytest.raises(SmokeStopped):
                await operator.create_thread()
        assert len(calls) == 1
        assert gate.read()["stop_code"]
    finally:
        await provider.close()


def valid_read_evidence():
    attributes = {"switch": "静音轴", "connection_capabilities": ["wired", "wireless"]}
    products = [
        {
            "id": p,
            "store_id": "store",
            "active": True,
            "price_cents": 19900,
            "on_hand": 20,
            "reserved": 0,
            "attributes": attributes,
        }
        for p in ("p1", "p2")
    ]
    facts = {
        "orders": [],
        "cases": [],
        "confirmations": [],
        "proposals": [],
        "items": [],
        "products": products,
        "payments": 0,
        "refunds": 0,
        "checkpoint_count": 2,
        "runs": [
            {
                "id": "run",
                "thread_id": "thread",
                "status": "COMPLETED",
                "has_worker": False,
                "has_lock": False,
                "event_seq": 1,
            }
        ],
    }
    return {
        "case_index": 0,
        "task_id": "CONTRACT_TEST_ONLY",
        "actor_binding": {"user_id": "buyer", "store_id": "store"},
        "run": {"id": "run", "thread_id": "thread", "status": "COMPLETED"},
        "baseline": copy.deepcopy(facts),
        "after": facts,
        "events": [{"seq": 1}],
        "product_facts": [
            {
                "id": p["id"],
                "data": {
                    "price_cents": p["price_cents"],
                    "attributes": attributes,
                    "available": 20,
                },
            }
            for p in products
        ],
        "ledger": {
            "halted": None,
            "attempts": [
                {
                    "state": "SETTLED",
                    "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    "held_cny": "0.00036",
                }
            ],
        },
    }


@pytest.mark.parametrize(
    "field,value", [("available", 999), ("store_id", "other"), ("on_hand", 999), ("reserved", 99)]
)
def test_scoring_rejects_stock_and_ownership_mismatch(tmp_path, field, value):
    from evals.smoke_assertions import score_verified

    evidence = valid_read_evidence()
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    export_evidence(good, evidence)
    assert score_verified(good)["status"] == "PASS"
    evidence["product_facts"][0]["data"][field] = value
    export_evidence(bad, evidence)
    assert score_verified(bad)["status"] == "FAIL"


@pytest.mark.parametrize("fault", ["payment", "refund", "reserved", "on_hand"])
def test_preapproval_business_side_effect_cannot_be_hidden_by_final_facts(tmp_path, fault):
    from evals.smoke_assertions import score_verified

    evidence = valid_read_evidence()
    evidence["case_index"] = 1
    evidence["baseline"]["products"][0]["name"] = "宿舍静音 K68"
    evidence["after"]["products"][0]["name"] = "宿舍静音 K68"
    before = copy.deepcopy(evidence["baseline"])
    after = evidence["after"]
    after["orders"] = [
        {
            "id": "order",
            "proposal_id": "proposal",
            "status": "PENDING_PAYMENT",
            "address_label": "demo_dorm",
            "total_cents": 39800,
        }
    ]
    after["orders"][0].update(user_id="buyer", store_id="store")
    after["items"] = [
        {"order_id": "order", "product_id": "p1", "quantity": 2, "unit_price_cents": 19900}
    ]
    after["confirmations"] = [
        {"id": "confirmation", "decision": "approve", "consumed_at": "test", "result_ref": "order"}
    ]
    after["confirmations"][0].update(proposal_id="proposal", actor_id="buyer", store_id="store")
    after["proposals"] = [
        {"id": "proposal", "actor_id": "buyer", "store_id": "store", "action_type": "CHECKOUT"}
    ]
    after["receipts"] = [
        {"action_id": "proposal", "operation": "execute_checkout", "result": {"order_id": "order"}}
    ]
    after["products"][0]["reserved"] = 2
    evidence["stage_facts"] = [{"stage": "before-decision", "facts": before}]
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    export_evidence(good, evidence)
    assert score_verified(good)["status"] == "PASS"
    if fault in {"payment", "refund"}:
        before[fault + "s"] += 1
    else:
        before["products"][0][fault] += 1
    export_evidence(bad, evidence)
    assert score_verified(bad)["status"] == "FAIL"
