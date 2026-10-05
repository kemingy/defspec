"""Shared document validation and JSON snapshot assertions."""

from pathlib import Path
from typing import Any

import msgspec
from openapi_spec_validator import OpenAPIV31SpecValidator

from defspec import OpenAPI

_SNAPSHOTS = Path(__file__).parent / "snapshots"


class PathParameters(msgspec.Struct):
    user_id: int = msgspec.field(default=1, name="id")


def valid_document(api: OpenAPI) -> dict[str, Any]:
    document = api.to_dict()
    OpenAPIV31SpecValidator(document).validate()
    assert msgspec.json.decode(api.to_json()) == document
    assert msgspec.json.decode(api.to_json(), type=OpenAPI).to_dict() == document
    return document


def assert_snapshot(api: OpenAPI, name: str) -> None:
    expected = msgspec.json.decode((_SNAPSHOTS / f"{name}.json").read_bytes())
    assert _normalize_document(valid_document(api)) == _normalize_document(expected)


def _normalize_schema(schema: Any) -> Any:
    """Sort unordered schema arrays without changing literal JSON values."""
    if not isinstance(schema, dict):
        return schema
    normalized = schema.copy()
    for keyword in ("required", "enum"):
        if isinstance(schema.get(keyword), list):
            normalized[keyword] = sorted(
                schema[keyword],
                key=lambda value: msgspec.json.encode(value, order="deterministic"),
            )
    for keyword in ("properties", "patternProperties", "dependentSchemas", "$defs"):
        if keyword in schema:
            normalized[keyword] = {
                name: _normalize_schema(value)
                for name, value in schema[keyword].items()
            }
    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if keyword in schema:
            normalized[keyword] = [
                _normalize_schema(value) for value in schema[keyword]
            ]
    for keyword in (
        "items",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "unevaluatedItems",
        "contentSchema",
    ):
        if keyword in schema:
            normalized[keyword] = _normalize_schema(schema[keyword])
    return normalized


def _normalize_document(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_document(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, item in value.items():
        if key == "schema":
            normalized[key] = _normalize_schema(item)
        elif key == "schemas":
            normalized[key] = {
                name: _normalize_schema(schema) for name, schema in item.items()
            }
        elif key in ("example", "examples", "value") or key.startswith("x-"):
            normalized[key] = item
        else:
            normalized[key] = _normalize_document(item)
    return normalized
