"""Initialize ONLY a newly owned blank CI/demo database; never overwrite local config.

CI: AGENTMALL_CI_DB_PASSWORD=<synthetic> python scripts/ci/bootstrap.py --port 55433
Fresh Compose: run inside its isolated runner, also port 55433.
The caller owns database/container lifecycle. This script refuses existing user schemas.
"""

import argparse
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def database_url(port, password):
    if port != 55433:
        raise ValueError(
            "Fresh CI/demo requires internal port 55433; never historical host ports"
        )
    if not password:
        raise ValueError("Synthetic CI database password is required")
    return f"postgresql+psycopg://agentmall:{quote(password, safe='')}@127.0.0.1:{port}/agentmall_test"


def write_config(path, *, port, password):
    url = database_url(port, password)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        stream.write(
            f"AGENTMALL_DATABASE_URL={url}\nAGENTMALL_TEST_DATABASE_URL={url}\n"
            f"AGENTMALL_JWT_SECRET={secrets.token_hex(32)}\n"
        )


async def bootstrap(url):
    from agentmall.agents.persistence import setup_checkpoint
    from agentmall.infra.config import Settings
    from agentmall.infra.db import database
    from agentmall.seed import seed
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    admin = create_engine(url, poolclass=NullPool)
    schema, checkpoint = "test_" + uuid4().hex, "cp_" + uuid4().hex
    owned = []
    try:
        with admin.begin() as conn:
            existing = conn.scalars(
                text(
                    "SELECT nspname FROM pg_namespace WHERE nspname NOT IN "
                    "('public','extensions','information_schema') AND nspname !~ '^pg_'"
                )
            ).all()
            public_tables = conn.scalar(
                text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
            )
            if existing or public_tables:
                raise ValueError(
                    "Fresh bootstrap refuses existing business/checkpoint schemas or tables"
                )
            if conn.scalar(text("SELECT current_database()")) != "agentmall_test":
                raise ValueError("Dedicated database required")
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS extensions"))
            conn.execute(
                text(
                    "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions VERSION '0.8.7'"
                )
            )
            version, namespace = conn.execute(
                text(
                    "SELECT e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n "
                    "ON n.oid=e.extnamespace WHERE e.extname='vector'"
                )
            ).one()
            if (version, namespace) != ("0.8.7", "extensions"):
                raise ValueError(
                    "pgvector 0.8.7 in extensions is required; no relocation/upgrades"
                )
            for name in (schema, checkpoint):
                conn.execute(text(f'CREATE SCHEMA "{name}"'))
        owned.extend([schema, checkpoint])
        settings = Settings(
            database_url=url,
            test_database_url=url,
            jwt_secret=secrets.token_hex(32),
            db_schema=schema,
            checkpoint_schema=checkpoint,
        )
        engine, sessions = database(settings)
        try:
            cfg = Config(str(ROOT / "backend/alembic.ini"))

            def migrate(conn):
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
                command.check(cfg)

            async with engine.begin() as conn:
                await conn.run_sync(migrate)
            async with sessions.begin() as session:
                await seed(session, settings)
                first = [
                    int(await session.scalar(text(f"SELECT count(*) FROM {table}")))
                    for table in ("users", "products")
                ]
                await seed(session, settings)
                second = [
                    int(await session.scalar(text(f"SELECT count(*) FROM {table}")))
                    for table in ("users", "products")
                ]
            if first != second or first != [3, 12]:
                raise AssertionError(
                    "Repeat seed did not retain 3 synthetic users/12 products"
                )
            await setup_checkpoint(settings)
            async with engine.connect() as conn:
                revision = await conn.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                pg = await conn.scalar(text("SHOW server_version"))
            return {
                "mode": "FRESH_EMPTY_DATABASE_BOOTSTRAP",
                "postgres": pg,
                "pgvector": version,
                "revision": revision,
                "seed_before_after": [first, second],
                "schema": schema,
                "checkpoint_schema": checkpoint,
                "migration_check": "PASS",
            }
        finally:
            await engine.dispose()
    finally:
        try:
            with admin.begin() as conn:
                for name in reversed(owned):
                    conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        finally:
            admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, choices=(55433,), required=True)
    parser.add_argument("--config", type=Path, default=ROOT / ".env.rag")
    args = parser.parse_args()
    if args.config.exists() or args.config.is_symlink():
        raise FileExistsError(
            "Configuration already exists; refusing to overwrite or connect"
        )
    password = os.environ.get("AGENTMALL_CI_DB_PASSWORD")
    url = database_url(args.port, password)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from web_e2e_server import offline_boundary

    with offline_boundary():
        result = asyncio.run(bootstrap(url))
    write_config(args.config, port=args.port, password=password)
    print(
        json.dumps(result | {"owned_probe_schemas_cleaned": True, "paid_requests": 0})
    )


if __name__ == "__main__":
    main()
