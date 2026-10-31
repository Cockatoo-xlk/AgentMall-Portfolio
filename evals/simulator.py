"""Finite user/merchant scripts. No LLM can decide authorization here."""

from contextlib import contextmanager
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import text

from evals.fixtures import ROOT  # noqa: F401


class ScriptError(Exception):
    pass


@contextmanager
def fault_hooks(kind, evidence):
    from agentmall.agents import durable_graph, run_service

    with pytest.MonkeyPatch.context() as patch:
        if kind in {"before_execute", "after_commit"}:
            original = durable_graph.execute_confirmation

            async def execute(runtime, payload):
                if not evidence:
                    evidence.append(
                        {
                            "kind": kind,
                            "location": "deterministic_confirmation_node",
                            "action_id": payload["proposal_id"],
                        }
                    )
                    if kind == "before_execute":
                        raise RuntimeError("T12 controlled pre-execute failure")
                    await original(runtime, payload)
                    raise RuntimeError(
                        "T12 controlled commit-before-checkpoint failure"
                    )
                return await original(runtime, payload)

            patch.setattr(durable_graph, "execute_confirmation", execute)
        if kind == "final_answer":
            original_render = run_service.render

            def render(runtime, terminal):
                if not evidence and any(
                    kind == "proposal" and value.get("result")
                    for (kind, _), value in runtime.facts.items()
                ):
                    evidence.append(
                        {"kind": kind, "location": "after_checkpoint_before_run_result"}
                    )
                    raise RuntimeError("T12 controlled final rendering failure")
                return original_render(runtime, terminal)

            patch.setattr(run_service, "render", render)
        yield


