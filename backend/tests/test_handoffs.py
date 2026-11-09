from uuid import uuid4

import pytest
from multiagent_helpers import assessment_reads
from pydantic import ValidationError


def test_handoff_rejects_unknown_route_and_authority_fields():
    from agentmall.agents.context import TaskSpec

    for fields in (
        {"target": "refund_executor"},
        {"target": "shopping", "approved": True},
        {"target": "shopping", "actor_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(
                {
                    "subtask_id": "lookup",
                    "goal": "find_products",
                    "constraints": {},
                    "entity_refs": [],
                    "evidence_refs": [],
                    "depends_on": [],
                    **fields,
                }
            )


async def test_multiagent_endpoint_auth_and_disabled_default(client, buyer):
    body = {"request_id": str(uuid4()), "thread_id": str(uuid4()), "message": "找键盘"}
    assert (await client.post("/api/v1/agent/multi/messages", json=body)).status_code == 401
    response = await client.post("/api/v1/agent/multi/messages", json=body, headers=buyer)
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["error_codes"] == ["MODEL_DISABLED"]


async def test_explicit_owned_order_reaches_aftersales_without_raw_user_text(env, buyer, product):
    from aftersales_helpers import delivered_order
    from multiagent_helpers import (
        ai,
        call,
        final,
        install,
        make_models,
        payload,
        route,
        send,
    )

    order = await delivered_order(env[0], buyer, product)

    def inspect(messages):
        handoff = payload(messages)
        reference = next(r for r in handoff["entity_refs"] if r["kind"] == "order")
        assert reference["id"] == order["id"]
        assert reference["policy_version"] == "demo-v1"
        assert "private-sentinel" not in str(messages)
        return ai(
            call("check_eligibility", {"order_id": reference["id"], "reason_code": "QUALITY_ISSUE"})
        )

    models = make_models(
        supervisor=[route("aftersales", "assess_return"), route("finish")],
        aftersales=[inspect, final()],
    )
    await install(env, models)
    result = await send(
        env, buyer, message=f"订单 {order['id']} 有质量问题，检查售后资格。密码 private-sentinel"
    )
    assert result["error_codes"] == [], result
    assert any(f["kind"] == "eligibility" for f in result["facts"])


async def test_order_handoff_rejects_private_return_proposal(env, buyer, product):
    from aftersales_helpers import delivered_order
    from conftest import row
    from multiagent_helpers import ai, call, install, make_models, route, send

    order = await delivered_order(env[0], buyer, product)

    def copy_return(task):
        # Supervisor tries carrying a private return receipt into the purchasing context.
        task["entity_refs"] = [{"kind": "proposal", "id": proposal[0], "relation": "return"}]

    proposal = []

    def read_proposal(messages):
        from multiagent_helpers import payload

        proposal.append(
            next(r["id"] for r in payload(messages)["entity_refs"] if r["kind"] == "proposal")
        )
        return route("order", "prepare_checkout", "buy", read_only=False, change=copy_return)(
            messages
        )

    models = make_models(
        supervisor=[
            route("aftersales", "assess_return", "assessment"),
            route(
                "aftersales", "prepare_return", "return", depends=["assessment"], read_only=False
            ),
            read_proposal,
        ],
        aftersales=[
            *assessment_reads(order["id"]),
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": order["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "质量问题",
                    },
                )
            ),
        ],
    )
    await install(env, models)
    replacement = row(env[1], "SELECT id FROM products WHERE id != :id LIMIT 1", id=product)["id"]
    result = await send(
        env,
        buyer,
        message=f"订单 {order['id']} 质量问题想退掉，购买{replacement}，一件，送演示宿舍",
    )
    assert "CONTEXT_SCOPE_VIOLATION" in result["error_codes"]
    assert not models["order"].seen


@pytest.mark.parametrize(
    "bad_reference",
    [
        {"kind": "order", "id": "not-a-uuid"},
        {"kind": "order", "id": str(uuid4()), "approved": True},
    ],
)
def test_reference_schema_forbids_invalid_identity_or_authority(bad_reference):
    from agentmall.agents.context import TaskSpec

    with pytest.raises(ValidationError):
        TaskSpec(
            subtask_id="check",
            target="aftersales",
            goal="assess_return",
            constraints={},
            entity_refs=[bad_reference],
        )


async def test_order_policy_version_cannot_change_in_handoff(env, buyer, product):
    from aftersales_helpers import delivered_order
    from multiagent_helpers import install, make_models, route, send

    order = await delivered_order(env[0], buyer, product)

    def corrupt(task):
        for ref in task["entity_refs"]:
            if ref["kind"] == "order":
                ref["policy_version"] = "invented-version"

    models = make_models(supervisor=[route("aftersales", "assess_return", change=corrupt)])
    await install(env, models)
    result = await send(env, buyer, message=f"订单 {order['id']} 检查退货资格")
    assert "POLICY_VERSION_MISMATCH" in result["error_codes"]
    assert not models["aftersales"].seen


async def test_explicit_product_uuid_is_not_misclassified_as_order(env, buyer, product):
    from multiagent_helpers import ai, call, final, install, make_models, payload, route, send

    def lookup(messages):
        ref = next(r for r in payload(messages)["entity_refs"] if r["kind"] == "product")
        assert ref["id"] == product
        return ai(call("get_product", {"product_id": ref["id"]}))

    models = make_models(
        supervisor=[route("shopping", "find_products"), route("finish")], shopping=[lookup, final()]
    )
    await install(env, models)
    result = await send(env, buyer, message=f"查看商品 {product}")
    assert result["error_codes"] == [], result
    assert any(f["kind"] == "product" and f["id"] == product for f in result["facts"])
