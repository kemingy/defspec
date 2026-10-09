"""Shared document validation and JSON snapshot assertions."""

from copy import deepcopy
from pathlib import Path
from typing import Any, get_args

import msgspec
from openapi_spec_validator import OpenAPIV31SpecValidator

from defspec import OpenAPI
from defspec.spec import HTTP_METHODS

_SNAPSHOTS = Path(__file__).parent / "snapshots"


class PathParameters(msgspec.Struct):
    user_id: int = msgspec.field(name="id")


def valid_document(api: OpenAPI) -> dict[str, Any]:
    document = api.to_dict()
    OpenAPIV31SpecValidator(document).validate()
    assert msgspec.json.decode(api.to_json()) == document
    assert msgspec.json.decode(api.to_json(), type=OpenAPI).to_dict() == document
    return document


def assert_snapshot(api: OpenAPI, name: str) -> None:
    expected = msgspec.json.decode((_SNAPSHOTS / f"{name}.json").read_bytes())
    actual = msgspec.json.encode(
        _normalize_document(valid_document(api)), order="deterministic"
    )
    expected = msgspec.json.encode(_normalize_document(expected), order="deterministic")
    assert (
        msgspec.json.format(actual).decode() == msgspec.json.format(expected).decode()
    )


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


def _normalize_schema_fields(value: dict[str, Any]) -> None:
    """Normalize schemas in parameter, header, body and media type objects."""
    if "schema" in value:
        value["schema"] = _normalize_schema(value["schema"])
    for media in value.get("content", {}).values():
        _normalize_schema_fields(media)
    for encoding in value.get("encoding", {}).values():
        for header in encoding.get("headers", {}).values():
            _normalize_schema_fields(header)


def _normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    """Normalize schema locations emitted by defspec without changing user data."""
    normalized = deepcopy(document)
    schemas = normalized.get("components", {}).get("schemas", {})
    for name, schema in schemas.items():
        schemas[name] = _normalize_schema(schema)
    for path in normalized.get("paths", {}).values():
        for method in get_args(HTTP_METHODS):
            if method not in path:
                continue
            operation = path[method]
            for parameter in operation.get("parameters", []):
                _normalize_schema_fields(parameter)
            _normalize_schema_fields(operation.get("requestBody", {}))
            for response in operation.get("responses", {}).values():
                _normalize_schema_fields(response)
    return normalized
