"""Opt-in synthetic recovery evidence; never serialize prompts or credentials."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text


async def capture(env, tid, run, models, phase, exceptions):
    from agentmall.agents.durable_graph import build_durable_graph
    from agentmall.agents.persistence import checkpoint_config, checkpoint_saver

    with env[1].connect() as conn:
        row = (
            conn.execute(
                text("SELECT epoch,node_journal,budget FROM agent_runs WHERE id=:id"),
                {"id": run["id"]},
            )
            .mappings()
            .one()
        )
        events = list(
            conn.execute(
                text(
                    "SELECT seq,event_type,agent,payload_summary "
                    "FROM run_events WHERE run_id=:id ORDER BY seq"
                ),
                {"id": run["id"]},
            ).mappings()
        )
    async with checkpoint_saver(env[3]) as saver:
        graph = build_durable_graph(None, saver, None)
        state = await graph.aget_state(checkpoint_config(tid, run["id"]))

    def brief(output):
        runtime = output.get("runtime_state", {})
        return {
            "completed": {
                k: {"status": v["status"], "error_code": v.get("error_code")}
                for k, v in runtime.get("completed", {}).items()
            },
            "pending": sorted(runtime.get("pending", {})),
            "errors": runtime.get("errors", []),
            "output_keys": sorted(output),
        }

    result = {
        "phase": phase,
        "run_id": run["id"],
        "status": run["status"],
        "last_error": run["last_error"],
        "epoch": row["epoch"],
        "budget": row["budget"],
        "journal": {
            k: {"seq": v["seq"], **brief(v["output"])} for k, v in row["node_journal"].items()
        },
        "checkpoint": {
            **brief(state.values),
            "next": state.next,
            "tasks": [
                {"name": t.name, "error_type": type(t.error).__name__ if t.error else None}
                for t in state.tasks
            ],
            "id": state.config.get("configurable", {}).get("checkpoint_id"),
        },
        "model_calls": {k: len(m.seen) for k, m in models.items()},
        "events": [dict(e) for e in events],
        "exception_stages": list(exceptions),
    }
    await asyncio.to_thread(write, result, phase)
    result["digest"] = hashlib.sha256(
        json.dumps(result, default=str, sort_keys=True).encode()
    ).hexdigest()
    return result


def write(result, phase):
    destination = os.environ.get("AGENTMALL_R1_EVIDENCE_DIR")
    if destination:
        path = Path(destination).resolve()
        assert path.is_relative_to(Path(__file__).resolve().parents[2] / ".t13-r1")
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{phase}-{uuid4().hex}.json").write_text(
            json.dumps(result, default=str, indent=2) + "\n"
        )
