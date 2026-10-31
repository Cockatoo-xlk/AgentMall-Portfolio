"""Paired evaluation CLI. Default is offline fixture execution on owned PostgreSQL schemas."""

import argparse
import asyncio
import hashlib
import json
import sys
from contextlib import AsyncExitStack, nullcontext
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import uuid4

from agentmall.agents.context import Constraints, MultiRequest, user_constraints

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.fixture_model import fixture_models
from evals.fixtures import ROOT, episode_database, initial_identity, offline_boundary
from evals.metrics import orchestration_metrics, paired_report, schedule_pairs
from evals.oracles import assess, read_snapshot
from evals.schema import load_tasks
from evals.simulator import ScriptError, UserSimulator, fault_hooks


async def _run_episode(
    task,
    architecture,
    repetition_id,
    *,
    mode="fixture",
    live_ledger=None,
    live_key=None,
    output=None,
):
    if mode not in {"fixture", "live"} or (
        mode == "live" and (live_ledger is None or not live_key)
    ):
        raise ValueError("Explicit validated Live ledger and key required")
    started = monotonic()
    output.update(
        {
            "task_id": task.task_id,
            "split": task.split,
            "category": task.category,
            "architecture": architecture,
            "repetition_id": repetition_id,
            "mode": mode,
            "evidence_class": "FIXTURE_EVALUATION",
            "paid_provider_requests": 0,
            "actual_bill_cny": "NOT_APPLICABLE",
            "cost_cny": "NOT_APPLICABLE",
            "annotation_source": task.annotation_source,
        }
    )
    # This guard covers setup, models and tool transports. It cannot be disabled by a task.
    with offline_boundary() if mode == "fixture" else nullcontext():
        async with AsyncExitStack() as stack:
            resources = await stack.enter_async_context(
                episode_database(
                    task, embedding="fixture" if mode == "fixture" else "local"
                )
            )
            env = resources["env"]
            output["cleanup"] = resources["cleanup"]
            output["initial"] = initial = read_snapshot(env)
            output["initial_hash"], output["initial_logical_state"] = initial_identity(
                initial, resources["refs"]
            )
            goal = task.user_goal.format(**resources["refs"])
            if mode == "fixture":
                single, multi = fixture_models(
                    task.fixture_program, goal, resources["refs"], task.fault.kind
                )
            else:
                import httpx

                from evals.provider import MeteredTransport, live_model

                episode_key = f"{task.task_id}:{repetition_id}:{architecture}"
                if any(
                    a["episode"] == episode_key for a in live_ledger.read()["attempts"]
                ):
                    raise ValueError(
                        "LIVE_EPISODE_ALREADY_ATTEMPTED_USE_ORIGINAL_EVIDENCE"
                    )
                client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        transport=MeteredTransport(live_ledger, episode_key),
                        timeout=30,
                        trust_env=False,
                    )
                )
                single = live_model(live_key, client)
                multi = {
                    role: live_model(live_key, client)
                    for role in ("supervisor", "shopping", "order", "aftersales")
                }
                output.update(
                    evidence_class="LIVE_LLM_EVALUATION", actual_bill_cny="UNKNOWN"
                )
            env[2].state.multi_models = multi
            env[2].state.durable_single_model = single
            simulator = UserSimulator(task, resources)
            response = await simulator.request(
                "POST", "/api/v1/agent/threads", json={"mode": architecture}
            )
            if response.status_code != 201:
                raise RuntimeError("THREAD_CREATE_FAILED")
            tid = response.json()["id"]
            rid = str(uuid4())
            # These are declared user choices, identical for both modes, not an answer key.
            constraints = {}
            quantities = {
                d.quantity
                for d in task.user_script.decisions
                if d.action_type == "CHECKOUT" and d.quantity is not None
            }
            if len(quantities) == 1 and "clarify" not in task.fixture_program:
                constraints["quantity"] = next(iter(quantities))
                # The API persists a complete Constraints DTO. Preserve the goal's
                # parsed intents when the deterministic user supplies a quantity.
                constraints = user_constraints(
                    MultiRequest(
                        request_id=rid,
                        thread_id=tid,
                        message=goal,
                        constraints=Constraints(**constraints),
                    )
                ).model_dump(mode="json")
            body = {
                "request_id": rid,
                "message": goal,
                **({"constraints": constraints} if constraints else {}),
            }
            injection = []
            run = None
            simulator_error = None
            with fault_hooks(task.fault.kind, injection):
                try:
                    async with asyncio.timeout(90):
                        response = await simulator.request(
                            "POST", f"/api/v1/agent/threads/{tid}/runs", json=body
                        )
                        if response.status_code not in (200, 201):
                            raise ScriptError("START_FAILED")
                        run = response.json()
                        if task.fault.kind == "start_reply_loss":
                            run = await simulator.reread(tid)
                            injection.append(
                                {
                                    "kind": "CLIENT_DISCARDED_ASGI_START_RESPONSE",
                                    "request_id": rid,
                                }
                            )
                        run = await simulator.continue_run(tid, run)
                        state_at_answer = read_snapshot(env)
                        output["agent_result_resources"] = {
                            name: state_at_answer[name]
                            for name in (
                                "orders",
                                "aftersales_cases",
                                "support_tickets",
                            )
                        }
                        await simulator.deterministic_actions(run)
                except ScriptError as exc:
                    simulator_error = str(exc)
                    run = await simulator.reread(tid)
                except TimeoutError:
                    simulator_error = "EPISODE_TIME_BUDGET_EXCEEDED"
                    run = await simulator.reread(tid)
            final = read_snapshot(env)
            tools = [
                event["payload_summary"].get("name")
                for event in final["run_events"]
                if event["event_type"] == "tool"
            ]
            output["resource_refs"] = resources["refs"]
            refs = resources["refs"] | {
                "run_status": run["status"],
                "observed_tools": tools,
                "agent_result_resources": output.get("agent_result_resources", final),
            }
            verdict = assess(task, initial, final, run["result"] or {}, refs)
            if simulator_error:
                verdict["success"] = False
                verdict["violations"].append(
                    {
                        "rule": simulator_error,
                        "label": "CONFIRMATION"
                        if "CONFIRMATION" in simulator_error
                        else "ORACLE_OR_FIXTURE",
                    }
                )
            budget = run.get("budget", {})
            if mode == "fixture":
                calls = (
                    single.call_records
                    if architecture == "single"
                    else [r for model in multi.values() for r in model.call_records]
                )
            else:
                calls = [
                    r
                    for r in live_ledger.read()["attempts"]
                    if r["episode"] == episode_key
                ]
                output["paid_provider_requests"] = len(calls)
                output["cost_cny"] = (
                    sum(float(r["held_cny"]) for r in calls)
                    if all(r["state"] == "SETTLED" for r in calls)
                    else "UNKNOWN"
                )
                output["reserved_upper_cost_cny"] = str(
                    sum(Decimal(r["held_cny"]) for r in calls)
                )
            usage = (
                "UNKNOWN"
                if len(calls) < budget.get("models", 0)
                or any(r["usage"] == "UNKNOWN" for r in calls)
                else {
                    key: sum(r["usage"][key] for r in calls)
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                }
            )
            output["orchestration"] = orchestration_metrics(final, task, architecture)
            output.update(
                success=verdict["success"],
                oracle=verdict,
                final=final,
                result=run["result"],
                thread_id=tid,
                run_id=run["id"],
                request_id=rid,
                run_status=run["status"],
                simulator_error=simulator_error,
                fault_evidence=injection,
                requests=simulator.ledger,
                confirmations=simulator.confirmations,
                clarifications=simulator.clarifications,
                recoveries=simulator.recoveries,
                machine_seconds=simulator.machine_seconds,
                user_wait_seconds=simulator.user_wait_seconds,
                model_calls=budget.get("models", 0),
                tool_calls=budget.get("tools", 0),
                delegations=budget.get("delegations", 0),
                input_tokens=usage["input_tokens"]
                if isinstance(usage, dict)
                else usage,
                output_tokens=usage["output_tokens"]
                if isinstance(usage, dict)
                else usage,
                token_evidence_class=(
                    "SIMULATED_FIXTURE" if mode == "fixture" else "PROVIDER_WIRE_USAGE"
                )
                if isinstance(usage, dict)
                else "UNKNOWN",
                provider_calls=calls,
                known_input_tokens=sum(
                    r["usage"]["input_tokens"]
                    for r in calls
                    if isinstance(r["usage"], dict)
                ),
                known_output_tokens=sum(
                    r["usage"]["output_tokens"]
                    for r in calls
                    if isinstance(r["usage"], dict)
                ),
                unknown_usage_calls=sum(r["usage"] == "UNKNOWN" for r in calls)
                + max(0, budget.get("models", 0) - len(calls)),
                business_steps_by_script=list(task.scripted_actions),
                unauthorized_action_count=verdict["unauthorized_action_count"],
                unsupported_claim_count=verdict["unsupported_claim_count"],
                subgoals_completed=verdict["subgoals_completed"],
                subgoals_total=verdict["subgoals_total"],
                graph_budget=budget,
                correct_refusal_clarification_applicable=(
                    task.category == "S1"
                    or "clarify" in task.fixture_program
                    or any(d.decision == "reject" for d in task.user_script.decisions)
                    or task.initial_state.catalog_variant == "no_stock"
                ),
                scope_limitations=task.capability_notes,
            )
    output["total_wall_seconds_including_fixture_setup"] = monotonic() - started
    return output


