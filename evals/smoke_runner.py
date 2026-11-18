"""Three-task product-smoke gates. No key/environment reads or network at import.

This composes existing product APIs and Playground metering, not the L8 Host.
An Owner receipt is a local delegated-operation record, not production PKI.
Synthetic contract mode can never construct a native Provider transport.
"""

import asyncio
import hashlib
import json
import os
import re
import select
import stat
import time
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from agentmall.playground.environment import private_write

from evals.controlled_offline import Operator
from evals.product_smoke import validate_proposal


class SmokeStopped(ValueError):
    def __init__(self, code):
        self.code = (
            code
            if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,100}", code)
            else "SMOKE_ERROR_UNKNOWN"
        )
        super().__init__(self.code)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def execution_plan(proposal, task_ids=None):
    """Select an ordered subset; original task inputs and case semantics stay fixed."""
    original = [task["id"] for task in proposal["tasks"]]
    selected = original if task_ids is None else task_ids
    if (
        not isinstance(selected, (list, tuple))
        or not selected
        or any(not isinstance(task, str) for task in selected)
        or len(set(selected)) != len(selected)
        or list(selected) != [task for task in original if task in selected]
    ):
        raise SmokeStopped("TASK_SELECTION_INVALID")
    limit = min(
        Decimal(proposal["limits"]["batch_cost_cny"]), Decimal("2.50") * len(selected)
    )
    return list(selected), str(limit)


def static_admission(proposal):
    """Pure parser/goal compatibility for this fixed smoke, never an Agent episode.

    A positive result means executable semantics are possible, not that a model
    or business assertion has passed. Expected goals never enter Agent input.
    """
    from agentmall.agents.context import MultiRequest, user_constraints

    proposal = validate_proposal(proposal)
    projected, codes = [], []
    for task in proposal["tasks"]:
        request = MultiRequest(
            request_id=uuid4(), thread_id=uuid4(), message=task["user_request"]
        )
        constraints = user_constraints(request)
        projected.append(
            {
                "task_id": task["id"],
                "quantity": constraints.quantity,
                "max_price_cents": constraints.max_price_cents,
                "purchase_requested": constraints.purchase_requested,
                "return_requested": constraints.return_requested,
                "reason_code": constraints.reason_code,
            }
        )
    b, c = projected[1:]
    if b["quantity"] != 2 or not b["purchase_requested"]:
        codes.append("B_PURCHASE_INTENT_UNSUPPORTED")
    if b["max_price_cents"] is not None and b["max_price_cents"] < 39800:
        codes.append("B_TOTAL_PRICE_CONFLICT")
    if not c["return_requested"] or c["reason_code"] != "QUALITY_ISSUE":
        codes.append("C_RETURN_INTENT_UNSUPPORTED")
    return {
        "state": "BLOCKED" if codes else "STATIC_COMPATIBLE_NOT_AUTHORIZED",
        "codes": codes,
        "projection": projected,
        "agent_episodes": 0,
    }


def owner_receipt(path, binding):
    if path is None:
        raise SmokeStopped("OWNER_AUTHORIZATION_REQUIRED")
    path = Path(path)
    try:
        if (
            path.is_symlink()
            or path.stat().st_uid != os.getuid()
            or path.stat().st_mode & 0o077
        ):
            raise ValueError()
        data = json.loads(path.read_bytes())
        age = (
            datetime.now(UTC) - datetime.fromisoformat(data["approved_at"])
        ).total_seconds()
        validity = (
            datetime.fromisoformat(data["expires_at"])
            - datetime.fromisoformat(data["approved_at"])
        ).total_seconds()
        if (
            data["purpose"] != "V217_LIVE1_REAL_MODEL_SMOKE"
            or data["approved"] is not True
            or data["binding_sha256"] != binding
            or data["operator"] != "TEST_OPERATOR_CODEX"
            or data["key_scope"] != "ANONYMOUS_FD_AFTER_INITIALIZATION"
            or data["cleanup_scope"] != "VERIFIED_CURRENT_BATCH_SCHEMAS"
            or not 0 <= age < validity <= 86400
            or not isinstance(data["owner_reference"], str)
            or not 12 <= len(data["owner_reference"]) <= 200
            or "synthetic" in data["owner_reference"].lower()
        ):
            raise ValueError()
    except (OSError, KeyError, TypeError, ValueError):
        raise SmokeStopped("OWNER_AUTHORIZATION_REQUIRED") from None
    return data


