"""Bounded model-call observations, never prompts, authorization or billing proof."""

import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

VERSION = "V215_TOOL_SCHEMA_V1"
CURRENT = ContextVar("agentmall_model_receipt", default=None)
STAGES = {"MODEL_INVOKE", "SDK_REQUEST_BUILD", "SDK_RESPONSE_PARSE"}
USAGE_STATES = {"UNKNOWN", "INVALID", "OBSERVED_VALID"}


def digest(value):
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        return hashlib.sha256(raw).hexdigest() if len(raw) <= 1_048_576 else "UNKNOWN"
    except (TypeError, ValueError):
        return "UNKNOWN"


def usage_observation(raw, cap=2048):
    if not isinstance(raw, dict):
        return "UNKNOWN", None
    values = [raw.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if (
        any(type(v) is not int or v < 0 for v in values)
        or values[0] + values[1] != values[2]
        or values[0] > 1_048_576
        or values[1] > cap
    ):
        return "INVALID", None
    return "OBSERVED_VALID", dict(
        zip(("input_tokens", "output_tokens", "total_tokens"), values, strict=True)
    )


def safe_response_id(value):
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"chatcmpl-[A-Za-z0-9_-]{1,96}", value)
        and not re.search(r"(?i)sk-|eyJ|password|token|secret|api.?key", value)
        else "UNKNOWN"
    )


@dataclass
class ModelReceipt:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    schema_sha256: str = "UNKNOWN"
    response_sha256: str = "UNKNOWN"
    response_id: str = "UNKNOWN"
    usage_state: str = "UNKNOWN"
    usage: dict | None = None
    stage: str | None = None
    cap: int = 2048

    def summary(self):
        result = {
            "model_request_id": self.request_id,
            "tool_schema_version": VERSION,
            "tool_schema_sha256": self.schema_sha256,
            "response_body_sha256": self.response_sha256,
            "provider_response_id": self.response_id,
            "provider_usage_state": self.usage_state,
        }
        if self.usage is not None:
            result["observed_provider_usage"] = dict(self.usage)
        if self.stage:
            result["diagnostic_stage"] = self.stage
        return result


@contextmanager
def capture_model_diagnostics():
    receipt = ModelReceipt()
    token = CURRENT.set(receipt)
    try:
        yield receipt
    finally:
        CURRENT.reset(token)


def observe_request(payload):
    if receipt := CURRENT.get():
        receipt.schema_sha256 = digest(payload.get("tools", []))
        cap = payload.get("max_tokens", 2048)
        receipt.cap = cap if type(cap) is int and 0 < cap <= 2048 else 2048


def observe_response(body):
    if receipt := CURRENT.get():
        receipt.response_sha256 = digest(body)
        if isinstance(body, dict):
            receipt.response_id = safe_response_id(body.get("id"))
            receipt.usage_state, receipt.usage = usage_observation(body.get("usage"), receipt.cap)


def parsing_failed(stage):
    if receipt := CURRENT.get():
        receipt.stage = stage if stage in STAGES else "MODEL_INVOKE"


def public_model_diagnostics(data):
    """Explicit projection also protects injected fixture/model metadata."""
    if not isinstance(data, dict):
        return {}
    result = {}
    value = data.get("model_request_id")
    if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value):
        result["model_request_id"] = value
    for key in ("tool_schema_sha256", "response_body_sha256"):
        value = data.get(key)
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            result[key] = value
    if data.get("tool_schema_version") == VERSION:
        result["tool_schema_version"] = VERSION
    value = safe_response_id(data.get("provider_response_id"))
    if value != "UNKNOWN":
        result["provider_response_id"] = value
    if (
        isinstance(data.get("provider_usage_state"), str)
        and data["provider_usage_state"] in USAGE_STATES
    ):
        result["provider_usage_state"] = data["provider_usage_state"]
    if isinstance(data.get("output_budget_state"), str) and data["output_budget_state"] in {
        "RECONCILED",
        "UNRESOLVED",
    }:
        result["output_budget_state"] = data["output_budget_state"]
    if isinstance(data.get("diagnostic_stage"), str) and data["diagnostic_stage"] in STAGES:
        result["diagnostic_stage"] = data["diagnostic_stage"]
    usage = data.get("observed_provider_usage")
    if isinstance(usage, dict):
        raw = {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        state, checked = usage_observation(raw)
        if state == "OBSERVED_VALID" and data.get("provider_usage_state") == state:
            result["observed_provider_usage"] = checked
    return result
