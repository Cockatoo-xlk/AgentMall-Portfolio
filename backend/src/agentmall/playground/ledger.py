"""Private metadata only; durable global reservations, independent of graph/eval budgets."""

import fcntl
import hashlib
import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from agentmall.agents.budgets import RunStopped
from agentmall.playground.policy import INPUT_BOUND


def safe_id(value):
    import re

    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value)
        or value.lower().startswith(("sk-", "eyj", "bearer", "password"))
    ):
        return "UNKNOWN"
    return value


class PlaygroundLedger:
    def __init__(self, path, policy):
        policy.validate_current()
        self.path, self.policy = Path(path), policy
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError("UNSAFE_LEDGER_PATH")
        self.active = set()
        self.local_lock = threading.RLock()
        with self.locked():
            if self.path.exists():
                data = self._read()
                if any(r["state"] == "RESERVED" for r in data["attempts"]):
                    data["halted"] = data["halted"] or "PROVIDER_OUTCOME_UNKNOWN"
                    self._write(data)
            else:
                self._write(
                    {
                        "version": 1,
                        "binding": policy.binding,
                        "started_at": datetime.now(UTC).isoformat(),
                        "halted": None,
                        "attempts": [],
                    }
                )

    @contextmanager
    def locked(self):
        with self.local_lock:
            fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self):
        try:
            if (
                self.path.is_symlink()
                or stat.S_IMODE(self.path.stat().st_mode) & 0o077
                or self.path.stat().st_size > 1_000_000
            ):
                raise ValueError()
            data = json.loads(self.path.read_text())
            if data.get("binding") != self.policy.binding or data.get("version") != 1:
                raise RunStopped("LEDGER_BINDING_MISMATCH")
            started = datetime.fromisoformat(data["started_at"])
            if started.tzinfo is None or started > datetime.now(UTC):
                raise ValueError()
            rows = data["attempts"]
            if (
                not isinstance(rows, list)
                or len(rows) > self.policy.max_model_calls
                or len({r["slot"] for r in rows}) != len(rows)
                or len({r["id"] for r in rows}) != len(rows)
            ):
                raise ValueError()
            for r in rows:
                if (
                    r["state"] not in {"RESERVED", "SETTLED", "STOPPED"}
                    or type(r["output_cap"]) is not int
                    or not 0 < r["output_cap"] <= 2048
                ):
                    raise ValueError()
                cost = (
                    INPUT_BOUND * self.policy.input_cny_per_million
                    + r["output_cap"] * self.policy.output_cny_per_million
                ) / 1_000_000
                inp, output = INPUT_BOUND, r["output_cap"]
                if r["state"] == "SETTLED":
                    usage = r["usage"]
                    inp, output, total = [
                        usage[k] for k in ["input_tokens", "output_tokens", "total_tokens"]
                    ]
                    if (
                        any(type(v) is not int or v < 0 for v in [inp, output, total])
                        or inp + output != total
                        or inp > INPUT_BOUND
                        or output > r["output_cap"]
                        or r.get("error_code") is not None
                    ):
                        raise ValueError()
                    cost = (
                        inp * self.policy.input_cny_per_million
                        + output * self.policy.output_cny_per_million
                    ) / 1_000_000
                elif r["usage"] != "UNKNOWN":
                    raise ValueError()
                if (
                    r["held_input_tokens"] != inp
                    or r["held_output_tokens"] != output
                    or not Decimal(r["held_cny"]).is_finite()
                    or Decimal(r["held_cny"]) != cost
                ):
                    raise ValueError()
            if (
                sum(Decimal(r["held_cny"]) for r in rows) > self.policy.max_cost_cny
                or sum(r["held_input_tokens"] for r in rows) > self.policy.max_input_tokens
                or sum(r["held_output_tokens"] for r in rows) > self.policy.max_output_tokens
            ):
                raise ValueError()
            return data
        except RunStopped:
            raise
        except (ValueError, TypeError, KeyError, OSError):
            raise RunStopped("LEDGER_INVALID") from None

    def _write(self, data):
        fd, name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def read(self):
        with self.locked():
            return self._read()

    @property
    def seconds_left(self):
        data = self.read()
        return max(
            0,
            self.policy.max_wall_seconds
            - (datetime.now(UTC) - datetime.fromisoformat(data["started_at"])).total_seconds(),
        )

    def reserve(self, scope, role, node, ordinal, cap, request_hash):
        try:
            self.policy.validate_current()
        except ValueError as exc:
            raise RunStopped(str(exc)) from None
        slot = hashlib.sha256(f"{scope.run_id}:{node}:{role}:{ordinal}".encode()).hexdigest()
        cost = (
            INPUT_BOUND * self.policy.input_cny_per_million
            + cap * self.policy.output_cny_per_million
        ) / 1_000_000
        with self.locked():
            data = self._read()
            rows = data["attempts"]
            if data["halted"]:
                raise RunStopped(data["halted"])
            if any(r["state"] == "RESERVED" and r["id"] not in self.active for r in rows):
                data["halted"] = "PROVIDER_OUTCOME_UNKNOWN"
                self._write(data)
                raise RunStopped(data["halted"])
            if any(r["slot"] == slot for r in rows):
                raise RunStopped("MODEL_REPLAY_BLOCKED")
            elapsed = (
                datetime.now(UTC) - datetime.fromisoformat(data["started_at"])
            ).total_seconds()
            if (
                type(cap) is not int
                or not 0 < cap <= 2048
                or len(rows) >= self.policy.max_model_calls
                or sum(Decimal(r["held_cny"]) for r in rows) + cost > self.policy.max_cost_cny
                or sum(r["held_input_tokens"] for r in rows) + INPUT_BOUND
                > self.policy.max_input_tokens
                or sum(r["held_output_tokens"] for r in rows) + cap > self.policy.max_output_tokens
                or elapsed >= self.policy.max_wall_seconds
            ):
                raise RunStopped("PLAYGROUND_BUDGET_EXHAUSTED")
            token = str(uuid4())
            rows.append(
                {
                    "id": token,
                    "slot": slot,
                    "request_sha256": request_hash,
                    "run_id": str(scope.run_id),
                    "thread_id": str(scope.thread_id),
                    "user_id": str(scope.user_id),
                    "store_id": str(scope.store_id),
                    "role": role,
                    "state": "RESERVED",
                    "usage": "UNKNOWN",
                    "http_status": "UNKNOWN",
                    "provider_request_id": "UNKNOWN",
                    "response_id": "UNKNOWN",
                    "response_model": "UNKNOWN",
                    "held_cny": str(cost),
                    "held_input_tokens": INPUT_BOUND,
                    "held_output_tokens": cap,
                    "output_cap": cap,
                    "reserved_at": datetime.now(UTC).isoformat(),
                }
            )
            self._write(data)
            self.active.add(token)
            return token

    def finish(self, token, response, status, request_id, *, error=None):
        with self.locked():
            data = self._read()
            row = next(r for r in data["attempts"] if r["id"] == token)
            if row["state"] != "RESERVED":
                raise RunStopped("ATTEMPT_ALREADY_FINISHED")
            row.update(
                http_status=status,
                provider_request_id=safe_id(request_id),
                response_id=safe_id(response.get("id")),
                response_model=safe_id(response.get("model")),
                finished_at=datetime.now(UTC).isoformat(),
            )
            usage = response.get("usage")
            values = (
                [usage.get(k) for k in ["prompt_tokens", "completion_tokens", "total_tokens"]]
                if isinstance(usage, dict)
                else []
            )
            valid = (
                len(values) == 3
                and all(type(v) is int and v >= 0 for v in values)
                and values[0] + values[1] == values[2]
                and values[0] <= INPUT_BOUND
                and values[1] <= row["output_cap"]
            )
            error = error or (None if valid else "PROVIDER_USAGE_UNKNOWN")
            if valid and not error:
                row.update(
                    usage=dict(
                        zip(["input_tokens", "output_tokens", "total_tokens"], values, strict=True)
                    ),
                    held_cny=str(
                        (
                            values[0] * self.policy.input_cny_per_million
                            + values[1] * self.policy.output_cny_per_million
                        )
                        / 1_000_000
                    ),
                    held_input_tokens=values[0],
                    held_output_tokens=values[1],
                )
            row["state"] = "STOPPED" if error else "SETTLED"
            row["error_code"] = error
            if error:
                data["halted"] = error
            self._write(data)
            self.active.discard(token)
            return error

    def summary(self, user_id, store_id, run_id=None):
        data = self.read()
        rows = [
            r
            for r in data["attempts"]
            if r["user_id"] == str(user_id)
            and r["store_id"] == str(store_id)
            and (run_id is None or r["run_id"] == str(run_id))
        ]
        known = [r["usage"] for r in rows if isinstance(r["usage"], dict)]
        return {
            "mode": self.policy.evidence_mode,
            "model_id": self.policy.model_id,
            "session_id": str(self.policy.session_id),
            "requests_reserved": len(rows),
            "responses_observed": sum(type(r["http_status"]) is int for r in rows),
            "valid_responses": sum(r["state"] == "SETTLED" for r in rows),
            "unknown_usage_calls": sum(r["usage"] == "UNKNOWN" for r in rows),
            "usage_state": "UNKNOWN" if any(r["usage"] == "UNKNOWN" for r in rows) else "KNOWN",
            "usage": {
                k: sum(r[k] for r in known)
                for k in ["input_tokens", "output_tokens", "total_tokens"]
            },
            "estimated_upper_cost_cny": str(
                sum((Decimal(r["held_cny"]) for r in rows), Decimal(0))
            ),
            "actual_bill_cny": "UNKNOWN",
            "halted": data["halted"],
            "limits": {
                k: str(v) if isinstance(v, Decimal) else v
                for k, v in self.policy.model_dump().items()
                if k.startswith("max_")
            },
            "attempts": [
                {
                    k: r[k]
                    for k in [
                        "id",
                        "role",
                        "state",
                        "http_status",
                        "provider_request_id",
                        "response_id",
                        "response_model",
                        "usage",
                        "error_code",
                    ]
                    if k in r
                }
                for r in rows
            ],
        }
