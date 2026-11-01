"""Real ChatDeepSeek SDK, strict wire boundary, no hidden retries or raw trace persistence."""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from agentmall.agents.budgets import RunStopped
from agentmall.agents.context import IntentPlan
from agentmall.agents.durable_budget import node_key
from agentmall.agents.single_agent import unique_object
from agentmall.agents.specialist_tools import SCHEMAS, WRITES
from agentmall.infra.llm import deepseek_model
from agentmall.playground.context import current_scope
from agentmall.playground.ledger import safe_id
from agentmall.playground.policy import MODEL, MODEL_REVISION


class DenySync(httpx.BaseTransport):
    def handle_request(self, request):
        raise RunStopped("SYNC_PROVIDER_FORBIDDEN")


def validate_response(data, body):
    if not isinstance(data, dict) or data.get("model") not in {MODEL, MODEL_REVISION}:
        return "PROVIDER_MODEL_MISMATCH"
    try:
        if safe_id(data.get("id")) == "UNKNOWN":
            raise ValueError()
        choices = data["choices"]
        if len(choices) != 1 or choices[0]["finish_reason"] not in {"stop", "tool_calls"}:
            raise ValueError()
        message = choices[0]["message"]
        if message["role"] != "assistant" or not isinstance(message.get("content") or "", str):
            raise ValueError()
        if message.get("reasoning_content") or message.get("reasoning"):
            raise ValueError()
        if choices[0].get("index") != 0:
            raise ValueError()
        calls = message.get("tool_calls", [])
        if not isinstance(calls, list) or len(calls) > 4:
            raise ValueError()
        allowed = {t["function"]["name"] for t in body.get("tools", [])}
        ids, names = set(), []
        for call in calls:
            ident = call["id"]
            if (
                not isinstance(ident, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ident)
                or ident in ids
                or call["type"] != "function"
            ):
                raise ValueError()
            ids.add(ident)
            fn = call["function"]
            name = fn["name"]
            if name not in allowed or name not in {*SCHEMAS, "route"}:
                raise ValueError()
            args = json.loads(fn["arguments"], object_pairs_hook=unique_object)
            if name == "route":
                plan = IntentPlan.model_validate(args)
                if len(calls) != 1 or (
                    len(plan.tasks) > 1 and any(not t.read_only for t in plan.tasks)
                ):
                    raise ValueError()
            else:
                SCHEMAS[name].model_validate(args)
            names.append(name)
        if len(calls) > 1 and any(n in WRITES for n in names):
            raise ValueError()
        if choices[0]["finish_reason"] == "tool_calls" and not calls:
            raise ValueError()
        choice = body.get("tool_choice")
        forced = choice.get("function", {}).get("name") if isinstance(choice, dict) else None
        if forced and (len(names) != 1 or names[0] != forced):
            raise ValueError()
        if (choice == "required" and not calls) or (choice == "none" and calls):
            raise ValueError()
        usage = data.get("usage")
        if isinstance(usage, dict):
            for key in ["prompt_tokens_details", "completion_tokens_details"]:
                details = usage.get(key)
                if details is not None and (
                    not isinstance(details, dict)
                    or any(type(v) is not int or v < 0 for v in details.values())
                    or details.get("reasoning_tokens", 0) != 0
                ):
                    raise ValueError()
    except (KeyError, ValueError, TypeError, ValidationError):
        return "PROVIDER_TOOL_INVALID"
    return None


def sdk_response(data):
    """Only validated nested fields reach SDK parsing; no arbitrary extensions."""
    original = data["choices"][0]
    message = original["message"]
    clean = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        clean["tool_calls"] = [
            {
                "id": c["id"],
                "type": "function",
                "function": {
                    "name": c["function"]["name"],
                    "arguments": c["function"]["arguments"],
                },
            }
            for c in message["tool_calls"]
        ]
    return {
        "id": data["id"],
        "model": data["model"],
        "created": 0,
        "choices": [{"index": 0, "finish_reason": original["finish_reason"], "message": clean}],
        "usage": {
            k: data["usage"][k] for k in ["prompt_tokens", "completion_tokens", "total_tokens"]
        },
    }


