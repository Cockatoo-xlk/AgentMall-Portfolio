"""One explicit provider; no credentials are loaded at import or normal app startup."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

MODEL_ID = "deepseek-flash"
DOCUMENTED_REVISION = "DeepSeek-V4.1-Flash-1017"
PRICE_DATE = "2026-10-30"
MAX_OUTPUT = 2048
CONTEXT_BOUND = 1_048_576
# Official CNY peak prices / million tokens, all input treated as cache misses.
RESERVATION = Decimal(CONTEXT_BOUND * 2 + MAX_OUTPUT * 8) / 1_000_000


class AgentStopped(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class Budget:
    max_calls: int = 8
    max_cost: Decimal = Decimal("3")
    attempts: list = field(default_factory=list)
    persist: Callable | None = None

    def __post_init__(self):
        if not 1 <= self.max_calls <= 8 or not Decimal("0") < self.max_cost <= Decimal("3"):
            raise ValueError("T03 budget cannot exceed 8 requests / CNY 3")

    @property
    def held(self):
        return sum((Decimal(a["upper_cost_cny"]) for a in self.attempts), Decimal(0))

    def save(self):
        if self.persist:
            self.persist()

    def start(self):
        if len(self.attempts) >= self.max_calls or self.held + RESERVATION > self.max_cost:
            raise AgentStopped("BUDGET_EXHAUSTED")
        self.attempts.append(
            {
                "attempt": len(self.attempts) + 1,
                "usage": "UNKNOWN",
                "upper_cost_cny": str(RESERVATION),
                "state": "RESERVED",
            }
        )
        self.save()  # Must persist before any network send; failures stop execution.

    def finish(self, message):
        usage = message.usage_metadata
        if not usage:
            raise AgentStopped("USAGE_UNKNOWN")
        # SDK normalization can synthesize zero counts for missing provider fields.
        # Never release a reservation without the original, complete wire usage.
        raw = message.response_metadata.get("token_usage")
        if not isinstance(raw, dict):
            raise AgentStopped("USAGE_UNKNOWN")
        values = [raw.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
        normalized = [usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")]
        if any(type(v) is not int for v in normalized) or normalized != values:
            raise AgentStopped("USAGE_INVALID")
        if (
            any(type(v) is not int or v < 0 for v in values)
            or values[0] + values[1] != values[2]
            or values[0] > CONTEXT_BOUND
            or values[1] > MAX_OUTPUT
        ):
            raise AgentStopped("USAGE_INVALID")
        cost = Decimal(values[0] * 2 + values[1] * 8) / 1_000_000
        self.attempts[-1].update(
            usage=dict(zip(("input_tokens", "output_tokens", "total_tokens"), values, strict=True)),
            upper_cost_cny=str(cost),
            state="SETTLED",
            observed_response_model=message.response_metadata.get("model_name", "UNKNOWN"),
            system_fingerprint=message.response_metadata.get("system_fingerprint", "UNKNOWN"),
        )
        self.save()


def load_live_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise AgentStopped("KEY_UNAVAILABLE")
    return key


def deepseek_model(key, *, http_client=None, http_async_client=None):
    # Explicit key/base avoids SDK environment fallback and alternate endpoints.
    from langchain_deepseek import ChatDeepSeek

    return ChatDeepSeek(
        model=MODEL_ID,
        api_key=key,
        base_url="https://api.deepseek.com",
        max_tokens=MAX_OUTPUT,
        max_retries=0,
        timeout=30,
        streaming=False,
        extra_body={"thinking": {"type": "disabled"}},
        http_client=http_client,
        http_async_client=http_async_client,
    )
