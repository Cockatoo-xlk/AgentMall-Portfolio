import conftest
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.parametrize("stage", ["migration", "app", "seed", "test"])
async def test_fixture_cleans_resources_after_exception(monkeypatch, stage):
    settings = conftest.Settings()
    url = conftest.guard_test_database(settings.test_database_url.get_secret_value())
    observer = create_engine(url)
    original_dispose = AsyncEngine.dispose
    disposed = []

    async def dispose(engine, *args, **kwargs):
        disposed.append(engine)
        await original_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(AsyncEngine, "dispose", dispose)
    original_migrate = conftest.migrate
    original_seed = conftest.seed
    original_app = conftest.create_app
    apps = []

    def migrate(conn):
        original_migrate(conn)
        if stage == "migration":
            raise RuntimeError("injected migration failure")

    def create_app(config):
        if stage == "app":
            raise RuntimeError("injected app failure")
        app = original_app(config)
        apps.append(app)
        return app

    async def seed(session, config):
        await original_seed(session, config)
        if stage == "seed":
            raise RuntimeError("injected seed failure")

    def schemas():
        with observer.connect() as conn:
            return set(
                conn.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'test_%'"))
            )

    monkeypatch.setattr(conftest, "migrate", migrate)
    monkeypatch.setattr(conftest, "create_app", create_app)
    monkeypatch.setattr(conftest, "seed", seed)
    before = schemas()
    generator = conftest.env.__wrapped__()
    try:
        with pytest.raises(RuntimeError, match="injected"):
            if stage == "test":
                await anext(generator)
                await generator.athrow(RuntimeError("injected test failure"))
            else:
                await anext(generator)
        assert schemas() == before
        assert all(app.state.engine in disposed for app in apps)
    finally:
        await generator.aclose()
        # Keep the negative run itself from leaking a pool if the fixture is still broken.
        for app in apps:
            await original_dispose(app.state.engine)
        observer.dispose()
