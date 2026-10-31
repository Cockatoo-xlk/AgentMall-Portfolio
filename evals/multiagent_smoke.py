"""Offline T08 evidence runner; never creates a real network-backed model.

Run from the repository root after exporting the project's .env.rag settings.
The tests use owned schemas on port 55433, real StateGraph/create_agent and PostgreSQL.
Local embedding mode requires the previously verified cached model, never downloads it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / "evals/evidence/t08"
    destination.mkdir(parents=True, exist_ok=True)
    environment = {
        k: v
        for k, v in os.environ.items()
        if not any(
            word in k.upper()
            for word in ("DEEPSEEK", "OPENAI", "LANGSMITH", "LANGCHAIN")
        )
    }
    environment["AGENTMALL_T08_EVIDENCE_DIR"] = str(destination)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "backend/tests/test_multiagent_integration.py::test_shopping_to_order_proposal_with_actual_graph_and_domain",
        "backend/tests/test_multiagent_integration.py::test_cross_domain_return_and_replacement_preserve_identity",
        "backend/tests/test_multiagent_sdk.py",
        "-q",
    ]
    result = subprocess.run(
        command, check=False, cwd=ROOT, env=environment, capture_output=True, text=True
    )
    (destination / "smoke.txt").write_text(result.stdout + result.stderr)
    (destination / "smoke-command.json").write_text(
        json.dumps(
            {
                "command": command,
                "cwd": str(ROOT),
                "exit_code": result.returncode,
                "chat_transport": "SCRIPTED_FIXTURE / MockTransport",
                "paid_calls": 0,
                "embedding": ["fixture", "local cached BGE"],
                "live_multi_agent_verified": "NOT_RUN",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(result.stdout + result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
