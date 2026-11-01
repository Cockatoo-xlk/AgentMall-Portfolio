"""Explicit initialization and comment-bound ownership of fresh local schemas only."""

import json
import os
import secrets
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text

from agentmall.agents.persistence import connection_info, setup_checkpoint
from agentmall.infra.config import Settings
from agentmall.infra.db import database
from agentmall.playground.policy import ROOT, PlaygroundRejected
from agentmall.seed import seed


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise PlaygroundRejected("PRIVATE_PATH_REQUIRED")
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_environment(state_dir):
    path = Path(state_dir) / "environment.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED")
    try:
        data = json.loads(path.read_text())
        if data["state"] != "READY":
            raise ValueError()
        settings = Settings(_env_file=None, **data["settings"])
        ident = UUID(data["environment_id"])
        verify_owned(settings, ident)
        return settings, ident
    except (ValueError, KeyError, TypeError, OSError):
        raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED") from None


def verify_owned(settings, environment_id):
    if settings.db_schema == "public" or settings.checkpoint_schema is None:
        raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED")
    try:
        import psycopg

        marker = "agentmall-live-playground-v1:" + str(environment_id)
        with psycopg.connect(
            connection_info(settings), connect_timeout=3, options="-cstatement_timeout=3000"
        ) as conn:
            values = conn.execute(
                "SELECT obj_description(oid,'pg_namespace') FROM pg_namespace "
                "WHERE nspname = ANY(%s)",
                ([settings.db_schema, settings.checkpoint_schema],),
            ).fetchall()
            if len(values) != 2 or any(v[0] != marker for v in values):
                raise ValueError()
    except Exception:
        raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED") from None


async def initialize_environment(state_dir, database_url):
    state_dir = Path(state_dir)
    if (state_dir / "environment.json").exists():
        return load_environment(state_dir)
    ident = uuid4()
    business, checkpoint = "test_" + uuid4().hex, "cp_" + uuid4().hex
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        test_database_url=database_url,
        jwt_secret=secrets.token_urlsafe(48),
        db_schema=business,
        checkpoint_schema=checkpoint,
    )
    info = connection_info(settings)
    data = {
        "environment_id": str(ident),
        "state": "INITIALIZING",
        "settings": {
            "database_url": database_url,
            "test_database_url": database_url,
            "jwt_secret": settings.jwt_secret.get_secret_value(),
            "db_schema": business,
            "checkpoint_schema": checkpoint,
        },
    }
    private_write(state_dir / "environment.json", data)
    import psycopg

    marker = "agentmall-live-playground-v1:" + str(ident)
    with psycopg.connect(info, connect_timeout=3) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS extensions")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions VERSION '0.8.7'")
        vector = conn.execute(
            "SELECT e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n "
            "ON n.oid=e.extnamespace WHERE e.extname='vector'"
        ).fetchone()
        if vector != ("0.8.7", "extensions"):
            raise PlaygroundRejected("PGVECTOR_VERSION_REQUIRED")
        for schema in [business, checkpoint]:
            if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone():
                raise PlaygroundRejected("OWNED_ENVIRONMENT_REQUIRED")
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            conn.execute(
                sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                    sql.Identifier(schema), sql.Literal(marker)
                )
            )
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'SET search_path TO "{business}", extensions'))
            cfg = Config(str(ROOT / "backend/alembic.ini"))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    finally:
        engine.dispose()
    async_engine, sessions = database(settings)
    try:
        async with sessions.begin() as session:
            await seed(session, settings)
        await setup_checkpoint(settings)
    finally:
        await async_engine.dispose()
    data["state"] = "READY"
    private_write(state_dir / "environment.json", data)
    verify_owned(settings, ident)
    return settings, ident
