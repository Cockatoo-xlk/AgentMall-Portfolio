"""One run-wide ledger; all agents reserve against the same async lock."""

import asyncio
import time
from dataclasses import asdict, dataclass


class RunStopped(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Limits:
    models: int = 12
    tools: int = 16
    delegations: int = 4
    steps: int = 24
    output_tokens: int = 12000
    seconds: float = 90

    def __post_init__(self):
        maximum = {
            "models": 12,
            "tools": 16,
            "delegations": 4,
            "steps": 24,
            "output_tokens": 12000,
            "seconds": 90,
        }
        if any(isinstance(v, bool) or not 0 < v <= maximum[k] for k, v in asdict(self).items()):
            raise ValueError("Limits must be positive and cannot exceed the T08 envelope")


class GraphBudget:
    persists_rejections = False

    def __init__(self, limits=None):
        self.limits = limits or Limits()
        self.used = {k: 0 for k in asdict(self.limits) if k != "seconds"}
        self.started = time.monotonic()
        self.lock = asyncio.Lock()
        self.reservations = {}
        self.orchestration_repair = None

    async def claim_repair(self, error_code, *, fields=()):
        """One shared correction opportunity; the next model call is charged normally."""
        async with self.lock:
            if self.orchestration_repair is not None:
                return False
            self.orchestration_repair = error_code
            return True

    @property
    def seconds_left(self):
        return max(0, self.limits.seconds - (time.monotonic() - self.started))

    async def take(self, kind, count=1):
        async with self.lock:
            if self.seconds_left <= 0 or self.used[kind] + count > getattr(self.limits, kind):
                raise RunStopped("BUDGET_EXCEEDED")
            self.used[kind] += count

    async def start_model(self):
        async with self.lock:
            if self.seconds_left <= 0 or self.used["models"] >= self.limits.models:
                raise RunStopped("BUDGET_EXCEEDED")
            tokens = min(2048, self.limits.output_tokens - self.used["output_tokens"])
            if tokens <= 0:
                raise RunStopped("BUDGET_EXCEEDED")
            self.used["models"] += 1
            self.used["output_tokens"] += tokens
            token = self.used["models"]
            self.reservations[token] = tokens
            return token

    async def finish_model(self, token, message):
        async with self.lock:
            reserved = self.reservations.pop(token)
            usage = message.usage_metadata if message is not None else None
            if usage is None:
                return  # Keep the full reservation on failure/unknown usage.
            raw = message.response_metadata.get("token_usage")
            if raw is not None and type(raw.get("completion_tokens")) is not int:
                return  # SDK-synthesized zero is not evidence that no output tokens were used.
            output = usage.get("output_tokens")
            if type(output) is not int or not 0 <= output <= reserved:
                raise RunStopped("MODEL_USAGE_INVALID")
            self.used["output_tokens"] -= reserved - output

    def snapshot(self):
        return {
            "limits": asdict(self.limits),
            "used": dict(self.used),
            "remaining": {k: getattr(self.limits, k) - v for k, v in self.used.items()},
            "seconds_left": self.seconds_left,
        }
