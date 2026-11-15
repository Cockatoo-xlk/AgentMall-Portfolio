"""CONTRACT_TEST_ONLY: explanatory text cannot create eligibility or authorize writes."""

from uuid import uuid4

import pytest
from test_v215_recommendations import runtime_for

from agentmall.agents.graph import render


@pytest.mark.parametrize(
    "code,explanation",
    [
        ("ACTIVE_CASE_EXISTS", "已有进行中的售后申请"),
        ("OUTSIDE_RETURN_WINDOW", "超出当前政策的退货期限"),
        ("NOT_DELIVERED", "订单尚未处于已送达状态"),
        ("NOT_PAID", "缺少已支付记录"),
    ],
)
def test_eligibility_reasons_explain_verified_failure(code, explanation):
    r = runtime_for("查看本人订单的售后资格", [])
    r.facts[("eligibility", "contract-only")] = {"eligible": False, "reason_codes": [code]}
    result = render(r, "finish")
    assert explanation in result.answer
    assert code in result.answer
    assert not result.proposal_ids


def test_response_parse_error_keeps_committed_receipt_separate_from_failure():
    r = runtime_for("核对本人订单", [])
    r.errors = ["MODEL_RESPONSE_INVALID"]
    r.facts[("proposal", str(uuid4()))] = {
        "action_type": "RETURN_REQUEST",
        "status": "EXECUTED",
        "result": {"status": "REQUESTED"},
    }
    result = render(r, "finish")
    assert result.status == "partial"
    assert "响应解析失败" in result.answer
    assert "数据库回执状态：REQUESTED" in result.answer
    assert "EXECUTED" in result.answer
    assert "退款成功" not in result.answer