async def run_episode(task, architecture, repetition_id, **kwargs):
    output = {}
    try:
        return await _run_episode(
            task, architecture, repetition_id, output=output, **kwargs
        )
    except Exception as exc:  # noqa: BLE001 - retain failed Episodes without secrets
        # Every scheduled Episode remains in the denominator, including setup failures.
        # Do not stringify provider/SQL exceptions: they may contain private inputs.
        failure = {
            "rule": "EPISODE_HARNESS_FAILED",
            "label": "ORACLE_OR_FIXTURE",
            "exception_type": type(exc).__name__,
        }
        output.update(
            success=False,
            oracle={
                "success": False,
                "violations": [failure],
                "failure": {
                    "primary": "ORACLE_OR_FIXTURE",
                    "evidence": [failure],
                    "root_cause": "UNKNOWN",
                    "architecture_related": "UNKNOWN",
                },
            },
            machine_seconds=output.get("machine_seconds", "UNKNOWN"),
            input_tokens="UNKNOWN",
            output_tokens="UNKNOWN",
            model_calls="UNKNOWN",
            tool_calls="UNKNOWN",
            delegations="UNKNOWN",
            user_wait_seconds="UNKNOWN",
            run_status="FAILED",
            harness_failure=True,
        )
        if kwargs.get("mode") == "live":
            reconcile_live(
                output,
                kwargs.get("live_ledger"),
                task.task_id,
                repetition_id,
                architecture,
            )
        return output


