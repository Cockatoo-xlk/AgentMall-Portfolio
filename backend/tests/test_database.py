import pytest
from conftest import guard_test_database, migrate, row
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from agentmall.seed import seed


async def test_migration_empty_schema_and_repeat_upgrade(env):
    _, db, _, _ = env
    assert set(inspect(db).get_table_names()) == {
        "alembic_version",
        "users",
        "products",
        "carts",
        "cart_items",
        "action_proposals",
        "confirmations",
        "idempotency_requests",
        "orders",
        "order_items",
        "business_events",
        "payments",
        "aftersales_cases",
        "refunds",
        "support_tickets",
        "knowledge_documents",
        "knowledge_chunks",
        "product_search",
        "agent_threads",
        "agent_thread_contexts",
        "agent_candidate_sets",
        "agent_context_mutations",
        "agent_runs",
        "run_events",
    }
    with db.begin() as conn:
        migrate(conn)
    assert row(db, "SELECT version_num FROM alembic_version")["version_num"] == "0009"
    assert row(db, "SELECT version() AS value")["value"].startswith("PostgreSQL")


async def test_seed_repeat_does_not_multiply_or_overwrite_existing_data(env):
    _, db, app, settings = env
    before = row(
        db,
        "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM products) AS products",
    )
    with db.begin() as conn:
        conn.execute(
            text(
                "UPDATE products SET price_cents=12345,on_hand=7 "
                "WHERE id=(SELECT id FROM products ORDER BY id LIMIT 1)"
            )
        )
        conn.execute(text("UPDATE users SET disabled=true WHERE login='buyer2'"))
    async with app.state.sessions.begin() as session:
        await seed(session, settings)
        await seed(session, settings)
    assert (
        row(
            db,
            "SELECT (SELECT count(*) FROM users) AS users, "
            "(SELECT count(*) FROM products) AS products",
        )
        == before
    )
    assert before["users"] == 3 and before["products"] >= 10
    assert row(db, "SELECT price_cents,on_hand FROM products ORDER BY id LIMIT 1") == {
        "price_cents": 12345,
        "on_hand": 7,
    }
    assert row(db, "SELECT disabled FROM users WHERE login='buyer2'")["disabled"] is True


@pytest.mark.parametrize(
    "assignment", ["on_hand=-1", "reserved=-1", "reserved=on_hand+1", "price_cents=-1"]
)
async def test_database_inventory_and_price_checks(env, product, assignment):
    with pytest.raises(IntegrityError), env[1].begin() as conn:
        conn.execute(text(f"UPDATE products SET {assignment} WHERE id=:id"), {"id": product})


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///agentmall_test",
        "postgresql+psycopg://agentmall:x@127.0.0.1/agentmall",
        "postgresql+psycopg://other:x@127.0.0.1/agentmall_test",
        "postgresql+psycopg://agentmall:x@remote/agentmall_test",
        "postgresql+psycopg://agentmall:x@127.0.0.1/agentmall_test?options=-csearch_path=public",
    ],
)
def test_test_database_guard_rejects_unsafe_targets(url):
    with pytest.raises(ValueError):
        guard_test_database(url)


async def test_upgrade_from_t01_preserves_seed_and_existing_cart(env, buyer, product):
    from alembic import command
    from alembic.config import Config
    from conftest import ROOT

    client, db, _, _ = env
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    with db.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0001")
    cart = (await client.get("/api/v1/cart", headers=buyer)).json()
    saved = await client.put(
        "/api/v1/cart/items/" + product,
        headers=buyer,
        json={"quantity": 2, "expected_version": cart["version"]},
    )
    before = row(db, "SELECT count(*) AS n FROM products")
    with db.begin() as connection:
        migrate(connection)
    assert (await client.get("/api/v1/cart", headers=buyer)).json() == saved.json()
    assert row(db, "SELECT count(*) AS n FROM products") == before
    assert row(db, "SELECT version_num FROM alembic_version")["version_num"] == "0009"


async def test_incomplete_idempotency_claim_cannot_commit(env):
    from uuid import uuid4

    db = env[1]
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO idempotency_requests(id,actor_id,store_id,operation,key,payload_hash)
            SELECT :id,id,:store,'execute_checkout','incomplete',:hash
            FROM users WHERE login='buyer1'
        """),
            {"id": uuid4(), "store": env[3].storefront_id, "hash": "a" * 64},
        )
    assert row(db, "SELECT count(*) AS n FROM idempotency_requests")["n"] == 0
