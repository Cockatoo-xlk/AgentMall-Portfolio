"""Authenticated service identity and owner-scoped usage, never frontend flags."""

from agentmall.agents.budgets import RunStopped
from agentmall.agents.models import AgentRun
from agentmall.agents.run_service import owned_thread
from agentmall.identity.service import require_buyer
from agentmall.infra.errors import DomainError, not_found


async def runtime_status(app, actor, run_id=None):
    require_buyer(actor)
    run = None
    if run_id is not None:
        async with app.state.sessions.begin() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                raise not_found()
            await owned_thread(session, actor, run.thread_id)
    provider = getattr(app.state, "playground", None)
    if provider is not None:
        try:
            result = provider.ledger.summary(actor.user_id, actor.store_id, run_id)
        except RunStopped as exc:
            raise DomainError(503, exc.code, "预算状态无法安全核验，模型调用已停止") from None
        result["identity"] = provider.identity
        result["available_modes"] = ["single", "multi"]
        return result
    models = list((app.state.multi_models or {}).values())
    if app.state.durable_single_model is not None:
        models.append(app.state.durable_single_model)
    fixture = models and all(
        getattr(m, "_llm_type", "").startswith(("offline", "fixture", "agentmall-e2e-fake"))
        for m in models
    )
    mode = "FIXTURE" if fixture else "MODEL_ENABLED_UNVERIFIED" if models else "MODEL_DISABLED"
    return {
        "mode": mode,
        "model_id": "Fixture" if fixture else "UNKNOWN" if models else None,
        "available_modes": (["multi"] if app.state.multi_models else [])
        + (["single"] if app.state.durable_single_model is not None else []),
        "requests_reserved": 0 if not models or fixture else None,
        "valid_responses": 0 if not models or fixture else None,
        "budget_model_attempts": run.budget.get("used", {}).get("models", 0) if run else None,
        "usage_state": "UNKNOWN",
        "usage": None,
        "estimated_upper_cost_cny": "NOT_APPLICABLE" if fixture or not models else "UNKNOWN",
        "actual_bill_cny": "NOT_APPLICABLE" if fixture or not models else "UNKNOWN",
        "halted": None,
        "attempts": [],
    }
