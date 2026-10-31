"""Explicit Live boundary and durable reserve-before-send ledger. No key reads at import."""

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import httpx
from agentmall.agents.specialist_tools import SCHEMAS

MODEL = "deepseek-flash"
CONTEXT_BOUND = 1_048_576
OUTPUT_BOUND = 2048
EPISODE_INPUT_BOUND = CONTEXT_BOUND * 12
REQUEST_BYTES_BOUND = 65536
PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


class ProviderBoundaryError(ValueError):
    pass


@dataclass(frozen=True)
class LivePolicy:
    confirm_live: bool
    max_model_calls: int
    max_cost_cny: str
    max_wall_seconds: int
    manifest_hash: str
    price_checked_at: str
    input_cny_per_million: str
    output_cny_per_million: str
    price_source: str

    def __post_init__(self):
        try:
            prices = [
                Decimal(x)
                for x in (
                    self.max_cost_cny,
                    self.input_cny_per_million,
                    self.output_cny_per_million,
                )
            ]
            age = (
                datetime.now(UTC) - datetime.fromisoformat(self.price_checked_at)
            ).total_seconds()
            valid = (
                self.confirm_live is True
                and type(self.max_model_calls) is int
                and 0 < self.max_model_calls <= 10000
                and type(self.max_wall_seconds) is int
                and 0 < self.max_wall_seconds <= 86400
                and all(p.is_finite() and p > 0 for p in prices)
                and 0 <= age <= 86400
                and self.price_source == PRICE_SOURCE
                and len(self.manifest_hash) == 64
            )
        except (InvalidOperation, TypeError, ValueError):
            valid = False
        if not valid:
            raise ProviderBoundaryError("LIVE_FLAGS_BUDGET_OR_CURRENT_PRICE_REQUIRED")


class BudgetLedger:
    """Fixed path per reviewed experiment; run labels never select a new budget."""

    def __init__(self, path: Path, policy: LivePolicy):
        self.path, self.policy = Path(path), policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.binding = hashlib.sha256(
            json.dumps(asdict(policy), sort_keys=True).encode()
        ).hexdigest()
        with self.locked():
            if self.path.exists():
                self._validate(self._read())
            else:
                self._write(
                    {
                        "version": 1,
                        "binding": self.binding,
                        "policy": asdict(policy),
                        "started_at": datetime.now(UTC).isoformat(),
                        "attempts": [],
                    }
                )

    @contextmanager
    def locked(self):
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self):
        return json.loads(self.path.read_text())

    def _validate(self, data):
        if data.get("binding") != self.binding or data.get("policy") != asdict(
            self.policy
        ):
            raise ProviderBoundaryError("LEDGER_BINDING_MISMATCH")
        rows = data["attempts"]
        if len({r["id"] for r in rows}) != len(rows) or any(
            not Decimal(r["held_cny"]).is_finite() or Decimal(r["held_cny"]) < 0
            for r in rows
        ):
            raise ProviderBoundaryError("LEDGER_INVALID")

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
            data = self._read()
            self._validate(data)
            return data

    def seconds_left(self):
        data = self.read()
        elapsed = (
            datetime.now(UTC) - datetime.fromisoformat(data["started_at"])
        ).total_seconds()
        return max(0, self.policy.max_wall_seconds - elapsed)

    def reserve(self, episode, output_cap):
        # A price can expire while the process is alive, before its wall cap.
        self.policy.__post_init__()
        if type(output_cap) is not int or not 0 < output_cap <= OUTPUT_BOUND:
            raise ProviderBoundaryError("OUTPUT_BOUND_REQUIRED")
        cost = (
            Decimal(CONTEXT_BOUND) * Decimal(self.policy.input_cny_per_million)
            + Decimal(output_cap) * Decimal(self.policy.output_cny_per_million)
        ) / 1_000_000
        with self.locked():
            data = self._read()
            self._validate(data)
            rows = data["attempts"]
            owned = [r for r in rows if r["episode"] == episode]
            elapsed = (
                datetime.now(UTC) - datetime.fromisoformat(data["started_at"])
            ).total_seconds()
            if (
                len(rows) >= self.policy.max_model_calls
                or sum(Decimal(r["held_cny"]) for r in rows) + cost
                > Decimal(self.policy.max_cost_cny)
                or elapsed >= self.policy.max_wall_seconds
                or len(owned) >= 12
                or sum(r["held_input_tokens"] for r in owned) + CONTEXT_BOUND
                > EPISODE_INPUT_BOUND
                or sum(r["held_output_tokens"] for r in owned) + output_cap > 12000
            ):
                raise ProviderBoundaryError("EXPERIMENT_BUDGET_EXHAUSTED")
            token = str(uuid4())
            rows.append(
                {
                    "id": token,
                    "client_request_id": token,
                    "episode": episode,
                    "state": "RESERVED",
                    "sent_at": datetime.now(UTC).isoformat(),
                    "usage": "UNKNOWN",
                    "held_cny": str(cost),
                    "held_input_tokens": CONTEXT_BOUND,
                    "held_output_tokens": output_cap,
                    "output_cap": output_cap,
                    "model": MODEL,
                }
            )
            self._write(data)
            return token

    def finish(self, token, response, *, http_status, provider_request_id="UNKNOWN"):
        with self.locked():
            data = self._read()
            self._validate(data)
            row = next(r for r in data["attempts"] if r["id"] == token)
            if row["state"] != "RESERVED":
                raise ProviderBoundaryError("ATTEMPT_ALREADY_FINISHED")
            row.update(
                state="UNKNOWN",
                http_status=http_status,
                provider_request_id=provider_request_id[:200],
                finished_at=datetime.now(UTC).isoformat(),
            )
            for key, name in (
                ("id", "response_id"),
                ("model", "response_model"),
                ("system_fingerprint", "system_fingerprint"),
            ):
                value = response.get(key)
                row[name] = value[:200] if isinstance(value, str) else "UNKNOWN"
            usage = response.get("usage")
            if isinstance(usage, dict):
                inp, out, total = (
                    usage.get(k)
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                )
                if (
                    all(type(v) is int and v >= 0 for v in (inp, out, total))
                    and inp <= CONTEXT_BOUND
                    and out <= row["output_cap"]
                    and inp + out == total
                ):
                    cost = (
                        Decimal(inp) * Decimal(self.policy.input_cny_per_million)
                        + Decimal(out) * Decimal(self.policy.output_cny_per_million)
                    ) / 1_000_000
                    row.update(
                        state="SETTLED",
                        usage={
                            "input_tokens": inp,
                            "output_tokens": out,
                            "total_tokens": total,
                        },
                        held_cny=str(cost),
                        held_input_tokens=inp,
                        held_output_tokens=out,
                    )
            self._write(data)


