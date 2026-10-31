"""Delivery launcher must not write to an unrelated API or accept provider config."""

import importlib.util
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location("release_demo", ROOT / "scripts/demo.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


async def test_demo_preparation_refuses_unrecognized_server_without_writes():
    requests = []

    def reply(request):
        requests.append(request.method)
        return httpx.Response(200, json={"ready": True, "fixture_mode": "unknown"})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(reply)
    ) as client:
        with pytest.raises(ValueError, match="Fixture"):
            await module().prepare_return(client)
    assert requests == ["GET"]


def test_demo_refuses_occupied_port_without_terminating_listener():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        with pytest.raises(OSError):
            module().require_free_ports([port])
        assert sock.fileno() >= 0


def test_demo_child_receives_filtered_overrides_without_provider_values(tmp_path):
    import json
    import os
    import sys
    from unittest.mock import patch

    from web_e2e_server import FilteredEnvironment

    environment = FilteredEnvironment({"DEEPSEEK_API_KEY": "synthetic-never-forwarded"})
    environment["AGENTMALL_API_TARGET"] = "http://127.0.0.1:8001"
    environment["VITE_AGENT_MODE"] = "fixture"
    output = tmp_path / "child.json"
    with output.open("wb") as stream, patch.object(os, "environ", environment):
        process = module().spawn(
            [
                sys.executable,
                "-c",
                (
                    "import os,json; print(json.dumps({"
                    "'target':os.getenv('AGENTMALL_API_TARGET'),"
                    "'mode':os.getenv('VITE_AGENT_MODE'),"
                    "'provider_present':'DEEPSEEK_API_KEY' in os.environ}))"
                ),
            ],
            cwd=ROOT,
            stream=stream,
        )
        assert process.wait(timeout=10) == 0
    assert json.loads(output.read_text()) == {
        "target": "http://127.0.0.1:8001",
        "mode": "fixture",
        "provider_present": False,
    }


def test_demo_port_probe_accepts_closed_owned_server_in_time_wait():
    import socket

    with socket.socket() as server, socket.socket() as client:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen()
        client.connect(("127.0.0.1", port))
        accepted, _ = server.accept()
        accepted.close()
        assert client.recv(1) == b""
    module().require_free_ports([port])