def reconcile_live(output, ledger, task_id, repetition_id, architecture):
    output.update(
        evidence_class="LIVE_LLM_EVALUATION",
        actual_bill_cny="UNKNOWN",
        cost_cny="UNKNOWN",
        paid_provider_requests="UNKNOWN",
    )
    try:
        from decimal import Decimal

        calls = [
            r
            for r in ledger.read()["attempts"]
            if r["episode"] == f"{task_id}:{repetition_id}:{architecture}"
        ]
        output.update(
            provider_calls=calls,
            paid_provider_requests=len(calls),
            reserved_upper_cost_cny=str(
                sum((Decimal(r["held_cny"]) for r in calls), Decimal(0))
            ),
        )
        if all(r["state"] == "SETTLED" for r in calls):
            output["cost_cny"] = sum(float(r["held_cny"]) for r in calls)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        output["ledger_reconciliation"] = "UNKNOWN"


async def execute(args):
    from evals.manifest import FROZEN, claim_sealed, validate_manifest
    from evals.report import write_report

    selected_manifest = getattr(args, "manifest", None) or FROZEN
    manifest, manifest_hash = (
        validate_manifest(selected_manifest)
        if selected_manifest.exists()
        else (None, "UNFROZEN")
    )
    tasks = load_tasks(ROOT / f"evals/data/agent_{args.split}.jsonl")
    ledger, key = None, None
    if args.mode == "live":
        from agentmall.infra.llm import load_live_key

        from evals.experiments import open_ledger

        if not manifest or args.split != "dev" or not args.pilot or args.repeats != 1:
            raise ValueError(
                "FROZEN_DEV_PILOT_ONLY; formal Live requires a separately authorized frozen design"
            )
        ledger = open_ledger(manifest, manifest_hash, args)
        key = (
            load_live_key()
        )  # Only after every freeze/price/flag/budget boundary passes.
        tasks = [t for t in tasks if t.task_id in manifest["pilot"]["task_ids"]]
    elif args.confirm_live or args.pilot:
        raise ValueError("Live flags are invalid in fixture mode")
    if args.split == "test":
        if not manifest or args.repeats != 1:
            raise ValueError("FROZEN_SINGLE_SEALED_PASS_REQUIRED")
        claim_sealed(manifest_hash, args.run_id)
    destination = ROOT / "evals/results" / args.run_id
    destination.mkdir(parents=True, exist_ok=False)
    rows, initial_hashes = [], {}
    by_id = {t.task_id: t for t in tasks}
    schedule = [
        item | {"category": by_id[item["task_id"]].category}
        for item in schedule_pairs(list(by_id), args.repeats)
    ]
    (destination / "schedule.json").write_text(
        json.dumps(
            {
                "mode": args.mode,
                "manifest_sha256": manifest_hash,
                "dataset_sha256": hashlib.sha256(
                    (ROOT / f"evals/data/agent_{args.split}.jsonl").read_bytes()
                ).hexdigest(),
                "episodes": schedule,
            },
            indent=2,
        )
        + "\n"
    )
    for item in schedule:
        row = await run_episode(
            by_id[item["task_id"]],
            item["architecture"],
            item["repetition_id"],
            mode=args.mode,
            live_ledger=ledger,
            live_key=key,
        )
        row["manifest_sha256"] = manifest_hash
        pair = item["task_id"], item["repetition_id"]
        if pair in initial_hashes and initial_hashes[pair] != row.get("initial_hash"):
            row["success"] = False
            row["pairing_error"] = "INITIAL_STATE_MISMATCH"
            row["oracle"]["violations"].append(
                {"rule": "INITIAL_STATE_MISMATCH", "label": "ORACLE_OR_FIXTURE"}
            )
        initial_hashes[pair] = row.get("initial_hash")
        path = (
            destination
            / f"{item['task_id']}-{item['repetition_id']}-{item['architecture']}.json"
        )
        path.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n")
        rows.append(row)
        print(
            json.dumps(
                {
                    **item,
                    "success": row["success"],
                    "errors": row["oracle"]["violations"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    report = paired_report(rows)
    report["dataset_hash"] = hashlib.sha256(
        (ROOT / f"evals/data/agent_{args.split}.jsonl").read_bytes()
    ).hexdigest()
    report["manifest_sha256"] = manifest_hash
    (destination / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    write_report(destination, rows, report)
    return 0 if all(row["success"] for row in rows) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=1)
    parser.add_argument(
        "--architectures", choices=("single,multi",), default="single,multi"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Explicit amended freeze; original sealed manifest stays immutable",
    )
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--max-cost-cny")
    parser.add_argument("--max-wall-seconds", type=int)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        parser.error("Use a simple run label")
    return asyncio.run(execute(args))


if __name__ == "__main__":
    raise SystemExit(main())
