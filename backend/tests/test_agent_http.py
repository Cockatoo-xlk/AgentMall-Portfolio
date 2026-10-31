from uuid import uuid4

from evals.live_smoke import database_facts, http_server, purchase_http
from langchain_core.messages import AIMessage
from test_agent_tools import ai, call, checkout, install


async def test_real_http_fake_model_real_postgres_purchase(env):
    # Explicit Fake Model scenario; only the later live command can establish LLM evidence.
    from sqlalchemy import text

    with env[1].connect() as conn:
        product = str(
            conn.scalar(
                text(
                    "SELECT id FROM products WHERE category='keyboard' "
                    "AND price_cents<=30000 AND attributes->>'switch'='静音轴' ORDER BY id LIMIT 1"
                )
            )
        )
    trace = {}
    install(
        env,
        [
            ai(
                call(
                    "search_products",
                    {"category": "keyboard", "query": "静音", "max_price_cents": 30000},
                )
            ),
            ai(checkout(product)),
            AIMessage(content="等待人工确认"),
        ],
    )
    env[2].state.agent_trace_factory = lambda: trace
    evidence = {"request_id": str(uuid4())}
    async with http_server(env[2]) as client:
        await purchase_http(client, evidence, lambda: None)
    facts = database_facts(env[3], evidence)
    assert facts["order_count"] == 1 and facts["reserved"] == 1
    assert trace["model_final_received"] and len(trace["tools"]) == 2
    assert evidence["confirmation_actor"] == "synthetic_user_script_via_authenticated_T02_API"