class MeteredTransport(httpx.AsyncBaseTransport):
    def __init__(self, ledger, episode, *, inner=None):
        self.ledger, self.episode = ledger, episode
        self.inner = (
            inner
            if inner is not None
            else httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        )

    async def handle_async_request(self, request):
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != "api.deepseek.com"
            or request.url.path != "/chat/completions"
            or request.url.query
        ):
            raise ProviderBoundaryError("PROVIDER_ENDPOINT_FORBIDDEN")
        body = json.loads(await request.aread())
        if (
            len(request.content) > REQUEST_BYTES_BOUND
            or body.get("model") != MODEL
            or body.get("thinking") != {"type": "disabled"}
            or body.get("stream", False)
            or body.get("temperature", 0) != 0
        ):
            raise ProviderBoundaryError("MODEL_OR_CONTEXT_BOUND_VIOLATION")
        for tool in body.get("tools", []):
            if tool.get("type") != "function" or tool.get("function", {}).get(
                "name"
            ) not in {*SCHEMAS, "route"}:
                raise ProviderBoundaryError("SERVER_OR_UNKNOWN_TOOL_FORBIDDEN")
        token = self.ledger.reserve(self.episode, body.get("max_tokens"))
        try:
            async with asyncio.timeout(min(30, self.ledger.seconds_left())):
                response = await self.inner.handle_async_request(request)
                await response.aread()
        except BaseException:
            self.ledger.finish(token, {}, http_status="TRANSPORT_ERROR")
            raise
        try:
            data = response.json()
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        self.ledger.finish(
            token,
            data,
            http_status=response.status_code,
            provider_request_id=response.headers.get("x-request-id", "UNKNOWN"),
        )
        return response

    async def aclose(self):
        await self.inner.aclose()


def live_model(key, client):
    from agentmall.infra.llm import deepseek_model

    return deepseek_model(key, http_async_client=client).model_copy(
        update={"temperature": 0}
    )
