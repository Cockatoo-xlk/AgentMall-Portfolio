"""Real LangChain model/tool middleware with a run-wide budget and batch validation."""

import asyncio
import json
import re
from time import monotonic

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from agentmall.agents.budgets import RunStopped
from agentmall.agents.read_completion import finish_read_batch, supports_read_completion
from agentmall.agents.runtime import fingerprint
from agentmall.agents.specialist_tools import ALL_SCHEMAS, WRITE_TOOLS_BY_GOAL, WRITES


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


class ToolBatchRejected(RunStopped):
    """Stable public code plus fixed diagnostic metadata; never exception/argument text."""

    def __init__(self, detail, category, *, repairable=False, fields=(), code="INVALID_TOOL_BATCH"):
        super().__init__(code)
        self.diagnostic_code = detail
        self.failure_class = category
        self.repairable = repairable
        self.fields = sorted(set(fields))[:10]


BATCH_DIAGNOSTICS = frozenset(
    {
        "MODEL_INVALID_TOOL_CALL",
        "TOOL_ARGUMENT_JSON_INVALID",
        "TOOL_ARGUMENT_DUPLICATE_KEY",
        "TOOL_BATCH_TOO_LARGE",
        "TOOL_BATCH_UNORDERED_WRITE",
        "TOOL_ID_INVALID_OR_REUSED",
        "TOOL_NOT_ALLOWLISTED",
        "READ_ONLY_TOOL_VIOLATION",
        "TOOL_ARGUMENT_SCHEMA_INVALID",
        "TOOL_REPEATED_CALL",
        "TOOL_AUTHORITY_ARGUMENT_FORBIDDEN",
        "TOOL_WRITE_SCOPE_VIOLATION",
    }
)
FAILURE_CLASSES = frozenset(
    {
        "MODEL_OUTPUT_INVALID",
        "TOOL_SCHEMA_REJECTED",
        "POLICY_DENIED",
        "REPAIR_EXHAUSTED",
        "DELEGATION_REJECTED",
        "BUSINESS_OPERATION_FAILED",
    }
)


class DuplicateArgumentKey(ValueError):
    pass