class PlaygroundTransport(httpx.AsyncBaseTransport):
    def __init__(self, ledger, role, inner):
        self.ledger, self.role, self.inner = ledger, role, inner

    async def handle_async_request(self, request):
        scope = current_scope.get()
        if scope is None:
            raise RunStopped("RUN_SCOPE_REQUIRED")
        if (
            request.method != "POST"
            or str(request.url) != "https://api.deepseek.com/chat/completions"
        ):
            raise RunStopped("PROVIDER_ENDPOINT_FORBIDDEN")
        raw = await request.aread()
        try:
            body = json.loads(raw, object_pairs_hook=unique_object)
            if (
                len(raw) > 65536
                or body.get("model") != MODEL
                or body.get("thinking") != {"type": "disabled"}
                or body.get("stream", False)
                or body.get("temperature") != 0
                or any(
                    t.get("type") != "function"
                    or t.get("function", {}).get("name") not in {*SCHEMAS, "route"}
                    for t in body.get("tools", [])
                )
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise RunStopped("PROVIDER_REQUEST_INVALID") from None
        node = node_key.get()
        ordinal = scope.next(self.role, node)
        # Synchronous fsync is deliberate: cancellation cannot lose the reservation id
        # between reserve-before-send and entering the first network await.
        token = self.ledger.reserve(
            scope, self.role, node, ordinal, body.get("max_tokens"), hashlib.sha256(raw).hexdigest()
        )
        request.headers["X-Client-Request-ID"] = token
        response = None
        try:
            async with asyncio.timeout(min(30, self.ledger.seconds_left)):
                response = await self.inner.handle_async_request(request)
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 1_000_000:
                        raise ValueError()
                try:
                    data = json.loads(chunks, object_pairs_hook=unique_object)
                except (ValueError, TypeError):
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                error = (
                    "PROVIDER_HTTP_ERROR"
                    if response.status_code != 200
                    else validate_response(data, body)
                )
                error = self.ledger.finish(
                    token,
                    data,
                    response.status_code,
                    response.headers.get("x-request-id", "UNKNOWN"),
                    error=error,
                )
                if error:
                    raise RunStopped(error)
                # Only the normal non-thinking assistant response reaches the SDK.
                return httpx.Response(
                    200,
                    json=sdk_response(data),
                    request=request,
                )
        except RunStopped:
            raise
        except BaseException as exc:
            self.ledger.finish(
                token, {}, "TRANSPORT_UNKNOWN", "UNKNOWN", error="PROVIDER_OUTCOME_UNKNOWN"
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RunStopped("PROVIDER_OUTCOME_UNKNOWN") from None
        finally:
            if response is not None:
                await response.aclose()

    async def aclose(self):
        await self.inner.aclose()


@dataclass
class Clients:
    asynchronous: httpx.AsyncClient
    synchronous: httpx.Client

    async def close(self):
        await self.asynchronous.aclose()
        self.synchronous.close()


def metered_model(ledger, role, key, inner=None):
    if inner is not None and (
        ledger.policy.evidence_mode != "MOCK_TRANSPORT"
        or not isinstance(inner, httpx.MockTransport)
    ):
        raise ValueError("Mock injection must be explicitly labeled MOCK_TRANSPORT")
    if inner is None:
        if ledger.policy.evidence_mode != "LIVE_DEEPSEEK":
            raise ValueError("Offline mode cannot construct a real transport")
        inner = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
    client = httpx.AsyncClient(
        transport=PlaygroundTransport(ledger, role, inner),
        timeout=30,
        follow_redirects=False,
        trust_env=False,
    )
    sync = httpx.Client(transport=DenySync(), follow_redirects=False, trust_env=False)
    model = deepseek_model(key, http_client=sync, http_async_client=client).model_copy(
        update={"temperature": 0, "cache": False}
    )
    return model, Clients(client, sync)
