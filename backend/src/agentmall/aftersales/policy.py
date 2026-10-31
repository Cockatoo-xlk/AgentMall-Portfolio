"""Versioned synthetic rules, independent of model text and retrieval."""

from datetime import timedelta

from agentmall.aftersales.schemas import EligibilityResult

POLICY_WINDOWS = {"demo-v1": timedelta(days=7)}
HUMAN_REASONS = {"QUALITY_DISPUTE", "POLICY_DISPUTE", "INSUFFICIENT_INFORMATION", "OTHER"}


def evaluate_eligibility(
    *, status, delivered_at, policy_version, has_payment, has_active_case, reason_code, now
):
    if now.tzinfo is None or (delivered_at is not None and delivered_at.tzinfo is None):
        raise ValueError("Eligibility clocks must be timezone-aware")
    reasons = []
    human = False
    if policy_version not in POLICY_WINDOWS:
        reasons.append("UNSUPPORTED_POLICY")
        human = True
    if not has_payment:
        reasons.append("NOT_PAID")
    if status == "REFUNDED":
        reasons.append("ALREADY_REFUNDED")
    elif status != "DELIVERED":
        reasons.append("NOT_DELIVERED")
    if delivered_at is None:
        reasons.append("MISSING_DELIVERY_TIME")
    elif now < delivered_at:
        reasons.append("INVALID_DELIVERY_TIME")
        human = True
    elif policy_version in POLICY_WINDOWS and now - delivered_at > POLICY_WINDOWS[policy_version]:
        reasons.append("OUTSIDE_RETURN_WINDOW")
        human = True
    if has_active_case:
        reasons.append("ACTIVE_CASE_EXISTS")
    if reason_code in HUMAN_REASONS:
        reasons.append("REQUIRES_HUMAN_REVIEW")
        human = True
    return EligibilityResult(
        eligible=not reasons,
        reason_codes=reasons,
        requires_human=human,
        policy_version=policy_version,
    )
