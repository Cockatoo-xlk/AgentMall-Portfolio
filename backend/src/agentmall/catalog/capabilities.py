"""Synthetic catalogue capability contract, independent of model interpretation."""

from sqlalchemy import and_, func, or_

WIRELESS_LABELS = ("无线", "双模", "三模")


def connection_matches(attributes, connection, excluded=()):
    label = attributes.get("connection")
    if label in excluded:
        return False
    if connection not in {"无线", "有线"}:
        return connection is None or label == connection
    if "connection_capabilities" not in attributes:
        return label == connection
    capabilities = attributes["connection_capabilities"]
    allowed_labels = WIRELESS_LABELS if connection == "无线" else ("有线",)
    allowed_capabilities = ("wired", "wireless") if connection == "无线" else ("wired",)
    required = "wireless" if connection == "无线" else "wired"
    return (
        label in allowed_labels
        and type(capabilities) is list
        and all(c in allowed_capabilities for c in capabilities)
        and required in capabilities
    )


def connection_conditions(attributes, connection, excluded=()):
    label = attributes["connection"].as_string()
    result = []
    if excluded:
        result.append(or_(label.is_(None), label.not_in(excluded)))
    if connection in {"无线", "有线"}:
        capabilities = attributes["connection_capabilities"]
        labels = WIRELESS_LABELS if connection == "无线" else ("有线",)
        allowed = ["wired", "wireless"] if connection == "无线" else ["wired"]
        required = "wireless" if connection == "无线" else "wired"
        result.append(
            or_(
                and_(~attributes.has_key("connection_capabilities"), label == connection),
                and_(
                    label.in_(labels),
                    func.jsonb_typeof(capabilities) == "array",
                    capabilities.contained_by(allowed),
                    capabilities.contains([required]),
                ),
            )
        )
    elif connection is not None:
        result.append(label == connection)
    return result
