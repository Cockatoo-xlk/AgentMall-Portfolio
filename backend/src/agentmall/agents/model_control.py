"""Real LangChain model/tool middleware with a run-wide budget and batch validation."""

import asyncio
import json
import re
from time import monotonic

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from agentmall.agents.budgets import RunStopped
from agentmall.agents.runtime import fingerprint
from agentmall.agents.single_agent import unique_object
from agentmall.agents.specialist_tools import ALL_SCHEMAS, WRITES


async def model_call(runtime, role, invoke):
    model = runtime.models[role]
    if getattr(model, "max_retries", 0) != 0:
        raise RunStopped("HIDDEN_RETRIES_FORBIDDEN")
    reservation = await runtime.budget.start_model()
    cap = runtime.budget.reservations[reservation]
    runtime.event(
        "model_start",
        role=role,
        attempt=reservation,
        max_output_tokens=cap,
        budget=dict(runtime.budget.used),
    )
    if hasattr(runtime.budget, "record_model_event"):
        await runtime.budget.record_model_event(runtime.trace["events"][-1])
    message = None
    started = monotonic()
    try:
        async with asyncio.timeout(min(30, runtime.budget.seconds_left)):
            result = await invoke(cap)
        if isinstance(result, AIMessage):
            message = result
        else:
            messages = [m for m in result.result if isinstance(m, AIMessage)]
            if len(messages) != 1:
                raise RunStopped("MODEL_PROTOCOL_ERROR")
            message = messages[0]
        return result
    finally:
        settlement_error = None
        try:
            await runtime.budget.finish_model(reservation, message)
        except RunStopped as exc:
            settlement_error = exc.code
            raise
        finally:
            raw_usage = message.response_metadata.get("token_usage") if message else None
            usage = message.usage_metadata if message else None
            if settlement_error or (
                raw_usage is not None and type(raw_usage.get("completion_tokens")) is not int
            ):
                usage = None
            runtime.event(
                "model_end",
                duration_ms=round((monotonic() - started) * 1000),
                status="completed" if message and not settlement_error else "failed",
                error_code=settlement_error,
                role=role,
                budget=dict(runtime.budget.used),
                attempt=reservation,
                usage=usage or "UNKNOWN",
                response_model=message.response_metadata.get("model_name", "UNKNOWN")
                if message
                else "UNKNOWN",
            )
            if hasattr(runtime.budget, "record_model_event"):
                await runtime.budget.record_model_event(runtime.trace["events"][-1])


def validate_wire(message):
    if message.invalid_tool_calls:
        raise RunStopped("INVALID_TOOL_BATCH")
    try:
        for raw in message.additional_kwargs.get("tool_calls", []):
            json.loads(raw["function"]["arguments"], object_pairs_hook=unique_object)
    except (ValueError, KeyError, TypeError) as exc:
        raise RunStopped("INVALID_TOOL_BATCH") from exc


class SpecialistGuard(AgentMiddleware):
    def __init__(self, runtime, context):
        self.runtime, self.context = runtime, context
        self.role = context.envelope.target

    async def awrap_model_call(self, request, handler):
        self.runtime.event(
            "model_context",
            role=self.role,
            subtask_id=self.context.envelope.subtask_id,
            message_types=[m.type for m in request.messages],
            context_hash=fingerprint([m.content for m in request.messages]),
        )

        async def invoke(cap):
            return await handler(
                request.override(model_settings={**request.model_settings, "max_tokens": cap})
            )

        return await model_call(self.runtime, self.role, invoke)

    async def aafter_model(self, state, runtime):
        message = state["messages"][-1]
        validate_wire(message)
        calls = message.tool_calls
        if len(calls) > 4:
            raise RunStopped("INVALID_TOOL_BATCH")
        if len(calls) > 1 and any(c["name"] in WRITES for c in calls):
            raise RunStopped("UNORDERED_WRITE_BATCH")
        new_ids = set()
        signatures = []
        try:
            for call in calls:
                ident = call["id"]
                if (
                    not isinstance(ident, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ident)
                    or ident in self.runtime.tool_ids
                    or ident in new_ids
                ):
                    raise ValueError("Invalid tool identity")
                if call["name"] not in self.runtime.tool_allowlist(self.role):
                    raise ValueError("Invalid tool")
                if call["name"] in WRITES and self.context.envelope.read_only:
                    raise ValueError("Read only")
                args = ALL_SCHEMAS[call["name"]].model_validate(call["args"])
                signature = fingerprint(
                    {
                        "role": self.role,
                        "tool": call["name"],
                        "arguments": args.model_dump(mode="json"),
                    }
                )
                if self.runtime.tool_repeats.get(signature, 0) >= 2:
                    raise RunStopped("REPEATED_TOOL_CALL")
                new_ids.add(ident)
                signatures.append(signature)
        except (KeyError, ValueError, TypeError, ValidationError) as exc:
            raise RunStopped("INVALID_TOOL_BATCH") from exc
        if calls:
            if hasattr(self.runtime.budget, "claim_tools"):
                await self.runtime.budget.claim_tools(new_ids, signatures)
            else:
                await self.runtime.budget.take("tools", len(calls))
            self.runtime.tool_ids.update(new_ids)
            for signature in signatures:
                self.runtime.tool_repeats[signature] = (
                    self.runtime.tool_repeats.get(signature, 0) + 1
                )
        else:
            self.runtime.event(
                "model_final",
                role=self.role,
                sha256=fingerprint(message.content),
                trusted_as_business_fact=False,
            )
        return None

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        arguments = ALL_SCHEMAS[call["name"]].model_validate(call["args"]).model_dump(mode="json")
        started = monotonic()
        try:
            result = await handler(request)
            body = json.loads(result.content)
        except Exception:
            body = {
                "ok": False,
                "data": None,
                "error_code": "TOOL_FAILED",
                "retryable": False,
                "evidence_refs": [],
            }
            result = ToolMessage(
                content=json.dumps(body), tool_call_id=call["id"], name=call["name"]
            )
        self.runtime.event(
            "tool",
            duration_ms=round((monotonic() - started) * 1000),
            ok=bool(body.get("ok")),
            evidence_refs=body.get("evidence_refs", []),
            entity_refs=[
                self.runtime.references[key].model_dump(mode="json")
                for key in self.context.observed
            ],
            role=self.role,
            subtask_id=self.context.envelope.subtask_id,
            tool_call_id=call["id"],
            name=call["name"],
            validated_arguments=arguments,
            tool_result=body,
            error_code=body.get("error_code"),
        )
        if body.get("error_code"):
            self.context.records.append({"name": call["name"], "error_code": body["error_code"]})
        return result
