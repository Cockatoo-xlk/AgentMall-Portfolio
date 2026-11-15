"""Minimal observations of server-verified proposals; not an authorization decision."""

from uuid import UUID

STATUSES = {"PENDING", "APPROVED", "EXECUTED", "REJECTED", "EXPIRED"}
ACTIONS = {"CHECKOUT", "RETURN_REQUEST"}


def action_outcomes(facts):
    """The caller must supply runtime.facts, never model-produced claims or summaries."""
    outcomes = []
    for (kind, identifier), value in facts.items():
        if kind != "proposal" or not isinstance(value, dict):
            continue
        try:
            proposal_id = str(UUID(str(identifier)))
            if str(UUID(str(value.get("proposal_id")))) != proposal_id:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        action, status = value.get("action_type"), value.get("status")
        if action not in ACTIONS or status not in STATUSES:
            continue
        outcomes.append({"proposal_id": proposal_id, "action_type": action, "status": status})
    return sorted(outcomes, key=lambda outcome: outcome["proposal_id"])
