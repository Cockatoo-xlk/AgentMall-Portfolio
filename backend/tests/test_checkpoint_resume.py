from uuid import uuid4

import pytest
from sqlalchemy import text


@pytest.fixture
async def checkpoint_settings(env):
    schema = "cp_" + uuid4().hex
    with env[1].begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    settings = env[3].model_copy(update={"checkpoint_schema": schema})
    try:
        yield settings
    finally:
        with env[1].begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_checkpoint_roundtrip_after_connection_reopen(env, checkpoint_settings):
    from langgraph.checkpoint.base import empty_checkpoint

    from agentmall.agents.persistence import checkpoint_saver, setup_checkpoint

    await setup_checkpoint(checkpoint_settings)
    config = {"configurable": {"thread_id": str(uuid4()), "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {
        "state": {
            "goal": "合成需求",
            "completed": {"shop": {"status": "done"}},
            "budget": {"models": 3},
        }
    }
    checkpoint["channel_versions"] = {"state": "1"}
    async with checkpoint_saver(checkpoint_settings) as saver:
        saved = await saver.aput(
            config, checkpoint, {"source": "input", "step": 0, "parents": {}}, {"state": "1"}
        )
    async with checkpoint_saver(checkpoint_settings) as saver:
        loaded = await saver.aget_tuple(saved)
        assert loaded.checkpoint["channel_values"] == checkpoint["channel_values"]
        assert (
            await saver.aget_tuple(
                {"configurable": {"thread_id": str(uuid4()), "checkpoint_ns": ""}}
            )
            is None
        )
    with env[1].connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema=:s AND table_name='checkpoints'"
                ),
                {"s": env[3].db_schema},
            )
            == 0
        )


async def test_checkpoint_api_does_not_implicitly_setup(checkpoint_settings):
    from psycopg.errors import UndefinedTable

    from agentmall.agents.persistence import checkpoint_saver

    async with checkpoint_saver(checkpoint_settings) as saver:
        with pytest.raises(UndefinedTable):
            await saver.aget_tuple(
                {"configurable": {"thread_id": str(uuid4()), "checkpoint_ns": ""}}
            )


async def test_0006_upgrade_and_check_preserve_business_and_checkpoint_tables(
    env, checkpoint_settings, buyer, product
):
    from alembic import command
    from alembic.config import Config
    from conftest import ROOT
    from lifecycle_helpers import create_order

    from agentmall.agents.persistence import setup_checkpoint

    await create_order(env[0], buyer, product)
    await setup_checkpoint(checkpoint_settings)
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    with env[1].begin() as c:
        before = c.execute(text("SELECT to_jsonb(o) FROM orders o")).all()
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0005")
        command.upgrade(cfg, "head")
        command.check(cfg)
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        assert c.execute(text("SELECT to_jsonb(o) FROM orders o")).all() == before
        assert (
            c.scalar(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema=:s"),
                {"s": checkpoint_settings.checkpoint_schema},
            )
            == 4
        )
    print("ALEMBIC 0005 -> 0006 + check: preserved order snapshot; CP tables isolated")
