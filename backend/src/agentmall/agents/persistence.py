"""Official PostgreSQL saver; schema setup is an explicit administrator operation."""

import os
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402


def connection_info(settings):
    url = make_url(settings.database_url.get_secret_value())
    if not settings.db_schema.startswith("test_"):
        raise ValueError("Durable agents require an isolated business schema")
    if (url.host, url.port, url.database, url.username) != (
        "127.0.0.1",
        55433,
        "agentmall_test",
        "agentmall",
    ):
        raise ValueError("Durable agents require isolated local 55433 agentmall_test")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def checkpoint_saver(settings, fence=None):
    if settings.checkpoint_schema is None:
        raise ValueError("Explicit checkpoint schema configuration required")
    async with await AsyncConnection.connect(
        connection_info(settings),
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=0,
        connect_timeout=3,
        options=f"-csearch_path={settings.checkpoint_schema} -cstatement_timeout=10000",
        application_name=f"agentmall:checkpoint:{settings.checkpoint_schema}",
    ) as connection:
        saver = AsyncPostgresSaver(
            connection,
            serde=JsonPlusSerializer(
                pickle_fallback=False, allowed_json_modules=None, allowed_msgpack_modules=None
            ),
        )
        if fence is not None:

            def fenced(method):
                async def write(*args, **kwargs):
                    # Keep a short Run SHARE lock until the checkpoint write finishes;
                    # a replacement epoch cannot race an old writer's checkpoint.
                    async with fence.sessions.begin() as session:
                        await fence.check(session)
                        return await method(*args, **kwargs)

                return write

            saver.aput = fenced(saver.aput)
            saver.aput_writes = fenced(saver.aput_writes)
        yield saver


async def setup_checkpoint(settings):
    """Explicit, repeatable setup in an already provisioned owned checkpoint schema."""
    async with checkpoint_saver(settings) as saver:
        current = await (await saver.conn.execute("SELECT current_schema() AS schema")).fetchone()
        if current["schema"] != settings.checkpoint_schema:
            raise ValueError("Provision the dedicated checkpoint schema explicitly first")
        await saver.setup()


def checkpoint_config(thread_id, run_id):
    return {
        "configurable": {"thread_id": f"{thread_id}:{run_id}", "checkpoint_ns": ""},
        "recursion_limit": 40,
        "callbacks": [],
    }


if __name__ == "__main__":
    import argparse
    import asyncio

    from psycopg import sql

    from agentmall.infra.config import Settings

    parser = argparse.ArgumentParser(
        description="Explicit setup for an isolated AgentMall checkpoint schema"
    )
    parser.add_argument("--create-schema", action="store_true")
    arguments = parser.parse_args()

    async def setup():
        settings = Settings()
        if settings.checkpoint_schema is None or settings.db_schema == "public":
            raise ValueError("Set an isolated test_ business schema and cp_ checkpoint schema")
        if arguments.create_schema:
            async with await AsyncConnection.connect(
                connection_info(settings), autocommit=True
            ) as connection:
                await connection.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        sql.Identifier(settings.checkpoint_schema)
                    )
                )
        await setup_checkpoint(settings)
        print("Checkpoint setup complete:", settings.checkpoint_schema)

    asyncio.run(setup())
