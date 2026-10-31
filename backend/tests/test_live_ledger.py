import json
from decimal import Decimal
from uuid import uuid4

import pytest
from evals.live_smoke import resume_ledger
from test_llm import usage_message

from agentmall.infra.llm import MODEL_ID, PRICE_DATE, AgentStopped, Budget


def ledger():
    budget = Budget()
    for _ in range(3):
        budget.start()
        budget.finish(
            usage_message({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        )
        budget.attempts[-1]["observed_response_model"] = MODEL_ID
    return {
        "status": "LIVE_BLOCKED",
        "error_code": "NO_PURCHASE_PROPOSAL",
        "provider": "DeepSeek",
        "model_id": MODEL_ID,
        "price_checked_on": PRICE_DATE,
        "request_id": str(uuid4()),
        "schema": "test_" + uuid4().hex,
        "actual_http_requests": 3,
        "attempts": budget.attempts,
        "trace": {"model_final_received": True},
        "agent_response": {"status": "needs_input"},
    }


def test_resume_preserves_attempts_request_schema_and_prior_evidence(tmp_path):
    data = ledger()
    path = tmp_path / "purchase.json"
    path.write_text(json.dumps(data))
    evidence, budget = resume_ledger(path, 8, Decimal("3"))
    assert evidence["request_id"] == data["request_id"] and evidence["schema"] == data["schema"]
    assert budget.attempts == data["attempts"] and evidence["actual_http_requests"] == 3
    assert evidence["prior_passes"][0]["trace"] == data["trace"]
    assert evidence["trace"] == {}
    budget.start()
    assert budget.attempts[-1]["attempt"] == 4
    with pytest.raises(FileExistsError):
        resume_ledger(path, 8, Decimal("3"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "LIVE_LLM_VERIFIED"),
        ("actual_http_requests", 2),
        ("schema", "public"),
        ("model_id", "other-provider"),
        ("error_code", "PROVIDER_TIMEOUT"),
    ],
)
def test_resume_rejects_other_outcomes_or_scope(tmp_path, field, value):
    data = ledger()
    data[field] = value
    path = tmp_path / "purchase.json"
    path.write_text(json.dumps(data))
    with pytest.raises(AgentStopped):
        resume_ledger(path, 8, Decimal("3"))
    assert not path.with_suffix(".resume-started").exists()


def test_resume_rejects_unknown_usage_or_modified_cost(tmp_path):
    data = ledger()
    data["attempts"][0]["upper_cost_cny"] = "0"
    path = tmp_path / "purchase.json"
    path.write_text(json.dumps(data))
    with pytest.raises(AgentStopped):
        resume_ledger(path, 8, Decimal("3"))