class UserSimulator:
    def __init__(self, task, resources):
        self.task, self.resources = task, resources
        self.client, self.db, self.app, self.settings = resources["env"]
        self.auth = resources["auth"][task.actor]
        self.ledger = []
        self.clarifications = self.confirmations = self.recoveries = 0
        self.machine_seconds = self.user_wait_seconds = 0.0
        self.used_decisions = set()
        self.resumes = {}
        self.mutated = False

    async def request(self, method, path, *, headers=None, json=None, phase="agent"):
        started = monotonic()
        response = await self.client.request(
            method, path, headers=headers or self.auth, json=json
        )
        elapsed = monotonic() - started
        self.machine_seconds += elapsed
        self.ledger.append(
            {
                "method": method,
                "path": path,
                "status_code": response.status_code,
                "phase": phase,
                "duration_seconds": elapsed,
            }
        )
        return response

    async def reread(self, thread_id):
        response = await self.request(
            "GET", f"/api/v1/agent/threads/{thread_id}", phase="reconcile"
        )
        if response.status_code != 200 or not response.json()["runs"]:
            raise ScriptError("RUN_NOT_READABLE")
        return response.json()["runs"][0]

    async def recover(self, thread_id, run):
        self.recoveries += 1
        response = await self.request(
            "POST",
            f"/api/v1/agent/threads/{thread_id}/runs/{run['id']}/recover",
            json={"request_id": run["request_id"]},
            phase="recover",
        )
        if response.status_code != 200:
            raise ScriptError("RECOVER_FAILED")
        return response.json()

    def mutate_after_quote(self, proposal):
        if self.mutated or self.task.fault.kind not in {"price_change", "stock_loss"}:
            return
        if proposal["action_type"] != "CHECKOUT":
            return
        product = proposal["canonical_payload"]["items"][0]["product_id"]
        with self.db.begin() as connection:
            if self.task.fault.kind == "price_change":
                connection.execute(
                    text(
                        "UPDATE products SET price_cents=price_cents+100,catalog_version=catalog_version+1 WHERE id=:id"
                    ),
                    {"id": product},
                )
            else:
                connection.execute(
                    text("UPDATE products SET on_hand=reserved WHERE id=:id"),
                    {"id": product},
                )
        self.mutated = True

    async def continue_run(self, thread_id, run):
        for _ in range(6):
            if run["status"] == "RUNNING" or run.get("last_error") in {
                "EXECUTION_INTERRUPTED",
                "EXECUTION_TIMEOUT",
                "DATABASE_UNAVAILABLE",
            }:
                run = await self.recover(thread_id, run)
            pending = run.get("pending_confirmation")
            if not pending:
                return run
            wait_start = monotonic()
            wait_machine_start = self.machine_seconds
            if pending.get("type") == "clarification":
                script = self.task.user_script.clarifications
                if self.clarifications >= len(script):
                    raise ScriptError("UNEXPECTED_CLARIFICATION")
                payload = {
                    "run_id": run["id"],
                    "interrupt_id": pending["interrupt_id"],
                    "request_id": str(uuid4()),
                    "clarification": script[self.clarifications],
                }
                self.clarifications += 1
            else:
                pid = pending["proposal_id"]
                response = await self.request(
                    "GET", f"/api/v1/proposals/{pid}", phase="user_snapshot"
                )
                if response.status_code != 200:
                    raise ScriptError("PROPOSAL_NOT_READABLE")
                proposal = response.json()
                if pid in self.resumes:
                    payload = self.resumes[pid]
                    if payload["interrupt_id"] != pending["interrupt_id"]:
                        raise ScriptError("INTERRUPT_IDENTITY_CHANGED")
                else:
                    candidates = [
                        (i, d)
                        for i, d in enumerate(self.task.user_script.decisions)
                        if i not in self.used_decisions
                        and d.action_type == proposal["action_type"]
                    ]
                    if not candidates:
                        raise ScriptError("UNEXPECTED_CONFIRMATION")
                    index, decision = candidates[0]
                    if decision.decision == "wait":
                        return run
                    snapshot = proposal["canonical_payload"]
                    if (
                        decision.decision == "approve"
                        and decision.action_type == "CHECKOUT"
                    ):
                        if decision.quantity is not None and any(
                            i["quantity"] != decision.quantity
                            for i in snapshot["items"]
                        ):
                            raise ScriptError("USER_QUANTITY_MISMATCH")
                        if (
                            decision.max_total_cents is not None
                            and snapshot["total_cents"] > decision.max_total_cents
                        ):
                            raise ScriptError("USER_BUDGET_MISMATCH")
                    self.mutate_after_quote(proposal)
                    response = await self.request(
                        "POST",
                        f"/api/v1/proposals/{pid}/confirmations",
                        json={"decision": decision.decision},
                        phase="user_decision",
                    )
                    if response.status_code not in (200, 201):
                        raise ScriptError("CONFIRMATION_FAILED")
                    self.confirmations += 1
                    self.used_decisions.add(index)
                    payload = {
                        "run_id": run["id"],
                        "interrupt_id": pending["interrupt_id"],
                        "proposal_id": pid,
                        "confirmation_id": response.json()["confirmation_id"],
                        "request_id": str(uuid4()),
                    }
                    self.resumes[pid] = payload
            self.user_wait_seconds += max(
                0,
                monotonic() - wait_start - (self.machine_seconds - wait_machine_start),
            )
            response = await self.request(
                "POST", f"/api/v1/agent/threads/{thread_id}/resume", json=payload
            )
            if response.status_code == 500:
                run = await self.reread(thread_id)
                continue
            if response.status_code != 200:
                raise ScriptError("RESUME_FAILED")
            if self.task.fault.kind == "resume_reply_loss" and not self.mutated:
                self.mutated = True
                # Discard the observed HTTP body; read persistent state before any retry.
                run = await self.reread(thread_id)
                self.ledger.append(
                    {
                        "phase": "fault",
                        "kind": "CLIENT_DISCARDED_ASGI_RESPONSE",
                        "request_id": payload["request_id"],
                    }
                )
            else:
                run = response.json()
            if self.task.fault.kind == "resume_replay" and not self.mutated:
                self.mutated = True
                replay = await self.request(
                    "POST",
                    f"/api/v1/agent/threads/{thread_id}/resume",
                    json=payload,
                    phase="same_request_replay",
                )
                if replay.status_code != 200 or replay.json()["id"] != run["id"]:
                    raise ScriptError("REPLAY_IDENTITY_MISMATCH")
        raise ScriptError("USER_SCRIPT_LIMIT")

    async def deterministic_actions(self, run):
        from aftersales_helpers import (
            cancel_proposal,
            execute_cancel,
            execute_refund,
            receive_case,
            refund_proposal,
            review_case,
        )
        from checkout_helpers import confirm
        from lifecycle_helpers import execute_action, prepare_action

        refs, client = self.resources["refs"], self.client
        buyer, merchant = self.auth, self.resources["auth"]["merchant"]
        saved = {}
        for action in self.task.scripted_actions:
            oid = refs.get("original_order") or next(
                r["id"]
                for r in run["result"]["entity_refs"]
                if r["kind"] == "order" and r["relation"] == "purchase"
            )
            order = (
                await self.request(
                    "GET", f"/api/v1/orders/{oid}", phase="script_snapshot"
                )
            ).json()
            started = monotonic()
            machine_before_action = self.machine_seconds
            if action == "expire":
                from agentmall.maintenance import scan_once

                self.resources["clock"].advance(901)
                result = await scan_once(self.app.state.sessions)
            elif action in {"payment", "cancel"}:
                if order["status"] != "PENDING_PAYMENT":
                    response = await self.request(
                        "POST",
                        f"/api/v1/orders/{oid}/{action}-proposals",
                        headers={**buyer, "Idempotency-Key": str(uuid4())},
                        json={
                            "request_id": str(uuid4()),
                            "proposal_slot": action,
                            "expected_version": order["version"],
                        },
                        phase="scripted_business_rejection",
                    )
                    result = {
                        "http_status": response.status_code,
                        "error": response.json().get("code"),
                    }
                else:
                    proposal = await prepare_action(client, buyer, order, action)
                    confirmation = await confirm(client, buyer, proposal)
                    key = str(uuid4())
                    response = await execute_action(
                        client, buyer, order, proposal, confirmation, action, key
                    )
                    if response.status_code not in (200, 201):
                        raise ScriptError("SCRIPTED_ACTION_FAILED")
                    result = response.json()
                    saved[action] = (order, proposal, confirmation, key, result)
            elif action.startswith("replay_"):
                original = action.removeprefix("replay_")
                order, proposal, confirmation, key, previous = saved[original]
                response = await execute_action(
                    client, buyer, order, proposal, confirmation, original, key
                )
                if response.status_code != 200 or response.json() != previous:
                    raise ScriptError("SCRIPTED_REPLAY_MISMATCH")
                result = response.json()
            elif action in {"refund", "withdraw"}:
                cid = next(
                    r["id"] for r in run["result"]["entity_refs"] if r["kind"] == "case"
                )
                case = (
                    await self.request(
                        "GET", f"/api/v1/after-sales/{cid}", phase="script_snapshot"
                    )
                ).json()
                if action == "withdraw":
                    proposal = await cancel_proposal(client, buyer, case)
                    response = await execute_cancel(client, buyer, case, proposal)
                else:
                    reviewed = await review_case(client, merchant, case)
                    if reviewed.status_code != 200:
                        raise ScriptError("MERCHANT_REVIEW_FAILED")
                    received = await receive_case(client, merchant, reviewed.json())
                    if received.status_code != 200:
                        raise ScriptError("MERCHANT_RECEIVE_FAILED")
                    case = received.json()
                    proposal = await refund_proposal(client, merchant, case)
                    response = await execute_refund(client, merchant, case, proposal)
                if response.status_code not in (200, 201):
                    raise ScriptError("SCRIPTED_AFTERSALES_FAILED")
                result = response.json()
            elif action == "resolve_ticket":
                ident = next(
                    r["id"]
                    for r in run["result"]["entity_refs"]
                    if r["kind"] == "ticket"
                )
                ticket = (
                    await self.request(
                        "GET",
                        f"/api/v1/support-tickets/{ident}",
                        phase="script_snapshot",
                    )
                ).json()
                response = await self.request(
                    "POST",
                    f"/api/v1/merchant/tickets/{ident}/resolve",
                    headers=merchant,
                    json={
                        "expected_version": ticket["version"],
                        "resolution": "EXPLAINED",
                        "summary": "已解释规则，未批准任何退款",
                    },
                    phase="merchant_script",
                )
                if response.status_code != 200:
                    raise ScriptError("SCRIPTED_TICKET_FAILED")
                result = response.json()
            else:
                raise ScriptError("UNDECLARED_SCRIPTED_ACTION")
            self.machine_seconds = machine_before_action + monotonic() - started
            self.ledger.append(
                {
                    "phase": "deterministic_script",
                    "action": action,
                    "result": result,
                    "agent_autonomous": False,
                }
            )
