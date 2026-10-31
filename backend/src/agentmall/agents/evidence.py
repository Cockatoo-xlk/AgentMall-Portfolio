"""Conservative applicability gate, not a relevance-score or eligibility replacement."""


def policy_support(query):
    if any(
        word in query.lower()
        for word in (
            "内部",
            "审核备注",
            "系统指令",
            "忽略",
            "system prompt",
            "internal",
            "密码",
            "token",
            "jwt",
        )
    ):
        return "unsupported"
    if any(
        word in query for word in ("退货", "退款", "签收", "期限", "质量", "政策", "争议", "售后")
    ):
        return "context_only"
    return "unsupported"
