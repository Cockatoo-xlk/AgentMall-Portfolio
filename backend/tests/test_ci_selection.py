"""Exercise the real pytest mode boundary without PostgreSQL or model weights."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("ci_offline", [False, True], ids=["local-full", "ci-offline-core"])
def test_ci_mode_skips_only_real_bge_and_preserves_core_tests(tmp_path, ci_offline):
    # Copy the real plugin, so an overly broad skip or a changed default fails this test.
    (tmp_path / "conftest.py").write_text(Path(__file__).with_name("conftest.py").read_text())
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts = --strict-markers\nasyncio_default_fixture_loop_scope = function\n"
    )
    (tmp_path / "test_mode_contract.py").write_text(
        """
from pathlib import Path
import pytest

@pytest.mark.real_bge
def test_real_bge():
    Path(__file__).with_name('real-bge-executed').write_text('executed')

def test_postgres_transaction():
    pass

def test_checkpoint_recovery():
    pass

def test_safety_boundary():
    pass

def test_mock_provider_protocol():
    pass
"""
    )
    args = [sys.executable, "-m", "pytest", "-q", "-rs", "--confcutdir", str(tmp_path)]
    if ci_offline:
        args.append("--ci-offline-core")
    result = subprocess.run(
        args, cwd=tmp_path, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30
    )
    assert result.returncode == 0, result.stdout
    if ci_offline:
        assert "4 passed, 1 skipped" in result.stdout, result.stdout
        assert "CI_OFFLINE_CORE: real BGE weights are not installed" in result.stdout
        assert not (tmp_path / "real-bge-executed").exists()
    else:
        assert "5 passed" in result.stdout, result.stdout
        assert (tmp_path / "real-bge-executed").read_text() == "executed"
