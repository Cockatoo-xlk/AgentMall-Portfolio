"""CONTRACT_TEST_ONLY initialization; fixed BGE, synthetic FD, zero Agent episodes."""

import os

import pytest
from evals.smoke_runner import FdCredential, SmokeBatch
from evals.smoke_session import SmokeSession
from test_v217_live1_integration import SingleWire
from test_v217_live1_transport import price
from test_v217_smoke_contract import proposal


@pytest.mark.real_bge
async def test_fixed_bge_and_pg_ready_before_synthetic_fd_is_consumed(env, tmp_path):
    gate = SmokeBatch(tmp_path / "batch.json", proposal(), "e" * 64)
    gate.arm("contract-A")
    session = SmokeSession(gate, tmp_path / "owned")
    read, write = os.pipe()
    os.write(write, b"synthetic-fd-after-bge\n")
    os.close(write)

    class CheckedFd(FdCredential):
        def take(self):
            assert gate.read()["tasks"][-1]["state"] == "READY"
            encoder = session.app.state.retrieval_encoder
            assert encoder.revision == "7999e1d3359715c523056ef9478215996d62a620"
            assert encoder.dimension == 512
            return super().take()

    source = CheckedFd(read)
    try:
        await session.initialize(
            env[3].database_url.get_secret_value(),
            price(),
            transport_factory=SingleWire().transport,
            key_source=source,
        )
        assert source.used is True
        assert session.provider.ledger.read()["attempts"] == []
        assert gate.read()["tasks"][-1]["episode_started_at"] is None
    finally:
        await session.close()
        if not source.used:
            os.close(read)
