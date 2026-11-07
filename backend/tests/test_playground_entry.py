"""Entry/gate tests never load a real key or create a Live authorization."""

import json

import pytest


def test_describe_and_non_loopback_check_never_read_key_or_write_approval(
    monkeypatch, capsys, tmp_path
):
    from agentmall.playground.cli import main

    monkeypatch.setattr("agentmall.playground.app.load_live_key", lambda: pytest.fail("Key loaded"))
    assert main(["--describe"]) == 0
    assert json.loads(capsys.readouterr().out)["authorization"] == "NOT_GRANTED"
    assert main(["--host", "0.0.0.0", "--check", "--config", str(tmp_path / "missing")]) == 2
    assert "LOCALHOST_REQUIRED" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


async def test_owned_child_gets_filtered_explicit_environment(monkeypatch):
    import os
    from pathlib import Path

    from scripts.playground_proxy import serve_child

    monkeypatch.setenv("AGENTMALL_SYNTHETIC_CHILD_SETTING", "filtered-override")
    captured = {}

    class Child:
        returncode = 0

        async def wait(self):
            return 0

    class Proxy:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def spawn(*args, **kwargs):
        captured.update(kwargs)
        return Child()

    async def listen(*args):
        return Proxy()

    monkeypatch.setattr("scripts.playground_proxy.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setattr("scripts.playground_proxy.asyncio.start_server", listen)
    original = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: str(p) == "/.dockerenv" or original(p))
    assert await serve_child(["synthetic-command"], seconds=1) == 0
    assert captured["env"]["AGENTMALL_SYNTHETIC_CHILD_SETTING"] == "filtered-override"
    assert captured["env"] is not os.environ


def test_disabled_or_missing_policy_does_not_load_key(monkeypatch, tmp_path, capsys):
    from agentmall.playground.cli import main

    monkeypatch.setattr("agentmall.playground.app.load_live_key", lambda: pytest.fail("Key loaded"))
    assert main(["--check", "--config", str(tmp_path / "none")]) == 2
    assert "NO_GO" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_sdk_mock_cannot_be_labeled_live(tmp_path):
    import httpx
    from test_playground_budget import policy

    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.provider import metered_model

    live = policy().model_copy(update={"evidence_mode": "LIVE_DEEPSEEK"})
    ledger = PlaygroundLedger(tmp_path / "ledger.json", live)
    with pytest.raises(ValueError, match="Mock injection"):
        metered_model(
            ledger, "shopping", "synthetic", httpx.MockTransport(lambda r: httpx.Response(200))
        )


async def test_unmarked_existing_schema_cannot_be_borrowed_for_live(env):
    from uuid import uuid4

    from agentmall.playground.environment import verify_owned
    from agentmall.playground.policy import PlaygroundRejected

    with pytest.raises(PlaygroundRejected, match="OWNED_ENVIRONMENT"):
        verify_owned(env[3], uuid4())


def test_single_server_lease_cannot_be_shared_or_reset(tmp_path):
    from agentmall.playground.lease import ServerLease
    from agentmall.playground.policy import PlaygroundRejected

    lease = ServerLease(tmp_path)
    try:
        with pytest.raises(PlaygroundRejected, match="ALREADY_RUNNING"):
            ServerLease(tmp_path)
        assert (tmp_path / "server.lock").exists()
    finally:
        lease.close()
    replacement = ServerLease(tmp_path)
    replacement.close()


async def test_fresh_owned_environment_migrates_seeds_and_reopens_without_reset(env, tmp_path):
    from psycopg import sql
    from sqlalchemy import text

    from agentmall.agents.persistence import connection_info
    from agentmall.playground.environment import initialize_environment, load_environment

    settings = None
    try:
        settings, ident = await initialize_environment(
            tmp_path, env[3].test_database_url.get_secret_value()
        )
        import psycopg

        with psycopg.connect(connection_info(settings)) as conn:
            conn.execute(
                sql.SQL("SET search_path TO {}, extensions").format(
                    sql.Identifier(settings.db_schema)
                )
            )
            assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 12
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0009"
            conn.execute("UPDATE users SET disabled=true WHERE login='buyer2'")
        again, same = load_environment(tmp_path)
        assert again == settings and same == ident
        await initialize_environment(tmp_path, env[3].test_database_url.get_secret_value())
        with psycopg.connect(connection_info(settings)) as conn:
            assert (
                conn.execute(
                    sql.SQL("SELECT disabled FROM {}.users WHERE login='buyer2'").format(
                        sql.Identifier(settings.db_schema)
                    )
                ).fetchone()[0]
                is True
            )
    finally:
        if settings is not None:
            with env[1].begin() as conn:
                for schema in [settings.db_schema, settings.checkpoint_schema]:
                    conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_validated_admission_still_fails_before_key_without_real_bge(monkeypatch, tmp_path):
    from test_playground_budget import policy

    from agentmall.infra.config import Settings
    from agentmall.playground.app import create_live_app
    from agentmall.playground.policy import PlaygroundRejected

    monkeypatch.setattr("agentmall.playground.app.validate_approval", lambda *a: None)
    monkeypatch.setattr("agentmall.agents.persistence.connection_info", lambda *a: "synthetic")
    monkeypatch.setattr("agentmall.playground.environment.verify_owned", lambda *a: None)

    def no_encoder():
        raise ValueError("no local BGE")

    monkeypatch.setattr("agentmall.retrieval.embedding.LocalEncoder", no_encoder)
    monkeypatch.setattr("agentmall.playground.app.load_live_key", lambda: pytest.fail("Key read"))
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://agentmall:synthetic@127.0.0.1:55433/agentmall_test",
        jwt_secret="synthetic-test-jwt-not-live-32-characters",
        db_schema="test_" + "a" * 32,
        checkpoint_schema="cp_" + "a" * 32,
    )
    with pytest.raises(PlaygroundRejected, match="LOCAL_BGE_REQUIRED"):
        create_live_app(
            policy(), approval_path=tmp_path / "absent", state_dir=tmp_path, settings=settings
        )
    assert list(tmp_path.iterdir()) == []