def unique_arguments(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateArgumentKey()
        result[key] = value
    return result


def raw_tool_wire_failures(calls):
    """Checks before SDK normalization; return enums, never input/exception strings."""
    if not isinstance(calls, list):
        return ["MODEL_INVALID_TOOL_CALL"]
    codes = []
    for call in calls:
        try:
            arguments = json.loads(
                call["function"]["arguments"], object_pairs_hook=unique_arguments
            )
            if not isinstance(arguments, dict):
                codes.append("MODEL_INVALID_TOOL_CALL")
        except DuplicateArgumentKey:
            codes.append("TOOL_ARGUMENT_DUPLICATE_KEY")
        except json.JSONDecodeError:
            codes.append("TOOL_ARGUMENT_JSON_INVALID")
        except (ValueError, KeyError, TypeError):
            codes.append("MODEL_INVALID_TOOL_CALL")
    return sorted(set(codes))


def sdk_wire_failures(message):
    flags = message.response_metadata.get("agentmall_tool_wire_failures", [])
    if not isinstance(flags, list) or any(
        not isinstance(code, str)
        or code
        not in {
            "MODEL_INVALID_TOOL_CALL",
            "TOOL_ARGUMENT_DUPLICATE_KEY",
            "TOOL_ARGUMENT_JSON_INVALID",
        }
        for code in flags
    ):
        flags = ["MODEL_INVALID_TOOL_CALL"]
    return [
        ToolBatchRejected(
            code, "MODEL_OUTPUT_INVALID", repairable=code == "TOOL_ARGUMENT_JSON_INVALID"
        )
        for code in flags
    ]


def validate_wire(message):
    flags = sdk_wire_failures(message)
    if flags:
        raise next((failure for failure in flags if not failure.repairable), flags[0])
    try:
        for raw in message.additional_kwargs.get("tool_calls", []):
            json.loads(raw["function"]["arguments"], object_pairs_hook=unique_arguments)
    except DuplicateArgumentKey as exc:
        raise ToolBatchRejected("TOOL_ARGUMENT_DUPLICATE_KEY", "MODEL_OUTPUT_INVALID") from exc
    except json.JSONDecodeError as exc:
        raise ToolBatchRejected(
            "TOOL_ARGUMENT_JSON_INVALID", "MODEL_OUTPUT_INVALID", repairable=True
        ) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID") from exc
    if message.invalid_tool_calls:
        raise ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")


def validate_batch(runtime, context, message):
    # Inspect ALL declared names/IDs/authority before permitting even a format repair.
    # SDK invalid_tool_calls can coexist with otherwise valid parsed tool_calls.
    raw = message.additional_kwargs.get("tool_calls", [])
    if not isinstance(raw, list):
        raise ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
    try:
        raw_metadata = [{"id": c.get("id"), "name": c.get("function", {}).get("name")} for c in raw]
    except (AttributeError, TypeError):
        raise ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID") from None
    sdk_metadata = [*message.tool_calls, *message.invalid_tool_calls]
    metadata = raw_metadata if raw else sdk_metadata
    representations = [raw_metadata, sdk_metadata] if raw else [sdk_metadata]
    new_ids = set()
    for representation in representations:
        new_ids = set()  # The same ID across representations is expected, within one is not.
        for call in representation:
            name = call.get("name")
            if name not in runtime.tool_allowlist(context.envelope.target):
                raise ToolBatchRejected("TOOL_NOT_ALLOWLISTED", "POLICY_DENIED")
            if name in WRITES:
                if context.envelope.read_only:
                    raise ToolBatchRejected("READ_ONLY_TOOL_VIOLATION", "POLICY_DENIED")
                required = WRITE_TOOLS_BY_GOAL.get(context.envelope.goal)
                if required == "prepare_checkout" and runtime.constraints.bundle:
                    required = "prepare_bundle_checkout"
                if not runtime.single and required != name:
                    raise ToolBatchRejected("TOOL_WRITE_SCOPE_VIOLATION", "POLICY_DENIED")
            ident = call.get("id")
            if (
                not isinstance(ident, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ident)
                or ident in runtime.tool_ids
                or ident in new_ids
            ):
                raise ToolBatchRejected("TOOL_ID_INVALID_OR_REUSED", "POLICY_DENIED")
            new_ids.add(ident)
    if raw and sorted((c["id"], c["name"]) for c in raw_metadata) != sorted(
        (c["id"], c["name"]) for c in sdk_metadata
    ):
        raise ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
    failures = sdk_wire_failures(message)
    candidates = []
    if raw:
        for source, meta in zip(raw, metadata, strict=True):
            try:
                arguments = json.loads(
                    source["function"]["arguments"], object_pairs_hook=unique_arguments
                )
            except DuplicateArgumentKey:
                failures.append(
                    ToolBatchRejected("TOOL_ARGUMENT_DUPLICATE_KEY", "MODEL_OUTPUT_INVALID")
                )
            except json.JSONDecodeError:
                failures.append(
                    ToolBatchRejected(
                        "TOOL_ARGUMENT_JSON_INVALID", "MODEL_OUTPUT_INVALID", repairable=True
                    )
                )
            except (ValueError, KeyError, TypeError):
                failures.append(
                    ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
                )
            else:
                if isinstance(arguments, dict):
                    candidates.append({**meta, "args": arguments})
                else:
                    failures.append(
                        ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
                    )
    else:
        candidates = message.tool_calls
        if message.invalid_tool_calls and not failures:
            failures.append(ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID"))
    if raw:
        sdk_valid = {call["id"]: call for call in message.tool_calls}
        sdk_invalid = {call["id"]: call for call in message.invalid_tool_calls}
        if set(sdk_valid) != {call["id"] for call in candidates}:
            failures.append(ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID"))
        for candidate in candidates:
            parsed = sdk_valid.get(candidate["id"])
            if parsed is None or fingerprint(candidate["args"]) != fingerprint(parsed["args"]):
                failures.append(
                    ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
                )
        for source in raw:
            invalid = sdk_invalid.get(source["id"])
            if invalid is not None and invalid.get("args") != source["function"].get("arguments"):
                failures.append(
                    ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
                )
    calls = message.tool_calls
    signatures = []
    for call in candidates:
        schema = ALL_SCHEMAS[call["name"]]
        forbidden = {
            "actor_id",
            "user_id",
            "role",
            "store_id",
            "approved",
            "confirmation_id",
            "price_cents",
            "total_cents",
            "on_hand",
            "reserved",
        } - set(schema.model_fields)
        attempted = set(call["args"]) & forbidden
        if attempted:
            failures.append(
                ToolBatchRejected(
                    "TOOL_AUTHORITY_ARGUMENT_FORBIDDEN", "POLICY_DENIED", fields=attempted
                )
            )
        try:
            args = schema.model_validate(call["args"])
        except ValidationError as exc:
            fields = [
                e["loc"][0]
                for e in exc.errors(include_input=False, include_context=False)
                if e["loc"] and e["loc"][0] in schema.model_fields
            ]
            failures.append(
                ToolBatchRejected(
                    "TOOL_ARGUMENT_SCHEMA_INVALID",
                    "TOOL_SCHEMA_REJECTED",
                    repairable=True,
                    fields=fields,
                )
            )
            continue
        signature = fingerprint(
            {
                "role": context.envelope.target,
                "tool": call["name"],
                "arguments": args.model_dump(mode="json"),
            }
        )
        repeated = runtime.tool_repeats.get(signature, 0)
        if repeated >= 2 or (
            (call["name"] in WRITES or getattr(context, "repairing", False)) and repeated
        ):
            failures.append(
                ToolBatchRejected("TOOL_REPEATED_CALL", "POLICY_DENIED", code="REPEATED_TOOL_CALL")
            )
        signatures.append(signature)
    if failures:
        # A schema error in an earlier sibling must never hide a policy denial.
        raise next(
            (failure for failure in failures if failure.failure_class == "POLICY_DENIED"),
            next((failure for failure in failures if not failure.repairable), failures[0]),
        )
    if raw and ([{k: c[k] for k in ("id", "name", "args")} for c in calls] != candidates):
        raise ToolBatchRejected("MODEL_INVALID_TOOL_CALL", "MODEL_OUTPUT_INVALID")
    if len(calls) > 4:
        raise ToolBatchRejected("TOOL_BATCH_TOO_LARGE", "MODEL_OUTPUT_INVALID", repairable=True)
    if len(calls) > 1 and any(c["name"] in WRITES for c in calls):
        raise ToolBatchRejected(
            "TOOL_BATCH_UNORDERED_WRITE",
            "MODEL_OUTPUT_INVALID",
            repairable=True,
            code="UNORDERED_WRITE_BATCH",
        )
    return calls, new_ids, signatures


def legacy_batch_code(message, default):
    """Preserve public precedence only; never changes whether repair is authorized."""
    if message.invalid_tool_calls or sdk_wire_failures(message):
        return "INVALID_TOOL_BATCH"
    raw = message.additional_kwargs.get("tool_calls", [])
    if raw_tool_wire_failures(raw):
        return "INVALID_TOOL_BATCH"
    calls = message.tool_calls
    if len(calls) > 4:
        return "INVALID_TOOL_BATCH"
    if len(calls) > 1 and any(call["name"] in WRITES for call in calls):
        return "UNORDERED_WRITE_BATCH"
    return default


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
        if supports_read_completion(self.runtime, self.context.envelope):
            # END is a compiled SDK destination, not evidence of completion.
            # Disarm before any tool can run, including rejected/partial batches.
            for tool in self.context.bound_tools.values():
                tool.return_direct = False
        message = state["messages"][-1]
        try:
            calls, new_ids, signatures = validate_batch(self.runtime, self.context, message)
            if calls:
                try:
                    if hasattr(self.runtime.budget, "claim_tools"):
                        await self.runtime.budget.claim_tools(new_ids, signatures)
                    else:
                        await self.runtime.budget.take("tools", len(calls))
                except RunStopped as exc:
                    if exc.code in {"INVALID_TOOL_BATCH", "REPEATED_TOOL_CALL"}:
                        detail = (
                            "TOOL_ID_INVALID_OR_REUSED"
                            if exc.code == "INVALID_TOOL_BATCH"
                            else "TOOL_REPEATED_CALL"
                        )
                        raise ToolBatchRejected(detail, "POLICY_DENIED", code=exc.code) from exc
                    raise
        except ToolBatchRejected as exc:
            requested_names = {
                c.get("name") for c in [*message.tool_calls, *message.invalid_tool_calls]
            }
            intent_denied = (
                bool(requested_names & {"prepare_checkout", "prepare_bundle_checkout"})
                and not self.runtime.constraints.purchase_requested
            ) or (
                "prepare_return" in requested_names
                and not self.runtime.constraints.return_requested
            )
            if exc.repairable and intent_denied:
                # Do not turn a forbidden intent into a model format retry.
                # Valid calls retain the original authoritative domain refusal path.
                exc.repairable = False
                exc.failure_class = "POLICY_DENIED"
                exc.diagnostic_code = "TOOL_WRITE_SCOPE_VIOLATION"
            exc.code = legacy_batch_code(message, exc.code)
            exc.args = (exc.code,)
            self.runtime.event(
                "tool_batch_rejected",
                attempt=self.runtime.budget.used["models"],
                role=self.role,
                subtask_id=self.context.envelope.subtask_id,
                error_code=exc.code,
                diagnostic_code=exc.diagnostic_code,
                tool_names=sorted(
                    {
                        c["name"]
                        for c in [*message.tool_calls, *message.invalid_tool_calls]
                        if isinstance(c.get("name"), str) and c["name"] in ALL_SCHEMAS
                    }
                ),
                failure_class=exc.failure_class,
                violation_fields=exc.fields,
                repairable=exc.repairable,
                repair_consumed=bool(self.runtime.budget.orchestration_repair),
                tools_executed=False,
                phase="MODEL_OUTPUT_VALIDATION",
                budget=dict(self.runtime.budget.used),
            )
            if hasattr(self.runtime.budget, "record_model_event"):
                await self.runtime.budget.record_model_event(
                    {
                        **self.runtime.trace["events"][-1],
                        "attempt": self.runtime.budget.used["models"],
                    }
                )
            raise
        if calls:
            self.context.pending_tool_ids = set(new_ids)
            self.context.read_batch_settled = (
                asyncio.Event()
                if supports_read_completion(self.runtime, self.context.envelope)
                else None
            )
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
            phase="TOOL_EXECUTION",
            tools_executed=True,
            failure_class="BUSINESS_OPERATION_FAILED" if body.get("error_code") else None,
        )
        if body.get("error_code"):
            self.context.records.append({"name": call["name"], "error_code": body["error_code"]})
        self.context.pending_tool_ids.discard(call["id"])
        if not self.context.pending_tool_ids:
            try:
                finish_read_batch(self.runtime, self.context)
            finally:
                if self.context.read_batch_settled is not None:
                    self.context.read_batch_settled.set()
        if self.context.read_batch_settled is not None:
            # SDK tools run as parallel Send branches: an early sibling must not
            # route back to the model before the final sibling's receipt commits.
            # Cancellation propagates normally; this creates no detached task.
            await self.context.read_batch_settled.wait()
        return result
