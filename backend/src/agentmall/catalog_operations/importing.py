"""Bounded text-only ingestion. No file paths, fetching, scripts or spreadsheet execution."""

import csv
import io
import json

from pydantic import ValidationError

from agentmall.catalog_operations.schemas import ProductData
from agentmall.infra.errors import DomainError

MAX_CONTENT = 131072
MAX_ROWS = 50
COLUMNS = {"name", "category", "description", "price_cents", "on_hand", "attributes"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_rows(payload):
    if len(payload.content.encode("utf-8")) > MAX_CONTENT:
        raise DomainError(413, "FILE_TOO_LARGE", "商品资料不得超过128 KiB")
    text = payload.content.lstrip("\ufeff")
    try:
        if payload.format == "json":
            rows = json.loads(text, object_pairs_hook=unique_object)
            if not isinstance(rows, list):
                raise ValueError("array required")
        else:
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            headers = reader.fieldnames or []
            if (
                len(headers) != len(set(headers))
                or not set(headers) <= COLUMNS
                or not {"name", "price_cents", "on_hand"} <= set(headers)
            ):
                raise ValueError("invalid headers")
            rows = []
            for row in reader:
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise ValueError("row limit")
        if not 1 <= len(rows) <= MAX_ROWS:
            raise ValueError("row limit")
    except (ValueError, TypeError, csv.Error, RecursionError) as error:
        raise DomainError(
            422, "INVALID_IMPORT_FORMAT", "需要有效JSON数组或固定列CSV，1–50行"
        ) from error
    accepted = []
    errors = []
    for index, raw in enumerate(rows, 1):
        try:
            if not isinstance(raw, dict) or not set(raw) <= COLUMNS:
                raise ValueError("unexpected columns")
            values = dict(raw)
            if payload.format == "csv":
                for key in ["price_cents", "on_hand"]:
                    if not values.get(key, "").isdigit():
                        raise ValueError("integer required")
                    values[key] = int(values[key])
                if "attributes" in values:
                    values["attributes"] = json.loads(
                        values["attributes"] or "{}", object_pairs_hook=unique_object
                    )
                if values.get("category") == "":
                    values["category"] = None
            data = ProductData.model_validate(values)
            accepted.append((index, data, raw))
        except (ValueError, TypeError, ValidationError, RecursionError):
            errors.append({"row": index, "code": "ROW_VALIDATION_ERROR"})
    return accepted, errors
