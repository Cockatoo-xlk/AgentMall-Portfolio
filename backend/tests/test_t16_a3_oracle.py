"""The evidence oracle must detect corruption and fail closed before schema cleanup."""

from copy import deepcopy
from types import SimpleNamespace

import pytest


def sample():
    """Deliberately synthetic unit data; real verification reads independent PostgreSQL rows."""
    expected = {
        "user_id": "buyer",
        "store_id": "store",
        "thread_id": "thread",
        "run_ids": ["r1", "r2", "r3"],
        "proposal_id": "proposal",
        "confirmation_id": "confirmation",
        "product_id": "sku",
        "quantity": 1,
        "price_cents": 29900,
        "inventory": {
            "sku": {"on_hand": 20, "reserved": 0},
            "other": {"on_hand": 20, "reserved": 0},
        },
    }
    observed = {
        "metadata": {"read_only": "on", "isolation": "repeatable read"},
        "orders": [
            {
                "id": "order",
                "user_id": "buyer",
                "store_id": "store",
                "proposal_id": "proposal",
                "status": "PENDING_PAYMENT",
                "total_cents": 29900,
            }
        ],
        "order_items": [
            {
                "order_id": "order",
                "product_id": "sku",
                "store_id": "store",
                "quantity": 1,
                "unit_price_cents": 29900,
            }
        ],
        "action_proposals": [
            {
                "id": "proposal",
                "actor_id": "buyer",
                "store_id": "store",
                "status": "EXECUTED",
                "action_type": "CHECKOUT",
                "canonical_payload": {
                    "items": [{"product_id": "sku", "quantity": 1, "unit_price_cents": 29900}]
                },
            }
        ],
        "confirmations": [
            {
                "id": "confirmation",
                "proposal_id": "proposal",
                "actor_id": "buyer",
                "store_id": "store",
                "decision": "approve",
                "consumed_at": "SYNTHETIC-TIME",
                "result_ref": "order",
            }
        ],
        "products": [
            {"id": "sku", "on_hand": 20, "reserved": 1},
            {"id": "other", "on_hand": 20, "reserved": 0},
        ],
        "idempotency_requests": [
            {
                "operation": "execute_checkout",
                "action_id": "proposal",
                "actor_id": "buyer",
                "store_id": "store",
                "completed_at": "SYNTHETIC-TIME",
                "result": {"resource_id": "order"},
            }
        ],
        "business_events": [
            {"event_type": "ORDER_CREATED", "aggregate_id": "order", "action_id": "proposal"}
        ],
        "agent_threads": [{"id": "thread", "user_id": "buyer", "store_id": "store"}],
        "agent_runs": [
            {"id": rid, "thread_id": "thread", "status": "COMPLETED", "event_seq": 1}
            for rid in expected["run_ids"]
        ],
        "run_events": [{"run_id": rid, "seq": 1} for rid in expected["run_ids"]],
        "payments": [],
        "aftersales_cases": [],
        "refunds": [],
        "support_tickets": [],
    }
    checkpoints = [
        {"run_id": rid, "next": "done", "pending_writes": 0, "read_only": "on"}
        for rid in expected["run_ids"]
    ]
    from agentmall.actions.service import payload_hash

    quote = observed["action_proposals"][0]
    quote["canonical_payload"].update(
        total_cents=29900, currency="CNY", address_label="demo_dorm", policy_version="demo-v1"
    )
    quote["canonical_payload"]["items"][0].update(
        name_snapshot="合成SKU", attributes_snapshot={}, catalog_version=1
    )
    quote["payload_hash"] = payload_hash(quote["canonical_payload"])
    observed["orders"][0].update(
        currency="CNY", address_label="demo_dorm", policy_version="demo-v1"
    )
    observed["order_items"][0].update(name_snapshot="合成SKU", attributes_snapshot={})
    observed["products"][0].update(
        name="合成SKU", attributes={}, catalog_version=1, price_cents=29900, store_id="store"
    )
    expected["proposal_snapshot"] = deepcopy(quote)
    expected["address_label"] = "demo_dorm"
    return expected, observed, checkpoints


@pytest.mark.parametrize(
    "change,rule",
    [
        ("stock", "RESERVATION"),
        ("other_stock", "NON_TARGET_STOCK"),
        ("confirmation", "CONFIRMATION"),
        ("total", "ORDER_ITEM"),
        ("duplicate", "SINGLE_ORDER"),
        ("event", "EVENT_SEQUENCE"),
        ("checkpoint", "CHECKPOINT"),
        ("scope", "SCOPE"),
    ],
)
def test_oracle_detects_synthetic_corruption(change, rule):
    from t16_a3_oracle import validate

    expected, data, cp = sample()
    assert validate(data, expected, cp) == []
    if change == "stock":
        data["products"][0]["reserved"] = 0
    elif change == "other_stock":
        data["products"][1]["on_hand"] = 19
    elif change == "confirmation":
        data["confirmations"][0]["result_ref"] = "wrong"
    elif change == "total":
        data["orders"][0]["total_cents"] += 1
    elif change == "duplicate":
        data["orders"].append(deepcopy(data["orders"][0]))
    elif change == "event":
        data["run_events"][0]["seq"] = 2
    elif change == "checkpoint":
        cp[0]["pending_writes"] = 1
    elif change == "scope":
        data["confirmations"][0]["actor_id"] = "other-user"
    assert rule in validate(data, expected, cp)


