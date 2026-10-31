from contextlib import AsyncExitStack
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from agentmall.infra.config import Settings
from agentmall.main import create_app
from agentmall.seed import seed

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "AgentMall-demo-2026!"


def pytest_addoption(parser):
    parser.addoption(
        "--ci-offline-core",
        action="store_true",
        help="CI_OFFLINE_CORE: skip only tests requiring the project-local real BGE weights",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "real_bge: requires project-local real BGE model weights")


def pytest_report_header(config):
    return "CI_OFFLINE_CORE" if config.getoption("--ci-offline-core") else "LOCAL_FULL_WITH_BGE"


def pytest_collection_modifyitems(config, items):
    if config.getoption("--ci-offline-core"):
        skip_bge = pytest.mark.skip(
            reason="CI_OFFLINE_CORE: real BGE weights are not installed; use LOCAL_FULL_WITH_BGE"
        )
        for item in items:
            if item.get_closest_marker("real_bge"):
                item.add_marker(skip_bge)


def guard_test_database(url):
    parsed = make_url(url)
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.database != "agentmall_test"
        or parsed.username != "agentmall"
        or parsed.host not in {"localhost", "127.0.0.1"}
        or parsed.query
    ):
        raise ValueError("Tests require local agentmall / agentmall_test without URL options")
    return url


def migrate(connection):
    cfg = Config(str(ROOT / "backend/alembic.ini"))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


@pytest.fixture
async def env():
    base = Settings()
    if base.test_database_url is None:
        raise ValueError("AGENTMALL_TEST_DATABASE_URL is required")
    url = guard_test_database(base.test_database_url.get_secret_value())
    schema = "test_" + uuid4().hex
    settings = base.model_copy(update={"database_url": base.test_database_url, "db_schema": schema})
    # ExitStack unwinds engine -> schema -> admin even when setup or another cleanup fails.
    async with AsyncExitStack() as cleanup:
        admin = create_engine(url)
        cleanup.callback(admin.dispose)
        with admin.begin() as conn:
            assert conn.scalar(text("SELECT current_database()")) == "agentmall_test"
            assert conn.scalar(text("SELECT current_user")) == "agentmall"
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))

        def drop_owned_schema():
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

        cleanup.callback(drop_owned_schema)
        db = create_engine(url, connect_args={"options": f"-csearch_path={schema},extensions"})
        cleanup.callback(db.dispose)
        with db.begin() as conn:
            migrate(conn)
        app = create_app(settings)
        cleanup.push_async_callback(app.state.engine.dispose)
        async with app.state.sessions.begin() as session:
            await seed(session, settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, db, app, settings


@pytest.fixture
async def client(env):
    return env[0]


@pytest.fixture
async def buyer(client):
    response = await client.post(
        "/api/v1/auth/login", json={"login": "buyer1", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
async def buyer2(client):
    response = await client.post(
        "/api/v1/auth/login", json={"login": "buyer2", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
async def product(env):
    with env[1].connect() as conn:
        return str(conn.scalar(text("SELECT id FROM products WHERE active ORDER BY id LIMIT 1")))


def row(db, sql, **params):
    with db.connect() as conn:
        return conn.execute(text(sql), params).mappings().one()


@pytest.fixture(autouse=True)
def offline_provider_boundary(monkeypatch):
    """Default pytest cannot read provider keys or use a real HTTP transport."""
    import os
    import socket
    from collections.abc import MutableMapping

    import httpx
    import httpx2

    original_env = os.environ

    class OfflineEnvironment(MutableMapping):
        overrides = {}
        deleted = set()

        def __iter__(self):
            return iter(
                ({k for k in original_env if not self.hidden(k)} | set(self.overrides))
                - self.deleted
            )

        def __len__(self):
            return sum(1 for _ in self)

        @staticmethod
        def hidden(key):
            return any(s in key.upper() for s in ("DEEPSEEK", "OPENAI", "LANGSMITH", "LANGCHAIN"))

        def __setitem__(self, key, value):
            self.overrides[key] = value
            self.deleted.discard(key)

        def __delitem__(self, key):
            self.overrides.pop(key, None)
            self.deleted.add(key)

        def __getitem__(self, key):
            if key in self.deleted:
                raise KeyError(key)
            if key in self.overrides:
                return self.overrides[key]
            if self.hidden(key):
                raise KeyError(key)
            return original_env[key]

    monkeypatch.setattr(os, "environ", OfflineEnvironment())

    def denied(*args, **kwargs):
        raise AssertionError("Default pytest forbids external network/provider requests")

    for module in (httpx, httpx2):
        original_sync = module.HTTPTransport.handle_request
        original_async = module.AsyncHTTPTransport.handle_async_request

        def local_http(self, request, *, original=original_sync):
            if request.url.host not in {"127.0.0.1", "localhost", "::1"}:
                denied()
            return original(self, request)

        async def local_http_async(self, request, *, original=original_async):
            if request.url.host not in {"127.0.0.1", "localhost", "::1"}:
                denied()
            return await original(self, request)

        monkeypatch.setattr(module.HTTPTransport, "handle_request", local_http)
        monkeypatch.setattr(module.AsyncHTTPTransport, "handle_async_request", local_http_async)
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            denied()
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)
