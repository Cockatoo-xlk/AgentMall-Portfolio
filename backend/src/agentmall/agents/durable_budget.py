"""Reserve against the Run row before any external call; checkpoint replay never resets it."""

from contextvars import ContextVar
from copy import deepcopy

from agentmall.agents.budgets import GraphBudget, RunStopped

node_key = ContextVar("agentmall_node_key", default="outside")


def model_event_key(event):
    key = f"{event['kind']}:{event.get('attempt')}"
    if event["kind"] not in {"model_start", "model_end"}:
        key += f":{event.get('role')}:{event.get('subtask_id')}"
    return key


class DurableBudget(GraphBudget):
    persists_rejections = True

    async def record_model_event(self, event):
        """Persist safe metadata even if the containing node never journals.

        Uses the existing RunEvent store and fence, outside domain transactions.
        Marks and events commit together; journal/recovery cannot duplicate them.
        """
        from agentmall.agents.run_service import add_event

        key = model_event_key(event)
        async with self.lock:
            async with self.fence.sessions.begin() as session:
                run = await self.fence.check(session, exclusive=True)
                data = deepcopy(run.budget)
                recorded = data.setdefault("model_events", [])
                if key in recorded:
                    return
                add_event(session, run, event["kind"], event, event.get("role"))
                recorded.append(key)
                run.budget = data

    def __init__(self, fence, limits=None):
        super().__init__(limits)
        self.fence = fence

    def adopt(self, data):
        self.orchestration_repair = data.get("orchestration_repair")
        self.used.update(data.get("used", {}))
        self.reservations = {int(k): v for k, v in data.get("reservations", {}).items()}

    async def reload(self):
        async with self.fence.sessions.begin() as session:
            run = await self.fence.check(session)
            self.adopt(run.budget)

    async def mutate(self, change):
        async with self.lock:
            async with self.fence.sessions.begin() as session:
                run = await self.fence.check(session, exclusive=True)
                data = deepcopy(run.budget)
                self.adopt(data)
                result = change(data)
                data["used"] = dict(self.used)
                data["reservations"] = {str(k): v for k, v in self.reservations.items()}
                run.budget = data
                return result

    async def take(self, kind, count=1):
        def change(data):
            charge = count
            if kind in {"steps", "delegations"}:
                key = kind + ":" + node_key.get()
                previous = data.setdefault("once", {}).get(key, 0)
                charge = max(0, count - previous)
                data["once"][key] = max(previous, count)
            if self.seconds_left <= 0 or self.used[kind] + charge > getattr(self.limits, kind):
                raise RunStopped("BUDGET_EXCEEDED")
            self.used[kind] += charge

        await self.mutate(change)

    async def start_model(self):
        def change(data):
            if self.seconds_left <= 0 or self.used["models"] >= self.limits.models:
                raise RunStopped("BUDGET_EXCEEDED")
            cap = min(2048, self.limits.output_tokens - self.used["output_tokens"])
            if cap <= 0:
                raise RunStopped("BUDGET_EXCEEDED")
            self.used["models"] += 1
            self.used["output_tokens"] += cap
            token = self.used["models"]
            self.reservations[token] = cap
            return token

        return await self.mutate(change)

    async def claim_repair(self, error_code, *, fields=()):
        # The rejecting node may never journal/checkpoint. Record its safe error
        # together with the correction claim, BEFORE another model invocation.
        from agentmall.agents.run_service import add_event

        async with self.lock:
            async with self.fence.sessions.begin() as session:
                run = await self.fence.check(session, exclusive=True)
                data = deepcopy(run.budget)
                allowed = data.get("orchestration_repair") is None
                if allowed:
                    data["orchestration_repair"] = {
                        "error_code": error_code,
                        "node": node_key.get(),
                    }
                # Repeated observation of the same rejection is not a new event.
                key = f"{node_key.get()}:{data.get('used', {}).get('models', 0)}:{error_code}"
                recorded = data.setdefault("rejection_events", [])
                if key not in recorded:
                    add_event(
                        session,
                        run,
                        "orchestration_rejected",
                        {"error_code": error_code, "constraint_fields": list(fields)},
                    )
                    recorded.append(key)
                run.budget = data
                self.orchestration_repair = data.get("orchestration_repair")
                return allowed

    async def claim_tools(self, identifiers, signatures):
        def change(data):
            claimed = set(data.get("tool_ids", []))
            repeats = dict(data.get("tool_repeats", {}))
            if claimed.intersection(identifiers):
                raise RunStopped("INVALID_TOOL_BATCH")
            for signature in signatures:
                repeats[signature] = repeats.get(signature, 0) + 1
                if repeats[signature] > 2:
                    raise RunStopped("REPEATED_TOOL_CALL")
            if self.seconds_left <= 0 or self.used["tools"] + len(identifiers) > self.limits.tools:
                raise RunStopped("BUDGET_EXCEEDED")
            self.used["tools"] += len(identifiers)
            data["tool_ids"] = sorted(claimed | set(identifiers))
            data["tool_repeats"] = repeats

        await self.mutate(change)

    async def finish_model(self, token, message):
        def change(data):
            reserved = self.reservations.pop(token)
            usage = message.usage_metadata if message is not None else None
            raw = message.response_metadata.get("token_usage") if message is not None else None
            if usage is None or (raw is not None and type(raw.get("completion_tokens")) is not int):
                return
            output = usage.get("output_tokens")
            if type(output) is not int or not 0 <= output <= reserved:
                raise RunStopped("MODEL_USAGE_INVALID")
            self.used["output_tokens"] -= reserved - output

        await self.mutate(change)