def payload():
    expected, observed, cp = sample()
    return {
        "status": "PASS",
        "environment_id": "owned",
        "schemas": ["test_owned", "cp_owned"],
        "expected": expected,
        "observed": observed,
        "checkpoints": cp,
        "violations": [],
    }


def test_export_failure_never_drops_owned_schemas(monkeypatch, tmp_path):
    import t16_a3_oracle as oracle

    dropped = []
    monkeypatch.setattr(oracle, "drop_owned", lambda *args: dropped.append(args))

    def failed(*args):
        raise OSError("SYNTHETIC_DISK_FAILURE")

    monkeypatch.setattr(oracle, "export", failed)
    with pytest.raises(OSError, match="SYNTHETIC_DISK_FAILURE"):
        oracle.save_then_cleanup(SimpleNamespace(), "owned", payload(), tmp_path / "oracle.json")
    assert dropped == []


def test_tampered_or_failed_oracle_cannot_authorize_cleanup(monkeypatch, tmp_path):
    import t16_a3_oracle as oracle

    path = tmp_path / "oracle.json"
    sha = oracle.export(path, payload())
    path.write_text('{"status":"PASS","tampered":true}')
    dropped = []
    monkeypatch.setattr(oracle, "drop_owned", lambda *args: dropped.append(args))
    with pytest.raises(ValueError):
        oracle.cleanup_from_verified(SimpleNamespace(), "owned", path, sha)
    assert dropped == []


def test_detected_violation_cannot_be_exported_as_pass(monkeypatch, tmp_path):
    import t16_a3_oracle as oracle

    data = payload()
    data["observed"]["confirmations"][0]["consumed_at"] = None
    monkeypatch.setattr(oracle, "drop_owned", lambda *args: pytest.fail("must retain schema"))
    with pytest.raises(ValueError):
        oracle.save_then_cleanup(SimpleNamespace(), "owned", data, tmp_path / "oracle.json")
    assert not (tmp_path / "oracle.json").exists()


@pytest.mark.parametrize(
    "change", ["quantity", "extra_item", "hash", "price", "address", "product"]
)
def test_review_proposal_order_mutations_are_rejected(change):
    from t16_a3_oracle import validate

    expected, data, cp = sample()
    assert validate(data, expected, cp) == []
    proposal = data["action_proposals"][0]
    if change == "quantity":
        proposal["canonical_payload"]["items"][0]["quantity"] = 7
    elif change == "extra_item":
        proposal["canonical_payload"]["items"].append(
            deepcopy(proposal["canonical_payload"]["items"][0])
        )
    elif change == "hash":
        proposal["payload_hash"] = "0" * 64
    elif change == "price":
        proposal["canonical_payload"]["items"][0]["unit_price_cents"] = 1
    elif change == "address":
        data["orders"][0]["address_label"] = "wrong_destination"
    elif change == "product":
        data["products"][0]["catalog_version"] = 2
    assert validate(data, expected, cp)


def test_review_directory_sync_failure_prevents_drop(monkeypatch, tmp_path):
    import os
    import stat

    import t16_a3_oracle as oracle

    fsync = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("SYNTHETIC_DIRECTORY_SYNC_FAILURE")
        fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    dropped = []
    monkeypatch.setattr(oracle, "drop_owned", lambda *args: dropped.append(args))
    settings = SimpleNamespace(db_schema="test_owned", checkpoint_schema="cp_owned")
    with pytest.raises(OSError, match="SYNTHETIC_DIRECTORY_SYNC_FAILURE"):
        oracle.save_then_cleanup(settings, "owned", payload(), tmp_path / "new" / "oracle.json")
    assert dropped == []


def test_review_existing_state_is_rejected_before_output_or_database(tmp_path):
    from scripts.verify_t16_a3 import claim_paths

    state = tmp_path / "state"
    state.mkdir()
    marker = state / "environment.json"
    marker.write_text("SYNTHETIC_PRESERVED_STATE")
    output = tmp_path / "new-output"
    with pytest.raises(FileExistsError):
        claim_paths(output, state)
    assert marker.read_text() == "SYNTHETIC_PRESERVED_STATE"
    assert not output.exists()


@pytest.mark.parametrize("phase,retained", [("OWNED", True), ("DROPPED", False), ("UNKNOWN", None)])
def test_review_failure_report_matches_actual_cleanup_phase(phase, retained):
    from scripts.verify_t16_a3 import failure_record

    result = failure_record({"schema_state": phase}, RuntimeError("SYNTHETIC"))
    assert result["schemas_retained"] is retained
