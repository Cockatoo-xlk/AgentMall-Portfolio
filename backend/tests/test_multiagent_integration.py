from uuid import uuid4

import pytest
from conftest import row
from multiagent_helpers import (
    ai,
    call,
    choose_purchase,
    final,
    install,
    make_models,
    payload,
    route,
    send,
)


def facts(env):
    return row(
        env[1],
        "SELECT (SELECT count(*) FROM action_proposals) proposals, "
        "(SELECT count(*) FROM orders) orders, (SELECT count(*) FROM confirmations) confirmations, "
        "(SELECT count(*) FROM refunds) refunds, (SELECT sum(reserved) FROM products) reserved",
    )


@pytest.mark.parametrize(
    "embedding", ["fixture", pytest.param("local", marks=pytest.mark.real_bge)]
)
async def test_shopping_to_order_proposal_with_actual_graph_and_domain(env, buyer, embedding):
    baseline = facts(env)

    def no_transaction(messages):
        assert env[2].state.engine.pool.checkedout() == 0
        return final("已付款成功")

    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), no_transaction],
        order=[choose_purchase],
    )
    trace = await install(env, models, embedding=embedding)
    result = await send(env, buyer)
    assert result["status"] == "proposal", result
    assert len(result["proposal_ids"]) == 1
    assert facts(env) == {
        "proposals": 1,
        "orders": 0,
        "confirmations": 0,
        "refunds": 0,
        "reserved": 0,
    }
    assert "已付款成功" not in result["answer"]
    proposal = (
        await env[0].get("/api/v1/proposals/" + result["proposal_ids"][0], headers=buyer)
    ).json()
    assert proposal["canonical_payload"]["total_cents"] <= 30000
    assert proposal["status"] == "PENDING"
    assert [x["payload"]["target"] for x in trace["events"] if x["kind"] == "handoff"] == [
        "shopping",
        "order",
    ]
    assert set(trace["graph_nodes"]) == {
        "__start__",
        "__end__",
        "supervisor",
        "shopping",
        "order",
        "aftersales",
        "merge",
        "finish",
    }
    assert len(models["aftersales"].seen) == 0
    assert all(m.type != "tool" for m in models["order"].seen[0])
    assert payload(models["order"].seen[0])["constraints"]["max_price_cents"] == 30000
    from multiagent_helpers import save_evidence

    save_evidence("shopping-" + embedding, env, trace, result, baseline_counts=baseline)


@pytest.mark.parametrize(
    "embedding", ["fixture", pytest.param("local", marks=pytest.mark.real_bge)]
)
async def test_cross_domain_return_and_replacement_preserve_identity(
    env, buyer, product, embedding
):
    from aftersales_helpers import delivered_order

    order = await delivered_order(env[0], buyer, product)
    baseline = facts(env)

    def inspect(messages):
        return ai(call("get_order", {"order_id": order["id"]}))

    def prepare_return(messages):
        return ai(
            call(
                "prepare_return",
                {
                    "order_id": order["id"],
                    "reason_code": "QUALITY_ISSUE",
                    "description": "按键出现质量问题",
                },
            )
        )

    models = make_models(
        supervisor=[
            route("order", "inspect_orders", "old"),
            route("aftersales", "prepare_return", "return", depends=["old"], read_only=False),
            route("shopping", "find_products", "replacement", depends=["old"]),
            route("order", "prepare_checkout", "new", depends=["replacement"], read_only=False),
            route("finish"),
        ],
        order=[inspect, final(), choose_purchase],
        aftersales=[
            ai(
                call(
                    "check_eligibility", {"order_id": order["id"], "reason_code": "QUALITY_ISSUE"}
                ),
                call("retrieve_policies", {"order_id": order["id"], "query": "质量问题退货期限"}),
            ),
            prepare_return,
        ],
        shopping=[ai(call("retrieve_products", {"query": "安静机械键盘"})), final()],
    )
    trace = await install(env, models, embedding=embedding)
    result = await send(
        env,
        buyer,
        message="之前买的键盘有质量问题，想退掉。再帮我推荐一款500元以内更安静的键盘，准备购买，送演示宿舍。",
    )
    assert result["status"] == "proposal", result
    assert len(result["proposal_ids"]) == 2
    assert facts(env)["orders"] == baseline["orders"]
    assert facts(env)["refunds"] == 0
    assert facts(env)["confirmations"] == baseline["confirmations"]
    refs = result["entity_refs"]
    assert any(
        r["kind"] == "order" and r["id"] == order["id"] and r["policy_version"] == "demo-v1"
        for r in refs
    )
    assert any(
        r["kind"] == "product" and r["id"] == product and r["relation"] == "original" for r in refs
    )
    handoffs = [e["payload"] for e in trace["events"] if e["kind"] == "handoff"]
    shopping = next(h for h in handoffs if h["target"] == "shopping")
    assert product in shopping["constraints"]["exclude_product_ids"]
    assert shopping["constraints"]["max_price_cents"] == 50000
    assert shopping["constraints"]["noise_preference"] == "quiet"
    assert all(r["kind"] == "product" for r in shopping["entity_refs"])
    proposals = [f["data"] for f in result["facts"] if f["kind"] == "proposal"]
    returned = next(p for p in proposals if p["action_type"] == "RETURN_REQUEST")
    purchase = next(p for p in proposals if p["action_type"] == "CHECKOUT")
    assert returned["snapshot"]["order_id"] == order["id"]
    assert purchase["snapshot"]["items"][0]["product_id"] != product
    assert all(
        c["policy_version"] == "demo-v1" and c["visibility"] == "public"
        for c in result["citations"]
    )
    assert result["budget"]["used"]["models"] == 12
    from multiagent_helpers import save_evidence

    save_evidence("return-replacement-" + embedding, env, trace, result, baseline_counts=baseline)


