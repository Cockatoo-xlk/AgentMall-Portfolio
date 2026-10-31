"""Delivery safety boundaries; no writes to the user's existing PostgreSQL."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location(
        "release_bootstrap", ROOT / "scripts/ci/bootstrap.py"
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_bootstrap_never_overwrites_existing_configuration(tmp_path):
    bootstrap = module()
    path = tmp_path / ".env.rag"
    path.write_text("original private configuration")
    with pytest.raises(FileExistsError):
        bootstrap.write_config(path, port=55433, password="synthetic-only")
    assert path.read_text() == "original private configuration"


@pytest.mark.parametrize("port", [5432, 55432, 55434, 65536])
def test_bootstrap_rejects_unowned_or_historical_ports(tmp_path, port):
    with pytest.raises(ValueError, match="55433"):
        module().write_config(tmp_path / ".env.rag", port=port, password="synthetic-only")
    assert not list(tmp_path.iterdir())


def test_bootstrap_config_is_local_private_and_contains_no_provider_key(tmp_path):
    path = tmp_path / ".env.rag"
    module().write_config(path, port=55433, password="synthetic-only")
    value = path.read_text()
    assert "127.0.0.1:55433/agentmall_test" in value
    assert "DEEPSEEK" not in value and "OPENAI" not in value
    assert path.stat().st_mode & 0o777 == 0o600
