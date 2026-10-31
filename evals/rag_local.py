"""Explicit isolated T07 index/serve entrypoint. Never selects the legacy demo database."""

import argparse
import asyncio

from agentmall.infra.config import Settings
from agentmall.main import create_app
from agentmall.retrieval.embedding import ROOT, LocalEncoder
from agentmall.retrieval.ingest import index_policies, index_products, load_policies
from agentmall.seed import seed
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def isolated_settings():
    base = Settings()
    if base.test_database_url is None:
        raise ValueError("AGENTMALL_TEST_DATABASE_URL required")
    url = make_url(base.test_database_url.get_secret_value())
    if (url.drivername, url.host, url.port, url.database, url.username) != (
        "postgresql+psycopg",
        "127.0.0.1",
        55433,
        "agentmall_test",
        "agentmall",
    ) or url.query:
        raise ValueError("Requires dedicated T07 database at 127.0.0.1:55433")
    return base.model_copy(
        update={"database_url": base.test_database_url, "db_schema": "public"}
    )


async def initialize(settings, encoder):
    app = create_app(settings)
    try:
        async with app.state.sessions.begin() as session:
            await seed(session, settings)
            products = await index_products(session, settings.storefront_id, encoder)
            chunks = await index_policies(session, load_policies(), encoder)
        print(
            f"Indexed {products} products and {chunks} policy chunks; existing source data preserved."
        )
    finally:
        await app.state.engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "serve"])
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    settings = isolated_settings()
    encoder = LocalEncoder()
    if args.command == "init":
        db = create_engine(
            settings.database_url.get_secret_value(),
            connect_args={"options": "-csearch_path=public,extensions"},
        )
        try:
            with db.begin() as c:
                cfg = Config(str(ROOT / "backend/alembic.ini"))
                cfg.attributes["connection"] = c
                command.upgrade(cfg, "head")
                command.check(cfg)
        finally:
            db.dispose()
        asyncio.run(initialize(settings, encoder))
    else:
        if args.port in {8000, 8001, 5173, 5174}:
            raise ValueError("Reserved demo/regression port")
        import uvicorn

        app = create_app(settings)
        app.state.retrieval_encoder = encoder
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