async def test_rejected_proposal_replay_does_not_call_model_or_execute(env, buyer):
    request_id = str(uuid4())
    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    first = await send(env, buyer, request_id=request_id)
    proposal = first["proposal_ids"][0]
    rejection = await env[0].post(
        f"/api/v1/proposals/{proposal}/confirmations", headers=buyer, json={"decision": "reject"}
    )
    assert rejection.status_code == 201
    before = {k: len(m.seen) for k, m in models.items()}
    replay = await send(env, buyer, request_id=request_id)
    assert {k: len(m.seen) for k, m in models.items()} == before
    assert replay["status"] == "blocked"
    assert "用户已拒绝" in replay["answer"]
    assert facts(env)["orders"] == 0 and facts(env)["reserved"] == 0


async def test_aftersales_proposal_survives_failed_recommendation(env, buyer, product):
    from aftersales_helpers import delivered_order

    order = await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "prepare_return", "return", read_only=False),
            route("shopping", "find_products", "shop"),
            route("finish"),
        ],
        aftersales=[
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": order["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "质量问题",
                    },
                )
            )
        ],
        shopping=[TimeoutError()],
    )
    await install(env, models)
    result = await send(
        env, buyer, message=f"订单 {order['id']} 质量问题，想退掉，再帮我推荐一款键盘"
    )
    assert result["status"] == "partial"
    assert len(result["proposal_ids"]) == 1
    assert "SPECIALIST_TIMEOUT" in result["error_codes"]
    assert row(env[1], "SELECT count(*) n FROM aftersales_cases")["n"] == 0
    assert row(env[1], "SELECT count(*) n FROM refunds")["n"] == 0


async def test_ineligible_return_does_not_block_independent_recommendation(env, buyer, product):
    from lifecycle_helpers import create_order

    order = await create_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "prepare_return", "return", read_only=False),
            route("shopping", "find_products", "shop"),
            route("finish"),
        ],
        aftersales=[
            ai(
                call("check_eligibility", {"order_id": order["id"], "reason_code": "QUALITY_ISSUE"})
            ),
            ai(
                call(
                    "prepare_return",
                    {
                        "order_id": order["id"],
                        "reason_code": "QUALITY_ISSUE",
                        "description": "故障",
                    },
                )
            ),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
    )
    await install(env, models)
    result = await send(
        env,
        buyer,
        message=f"订单 {order['id']} 键盘质量问题想退掉，再帮我推荐一款500元以内静音键盘",
    )
    assert result["status"] == "partial"
    assert "AFTERSALES_INELIGIBLE" in result["error_codes"]
    assert any(f["kind"] == "product" for f in result["facts"])
    assert result["proposal_ids"] == []


async def test_human_ticket_is_real_and_not_refund_authority(env, buyer, product):
    from aftersales_helpers import delivered_order

    order = await delivered_order(env[0], buyer, product)
    models = make_models(
        supervisor=[
            route("aftersales", "human_support", "human", read_only=False),
            route("finish"),
        ],
        aftersales=[
            ai(
                call(
                    "create_support_ticket",
                    {
                        "order_id": order["id"],
                        "reason": "POLICY_DISPUTE",
                        "summary": "需要人工核对",
                    },
                )
            )
        ],
    )
    await install(env, models)
    result = await send(env, buyer, message=f"订单 {order['id']} 联系人工处理售后争议")
    assert any(f["kind"] == "ticket" and f["data"]["status"] == "OPEN" for f in result["facts"])
    assert row(env[1], "SELECT count(*) n FROM support_tickets")["n"] == 1
    assert facts(env)["refunds"] == 0


async def test_committed_proposal_survives_lost_tool_reply(env, buyer, monkeypatch):
    from agentmall.agents.specialist_tools import SpecialistTools

    original = SpecialistTools._execute

    async def lose_reply(self, name, args):
        result = await original(self, name, args)
        if name == "prepare_checkout" and result["ok"]:
            # Simulate committed DB success followed by loss of all in-memory receipts.
            self.runtime.facts.clear()
            self.runtime.references.clear()
            self.observed.clear()
            self.records.clear()
            raise TimeoutError("synthetic lost reply")
        return result

    monkeypatch.setattr(SpecialistTools, "_execute", lose_reply)
    models = make_models(
        supervisor=[
            route("shopping", "find_products", "shop"),
            route("order", "prepare_checkout", "buy", depends=["shop"], read_only=False),
            route("finish"),
        ],
        shopping=[ai(call("retrieve_products", {"query": "静音键盘"})), final()],
        order=[choose_purchase],
    )
    await install(env, models)
    result = await send(env, buyer)
    assert result["status"] == "partial"
    assert "TOOL_FAILED" in result["error_codes"]
    assert len(result["proposal_ids"]) == 1
    assert facts(env)["proposals"] == 1 and facts(env)["orders"] == 0
    assert (
        next(f["data"]["status"] for f in result["facts"] if f["kind"] == "proposal") == "PENDING"
    )