class SmokeBatch:
    """One writer, exclusive task identities and full fee holds; reattachment is read-only.

    State is owned by the trusted local operator, not an untrusted Agent. No
    claim of cryptographic isolation from a malicious same-UID process is made.
    """

    def __init__(
        self,
        path,
        proposal,
        binding,
        *,
        clock=time.time,
        mode="CONTRACT_TEST_ONLY",
        approval=None,
        verify_source=None,
        task_ids=None,
    ):
        self.path, self.proposal = Path(path), validate_proposal(proposal)
        self.task_order, self.batch_cost_limit = execution_plan(self.proposal, task_ids)
        if mode not in {"CONTRACT_TEST_ONLY", "LIVE_DEEPSEEK"}:
            raise SmokeStopped("MODE_INVALID")
        self.approval = (
            owner_receipt(approval, binding) if mode == "LIVE_DEEPSEEK" else None
        )
        if mode == "LIVE_DEEPSEEK" and static_admission(self.proposal)["codes"]:
            raise SmokeStopped("FROZEN_TASK_CONTRACT_INCOMPATIBLE")
        if mode == "LIVE_DEEPSEEK" and not callable(verify_source):
            raise SmokeStopped("SOURCE_VERIFIER_REQUIRED")
        self.verify_source = verify_source
        self.binding, self.clock, self.mode = binding, clock, mode
        self.writer = False
        self.last_clock = clock()
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise SmokeStopped("PRIVATE_STATE_REQUIRED")
        if not self.path.parent.is_dir() or self.path.parent.stat().st_mode & 0o077:
            raise SmokeStopped("PRIVATE_STATE_REQUIRED")
        if mode == "LIVE_DEEPSEEK" and not self.path.exists():
            # The approved local receipt is single-use across paths/processes.
            marker = Path(str(approval) + ".consumed")
            try:
                fd = os.open(
                    marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                raise SmokeStopped("OWNER_AUTHORIZATION_ALREADY_USED") from None
            with os.fdopen(fd, "w") as stream:
                json.dump(
                    {"binding": binding, "state_path": str(self.path.resolve())}, stream
                )
                stream.flush()
                os.fsync(stream.fileno())
        data = {
            "binding": binding,
            "proposal_sha256": digest(self.proposal),
            "mode": mode,
            "task_order": self.task_order,
            "batch_cost_limit_cny": self.batch_cost_limit,
            "tasks": [],
            "stop_code": None,
            "task_fee_holds_cny": "0",
        }
        try:
            fd = os.open(
                self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            self.read()
        else:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self.writer = True

    def read(self):
        if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
            raise SmokeStopped("PRIVATE_STATE_REQUIRED")
        data = json.loads(self.path.read_bytes())
        if (
            data["binding"] != self.binding
            or data["proposal_sha256"] != digest(self.proposal)
            or data["mode"] != self.mode
            or data["task_order"] != self.task_order
            or data.get("batch_cost_limit_cny", self.batch_cost_limit)
            != self.batch_cost_limit
        ):
            raise SmokeStopped("EXECUTION_BINDING_MISMATCH")
        return data

    def write(self, data):
        if not self.writer:
            raise SmokeStopped("READ_ONLY_REATTACH")
        private_write(self.path, data)

    def stop(self, code):
        code = SmokeStopped(code).code
        data = self.read()
        if not data["stop_code"]:
            data["stop_code"] = code
            if data["tasks"]:
                data["tasks"][-1]["state"] = "STOPPED"
            self.write(data)

    def remaining(self):
        data = self.read()
        if not data["tasks"]:
            return 300.0
        row, now = data["tasks"][-1], self.clock()
        outer = 300 - (now - row["outer_started_at"])
        episode = (
            90 - (now - row["episode_started_at"])
            if row["episode_started_at"] and not row.get("episode_finished_at")
            else 300
        )
        return max(0, min(outer, episode))

    def check(self):
        data = self.read()
        if data["stop_code"]:
            raise SmokeStopped(data["stop_code"])
        if self.verify_source:
            try:
                self.verify_source()
            except Exception:  # noqa: BLE001 - fail closed and suppress private exception text
                self.stop("SOURCE_BINDING_MISMATCH")
                raise SmokeStopped("SOURCE_BINDING_MISMATCH") from None
        now = self.clock()
        if now < self.last_clock:
            self.stop("CLOCK_ROLLBACK")
            raise SmokeStopped("CLOCK_ROLLBACK")
        self.last_clock = now
        if self.mode == "LIVE_DEEPSEEK":
            stamp = datetime.now(UTC)
            if (
                not datetime.fromisoformat(self.approval["approved_at"])
                <= stamp
                < datetime.fromisoformat(self.approval["expires_at"])
            ):
                self.stop("OWNER_AUTHORIZATION_EXPIRED")
                raise SmokeStopped("OWNER_AUTHORIZATION_EXPIRED")
        if not data["tasks"]:
            return
        row = data["tasks"][-1]
        if row["state"] == "VERIFIED":
            return
        code = None
        if now - row["outer_started_at"] >= 300:
            code = "OUTER_EXPIRED"
        elif (
            row["episode_started_at"]
            and not row.get("episode_finished_at")
            and now - row["episode_started_at"] >= 90
        ):
            code = "EPISODE_EXPIRED"
        if code:
            self.stop(code)
            raise SmokeStopped(code)

    def arm(self, task_id):
        if not self.writer:
            raise SmokeStopped("READ_ONLY_REATTACH")
        self.check()
        data = self.read()
        index = len(data["tasks"])
        if index >= len(self.task_order) or task_id != data["task_order"][index]:
            raise SmokeStopped("TASK_ORDER")
        if index and data["tasks"][-1]["state"] != "VERIFIED":
            raise SmokeStopped("PRIOR_TASK_NOT_FINALIZED")
        held = Decimal(data["task_fee_holds_cny"]) + Decimal("2.50")
        if held > Decimal(self.batch_cost_limit):
            raise SmokeStopped("BATCH_COST_EXHAUSTED")
        row = {
            "task_id": task_id,
            "execution_id": str(uuid4()),
            "outer_started_at": self.clock(),
            "episode_started_at": None,
            "state": "INITIALIZING",
            "audit": [],
        }
        data["tasks"].append(row)
        data["task_fee_holds_cny"] = str(held)
        self.write(data)
        return deepcopy(row)

    def case_index(self):
        task_id = self.read()["tasks"][-1]["task_id"]
        return next(
            i for i, task in enumerate(self.proposal["tasks"]) if task["id"] == task_id
        )

    def current_task(self):
        return deepcopy(self.proposal["tasks"][self.case_index()])

    def initialized(self, environment_id, business, checkpoint):
        self.check()
        data = self.read()
        row = data["tasks"][-1]
        if (
            row["state"] != "INITIALIZING"
            or not business.startswith("test_")
            or not checkpoint.startswith("cp_")
        ):
            raise SmokeStopped("INITIALIZATION_IDENTITY_INVALID")
        UUID(environment_id)
        if any(
            previous.get("environment_id") == environment_id
            or previous.get("business_schema") == business
            or previous.get("checkpoint_schema") == checkpoint
            for previous in data["tasks"][:-1]
        ):
            raise SmokeStopped("ENVIRONMENT_REUSE_FORBIDDEN")
        row.update(
            environment_id=environment_id,
            business_schema=business,
            checkpoint_schema=checkpoint,
            state="READY",
        )
        self.write(data)

    def start_episode(self):
        self.check()
        data = self.read()
        row = data["tasks"][-1]
        if row["episode_started_at"] is not None:
            raise SmokeStopped("EPISODE_ALREADY_STARTED")
        if row["state"] != "READY":
            raise SmokeStopped("INITIALIZATION_REQUIRED")
        row.update(episode_started_at=self.clock(), state="RUNNING")
        self.write(data)

    def bind_actor(self, user_id, store_id):
        UUID(user_id)
        UUID(store_id)
        data = self.read()
        row = data["tasks"][-1]
        if "user_id" in row and (row["user_id"], row["store_id"]) != (
            user_id,
            store_id,
        ):
            raise SmokeStopped("ACTOR_BINDING_IMMUTABLE")
        row.update(user_id=user_id, store_id=store_id)
        self.write(data)

    def end_episode(self):
        self.check()
        data = self.read()
        row = data["tasks"][-1]
        if row["episode_started_at"] is None:
            raise SmokeStopped("EPISODE_NOT_STARTED")
        if not row.get("episode_finished_at"):
            row["episode_finished_at"] = self.clock()
            self.write(data)

    def bind_thread(self, thread_id):
        UUID(thread_id)
        data = self.read()
        row = data["tasks"][-1]
        if row.get("thread_id", thread_id) != thread_id:
            raise SmokeStopped("THREAD_BINDING_IMMUTABLE")
        row["thread_id"] = thread_id
        self.write(data)

    def bind_run(self, scope):
        data = self.read()
        row = data["tasks"][-1]
        if (
            row.get("user_id") != str(scope.user_id)
            or row.get("store_id") != str(scope.store_id)
            or row.get("thread_id") != str(scope.thread_id)
            or row.get("run_id", str(scope.run_id)) != str(scope.run_id)
            or not row["episode_started_at"]
        ):
            self.stop("MODEL_SCOPE_MISMATCH")
            raise SmokeStopped("MODEL_SCOPE_MISMATCH")
        if "run_id" not in row:
            row["run_id"] = str(scope.run_id)
            self.write(data)

    def audit(self, kind, **fields):
        data = self.read()
        data["tasks"][-1]["audit"].append({"kind": kind, "at": self.clock(), **fields})
        self.write(data)

    def verified(self, evidence_hash):
        self.check()
        data = self.read()
        data["tasks"][-1].update(state="VERIFIED", evidence_sha256=evidence_hash)
        self.write(data)


class FdCredential:
    """Deferred, once-only anonymous pipe input, never an env/argv/key-file loader."""

    def __init__(self, fd):
        self.fd, self.used = fd, False

    def take(self):
        if self.used:
            raise SmokeStopped("CREDENTIAL_ALREADY_USED")
        self.used = True
        raw = bytearray()
        try:
            if not stat.S_ISFIFO(os.fstat(self.fd).st_mode):
                raise SmokeStopped("ANONYMOUS_PIPE_REQUIRED")
            deadline = time.monotonic() + 3
            while len(raw) <= 8192:
                wait = deadline - time.monotonic()
                if wait <= 0 or not select.select([self.fd], [], [], wait)[0]:
                    raise SmokeStopped("CREDENTIAL_TIMEOUT")
                chunk = os.read(self.fd, 8193 - len(raw))
                if not chunk:
                    break
                raw.extend(chunk)
            value = raw.decode().strip()
            if not value or len(raw) > 8192 or any(c.isspace() for c in value):
                raise SmokeStopped("CREDENTIAL_INVALID")
            return value
        except (OSError, UnicodeError):
            raise SmokeStopped("CREDENTIAL_INVALID") from None
        finally:
            os.close(self.fd)
            raw[:] = b"\0" * len(raw)


def validate_price(price):
    try:
        age = (
            datetime.now(UTC) - datetime.fromisoformat(price["checked_at"])
        ).total_seconds()
        if (
            not 0 <= age <= 86400
            or price["source"]
            != "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
            or price["model"] != "deepseek-flash"
            or price["documented_revision"] != "DeepSeek-V4.1-Flash-1017"
            or Decimal(price["peak_input_cache_miss"]) != 2
            or Decimal(price["peak_output"]) != 8
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError, InvalidOperation):
        raise SmokeStopped("CURRENT_OFFICIAL_PEAK_PRICE_REQUIRED") from None


async def attach_smoke_models(
    app, gate, state_dir, price, transport_factory=None, *, key_source=None
):
    """Compose the existing SDK/ledger after initialization, with the stricter caps.

    No task answers, raw wire bodies or credential strings are persisted. A
    response error retains the existing ledger's full UNKNOWN reservation.
    """
    import httpx
    from agentmall.agents.budgets import RunStopped
    from agentmall.infra.llm import deepseek_model
    from agentmall.playground.app import Playground
    from agentmall.playground.context import current_scope
    from agentmall.playground.ledger import PlaygroundLedger
    from agentmall.playground.policy import PlaygroundPolicy, source_fingerprint
    from agentmall.playground.provider import Clients, DenySync, PlaygroundTransport

    gate.check()
    validate_price(price)
    row = gate.read()["tasks"][-1]
    if row["state"] not in {"READY", "RUNNING"}:
        raise SmokeStopped("INITIALIZATION_REQUIRED")
    contract = gate.mode == "CONTRACT_TEST_ONLY"
    if contract != (transport_factory is not None):
        raise SmokeStopped("MOCK_NATIVE_BOUNDARY_INVALID")
    if not contract and (gate.approval is None or key_source is None):
        raise SmokeStopped("OWNER_AUTHORIZATION_REQUIRED")
    policy = PlaygroundPolicy(
        enabled=True,
        evidence_mode="MOCK_TRANSPORT" if contract else "LIVE_DEEPSEEK",
        session_id=UUID(row["execution_id"]),
        environment_id=UUID(row["environment_id"]),
        source_sha256=source_fingerprint(),
        price_checked_at=datetime.fromisoformat(price["checked_at"]),
        max_model_calls=12,
        max_cost_cny=Decimal("2.50"),
        max_wall_seconds=300,
        max_input_tokens=3145728,
        max_output_tokens=12000,
    )
    ledger = PlaygroundLedger(Path(state_dir) / "ledger.json", policy)

    class ClockedTransport(PlaygroundTransport):
        async def handle_async_request(self, request):
            try:
                gate.check()
                validate_price(price)
                current = gate.read()["tasks"][-1]
                if current["state"] != "RUNNING" or current.get("episode_finished_at"):
                    raise SmokeStopped("MODEL_AFTER_EPISODE_FORBIDDEN")
                scope = current_scope.get()
                if scope is None:
                    raise SmokeStopped("RUN_SCOPE_REQUIRED")
                gate.bind_run(scope)
                async with asyncio.timeout(gate.remaining()):
                    response = await super().handle_async_request(request)
                gate.check()  # No expired response may reach the SDK or authorize a tool.
                return response
            except BaseException as exc:  # noqa: BLE001 - fail closed and suppress private exception text
                code = (
                    exc.code
                    if isinstance(exc, RunStopped)
                    else str(exc)
                    if isinstance(exc, SmokeStopped)
                    else "PROVIDER_OUTCOME_UNKNOWN"
                )
                gate.stop(code)
                raise RunStopped(code) from None

    clients, models = [], {}
    key = None
    try:
        key = (
            key_source.take()
            if key_source is not None
            else "synthetic-contract-not-live"
        )
        for role in ("supervisor", "shopping", "order", "aftersales", "single"):
            inner = (
                transport_factory(role)
                if contract
                else httpx.AsyncHTTPTransport(verify=True, retries=0, trust_env=False)
            )
            if contract and not isinstance(inner, httpx.MockTransport):
                raise SmokeStopped("MOCK_TRANSPORT_REQUIRED")
            asynchronous = httpx.AsyncClient(
                transport=ClockedTransport(ledger, role, inner),
                timeout=30,
                follow_redirects=False,
                trust_env=False,
            )
            synchronous = httpx.Client(
                transport=DenySync(), trust_env=False, follow_redirects=False
            )
            pair = Clients(asynchronous, synchronous)
            clients.append(pair)
            models[role] = deepseek_model(
                key, http_client=synchronous, http_async_client=asynchronous
            ).model_copy(update={"temperature": 0, "cache": False})
        gate.check()
    except BaseException:  # noqa: BLE001 - fail closed and suppress private exception text
        for pair in clients:
            await pair.close()
        raise SmokeStopped("MODEL_INITIALIZATION_FAILED") from None
    finally:
        key = None
    provider = Playground(ledger, clients)
    app.state.multi_models = {
        k: models[k] for k in ("supervisor", "shopping", "order", "aftersales")
    }
    app.state.durable_single_model = models["single"]
    app.state.playground = provider
    return provider


class SmokeOperator(Operator):
    """One explicit formal-API action per call, with no decision/resume/recovery loop."""

    def __init__(self, client, auth, gate, ledger):
        super().__init__(client, dict(auth))
        self.auth_binding = digest(auth)
        self.gate, self.ledger = gate, ledger
        self.inspections, self.responses, self.resume_requests = {}, {}, {}

    def check_actor(self):
        if digest(self.auth) != self.auth_binding:
            self.gate.stop("ACTOR_OR_STORE_REJECTED")
            raise SmokeStopped("ACTOR_OR_STORE_REJECTED")

    def preflight(self):
        self.gate.check()
        self.check_actor()
        try:
            data = self.ledger.read()
            code = data["halted"] or next(
                (
                    "PROVIDER_USAGE_UNKNOWN"
                    for r in data["attempts"]
                    if r["state"] != "SETTLED"
                ),
                None,
            )
        except Exception:  # noqa: BLE001 - fail closed and suppress private exception text
            code = "BUDGET_STATE_UNKNOWN"
        if code:
            code = SmokeStopped(code).code
            self.gate.stop(code)
            raise SmokeStopped(code)

    async def _request(self, method, path, payload=None):
        self.check_actor()
        if method == "GET":
            import httpx

            try:
                return await super()._request(method, path, payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403, 404}:
                    self.gate.stop("ACTOR_OR_STORE_REJECTED")
                    raise SmokeStopped("ACTOR_OR_STORE_REJECTED") from None
                self.gate.stop("EVIDENCE_READ_UNAVAILABLE")
                raise SmokeStopped("EVIDENCE_READ_UNAVAILABLE") from None
        self.preflight()
        key = digest([method, path, payload])
        if key in self.responses:
            return deepcopy(self.responses[key])
        current = self.gate.read()["tasks"][-1]
        if current["state"] not in {"READY", "RUNNING"} or current.get(
            "episode_finished_at"
        ):
            raise SmokeStopped("EXECUTION_NOT_ACTIVE")
        try:
            async with asyncio.timeout(self.gate.remaining()):
                response = await self.client.request(
                    method, path, headers=self.auth, json=payload
                )
            if response.status_code >= 500:
                self.gate.stop("BUSINESS_WRITE_UNKNOWN")
                raise SmokeStopped("BUSINESS_WRITE_UNKNOWN")
            if response.status_code in {401, 403, 404}:
                self.gate.stop("ACTOR_OR_STORE_REJECTED")
                raise SmokeStopped("ACTOR_OR_STORE_REJECTED")
            if response.is_error:
                self.gate.stop("FORMAL_API_REJECTED")
                raise SmokeStopped("FORMAL_API_REJECTED")
            result = response.json()
        except SmokeStopped:
            raise
        except BaseException:  # noqa: BLE001 - fail closed and suppress private exception text
            self.gate.stop("BUSINESS_WRITE_UNKNOWN")
            raise SmokeStopped("BUSINESS_WRITE_UNKNOWN") from None
        self.preflight()
        if isinstance(result, dict) and result.get("thread_id"):
            errors = (result.get("result") or {}).get("error_codes", [])
            ordinary = {
                "AFTERSALES_INELIGIBLE",
                "CONSTRAINT_MISMATCH",
                "INSUFFICIENT_STOCK",
                "PURCHASE_DETAILS_REQUIRED",
                "ORDER_SELECTION_REQUIRED",
                "RECOMMENDATION_SHORTAGE",
                "REPLACEMENT_SOURCE_REQUIRED",
                "UNSUPPORTED_POLICY",
                "HUMAN_HANDOFF_REQUIRED",
            }
            fatal = result.get("last_error") or next(
                (e for e in errors if e not in ordinary), None
            )
            if fatal:
                self.gate.stop(fatal)
                raise SmokeStopped(fatal)
        self.gate.check()
        if (
            isinstance(result, dict)
            and result.get("status") in {"COMPLETED", "PARTIAL", "FAILED"}
            and result.get("thread_id")
        ):
            self.gate.end_episode()
        self.responses[key] = deepcopy(result)
        return result

    async def inspect(self, thread_id, run_id):
        value = await super().inspect(thread_id, run_id)
        if value["run"]["thread_id"] != thread_id:
            self.gate.stop("RUN_THREAD_MISMATCH")
            raise SmokeStopped("RUN_THREAD_MISMATCH")
        proposal = value["proposal"]
        if proposal:
            self.inspections[proposal["proposal_id"]] = digest(value)
        return value

    async def decide(self, inspection, *, decision, operator):
        self.gate.check()
        if operator != "TEST_OPERATOR_CODEX":
            raise SmokeStopped("EXPLICIT_OPERATOR_REQUIRED")
        proposal = inspection["proposal"]
        if not proposal or proposal["action_type"] not in {
            "CHECKOUT",
            "RETURN_REQUEST",
        }:
            raise SmokeStopped("SMOKE_ACTION_FORBIDDEN")
        index = self.gate.case_index()
        actions = ([], ["CHECKOUT"], ["RETURN_REQUEST", "CHECKOUT"])[index]
        decisions = sum(
            a["kind"] == "operator_decision"
            for a in self.gate.read()["tasks"][-1]["audit"]
        )
        if decision == "approve" and (
            decisions >= len(actions) or proposal["action_type"] != actions[decisions]
        ):
            raise SmokeStopped("SMOKE_ACTION_SEQUENCE_INVALID")
        if self.inspections.get(proposal["proposal_id"]) != digest(inspection):
            raise SmokeStopped("INSPECT_PROPOSAL_FIRST")
        fresh = await super().inspect(
            inspection["run"]["thread_id"], inspection["run"]["id"]
        )
        if digest(fresh) != digest(inspection) or proposal["status"] != "PENDING":
            raise SmokeStopped("PROPOSAL_SNAPSHOT_CHANGED")
        result = await super().decide(inspection, decision=decision)
        if (
            result["proposal_id"] != proposal["proposal_id"]
            or result["decision"] != decision
        ):
            self.gate.stop("CONFIRMATION_IDENTITY_UNKNOWN")
            raise SmokeStopped("CONFIRMATION_IDENTITY_UNKNOWN")
        self.gate.audit(
            "operator_decision",
            operator=operator,
            proposal_id=proposal["proposal_id"],
            confirmation_id=result["confirmation_id"],
            decision=decision,
            snapshot_sha256=digest(inspection),
        )
        return result

    async def resume(self, thread_id, inspection, confirmation_id, request_id):
        self.preflight()
        payload_hash = digest(
            [
                thread_id,
                inspection["run"]["id"],
                inspection["run"].get("pending_confirmation"),
                confirmation_id,
            ]
        )
        if (
            request_id in self.resume_requests
            and self.resume_requests[request_id] != payload_hash
        ):
            raise SmokeStopped("IDEMPOTENCY_CONFLICT")
        key = digest(["resume", request_id, payload_hash])
        if key in self.responses:
            return deepcopy(self.responses[key])
        fresh = await super().inspect(thread_id, inspection["run"]["id"])
        old, new = (
            inspection["run"].get("pending_confirmation"),
            fresh["run"].get("pending_confirmation"),
        )
        confirmation = (fresh["proposal"] or {}).get("confirmation")
        if (
            old != new
            or not confirmation
            or confirmation["confirmation_id"] != confirmation_id
            or confirmation["consumed_at"] is not None
        ):
            raise SmokeStopped("CONFIRMATION_BINDING_INVALID")
        if not any(
            a.get("confirmation_id") == confirmation_id
            and a["kind"] == "operator_decision"
            for a in self.gate.read()["tasks"][-1]["audit"]
        ):
            raise SmokeStopped("EXPLICIT_OPERATOR_DECISION_REQUIRED")
        result = await super().resume(
            thread_id, inspection, confirmation_id, request_id
        )
        self.resume_requests[request_id] = payload_hash
        self.responses[key] = deepcopy(result)
        self.gate.audit(
            "explicit_resume", confirmation_id=confirmation_id, request_id=request_id
        )
        return result


def export_evidence(directory, evidence):
    """FREEZE -> EXPORT -> VERIFY. No SQL/resource deletion is reachable here."""
    directory = Path(directory)
    frozen = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode()
    value = hashlib.sha256(frozen).hexdigest()
    for name, payload in [
        ("frozen.json", frozen),
        ("seal.json", json.dumps({"sha256": value, "phase": "EXPORTED"}).encode()),
    ]:
        fd = os.open(
            directory / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    if hashlib.sha256((directory / "frozen.json").read_bytes()).hexdigest() != value:
        raise SmokeStopped("EVIDENCE_HASH_MISMATCH")
    private_write(directory / "verified.json", {"sha256": value, "phase": "VERIFIED"})
    return value


def load_verified(directory):
    directory = Path(directory)
    try:
        seal = json.loads((directory / "verified.json").read_bytes())
        raw = (directory / "frozen.json").read_bytes()
        if (
            seal["phase"] != "VERIFIED"
            or seal["sha256"] != hashlib.sha256(raw).hexdigest()
        ):
            raise ValueError()
        return json.loads(raw)
    except (OSError, KeyError, ValueError):
        raise SmokeStopped("VERIFIED_EVIDENCE_REQUIRED") from None
