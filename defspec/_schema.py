"""Convert msgspec schemas into OpenAPI components and parameters."""

from __future__ import annotations

import enum
import inspect
import sys
from collections.abc import Callable
from copy import deepcopy
from typing import (
    Annotated,
    Any,
    NewType,
    Optional,
    TypeGuard,
    cast,
    get_args,
    get_origin,
)

import msgspec

from defspec.models import OpenAPIParam, ParameterLocation, Schema

SchemaHook = Callable[[type], Schema]

__MSGSPEC_STRUCT_DOC__ = inspect.getdoc(msgspec.Struct)

_REF_PREFIX = "#/components/schemas/"
_STRUCTURE = {"type", "properties", "required", "$comment"}
# Model metadata and unknown-field rejection cannot be represented by separate
# parameters. Only drop additionalProperties: false if it allows every model field.
_IGNORED = {"title", "description", "additionalProperties"}
_RESERVED_HEADERS = ("accept", "content-type", "authorization")


def get_def_doc(obj: Any) -> str:
    """Get the docstring of a type."""
    doc = inspect.getdoc(obj)
    # Ignore msgspec's inherited Struct docstring.
    return doc if doc is not None and doc != __MSGSPEC_STRUCT_DOC__ else ""


def _scalar_parameter_type(type_: Any) -> Optional[Any]:
    """Return the concrete type a scalar parameter is named after, if any."""
    if get_origin(type_) is Annotated:
        type_ = get_args(type_)[0]
    # Generic aliases, unions, and literals are named after their typing construct.
    if get_origin(type_) is not None or not isinstance(type_, (type, NewType)):
        return None
    return type_


def _own_doc(type_: Any) -> str:
    """Get an Enum or custom scalar's own docstring."""
    if not isinstance(
        msgspec.inspect.type_info(type_),
        (msgspec.inspect.EnumType, msgspec.inspect.CustomType),
    ):
        return ""
    doc = getattr(type_, "__dict__", {}).get("__doc__")
    # Python 3.10 sets this placeholder on enums without a docstring.
    if (
        sys.version_info < (3, 11)
        and isinstance(type_, enum.EnumMeta)
        and doc == "An enumeration."
    ):
        return ""
    return inspect.cleandoc(doc) if isinstance(doc, str) else ""


def _is_object_model(schema: Any) -> TypeGuard[dict[str, Any]]:
    return (
        isinstance(schema, dict)
        and schema.get("type") == "object"
        and "properties" in schema
    )


def _add_schema(
    type_: Any,
    components: dict[str, Schema],
    schema_hook: Optional[SchemaHook],
) -> Schema:
    """Return the schema of a type and add its definitions to `components`."""
    schemas, definitions = msgspec.json.schema_components(
        (type_,),
        # msgspec 0.20's stubs omit the True schemas supported at runtime.
        schema_hook=cast(Optional[Callable[[type], dict[str, Any]]], schema_hook),
        ref_template=_REF_PREFIX + "{name}",
    )
    for name, definition in definitions.items():
        if not name:
            raise ValueError("Model names must not be empty.")
        if name in components and components[name] != definition:
            raise ValueError(
                f"Conflicting schema name {name!r}; use distinct model names."
            )
        components[name] = definition
    return schemas[0]


def _intersect_schemas(base: Schema, constraint: Schema) -> Schema:
    """Intersect schemas without overriding a constraint from either source."""
    if base is False or constraint is False:
        return False
    if base is True:
        return constraint
    if constraint is True or base == constraint:
        return base
    schema: dict[str, Any] = {"allOf": [base, constraint]}
    # Parameter descriptions are read from the top level of the field schema.
    description = constraint.get("description", base.get("description"))
    if description is not None:
        schema["description"] = description
    return schema


def _check_model(schema: dict[str, Any], fields: dict[str, Any]) -> None:
    """Reject constraints that cannot be represented by separate parameters."""
    properties = schema.get("properties", {})
    unsupported = schema.keys() - _STRUCTURE - _IGNORED
    if schema.get("type", "object") != "object":
        unsupported.add("type")
    if schema.get("additionalProperties", False) is not False or (
        schema.get("additionalProperties") is False
        and fields.keys() - properties.keys()
    ):
        unsupported.add("additionalProperties")
    if unsupported:
        raise ValueError(
            f"Cannot expand parameter model constraints: {', '.join(sorted(unsupported))}."
        )
    undeclared = (properties.keys() | set(schema.get("required", []))) - fields.keys()
    if undeclared:
        raise ValueError(
            "Cannot expand parameter model constraints for undeclared fields: "
            f"{', '.join(sorted(undeclared))}."
        )


def _parameter_model(schema: Schema, components: dict[str, Schema]) -> Schema:
    """Return the object model whose fields become parameters, or `schema` for a scalar."""
    if not isinstance(schema, dict) or not schema.get("$ref", "").startswith(
        _REF_PREFIX
    ):
        # Inline schema, such as one returned by a schema hook.
        if _is_object_model(schema):
            _check_model(schema, schema["properties"])
        return schema

    model = components.get(schema["$ref"].removeprefix(_REF_PREFIX))
    if not isinstance(model, dict):
        return schema
    if not _is_object_model(model):
        if model.get("type") in ("array", "object"):
            raise ValueError(
                "Cannot expand a parameter model without named fields; "
                "use a model with named fields."
            )
        return schema
    # msgspec places Annotated constraints next to the $ref.
    annotation = {key: value for key, value in schema.items() if key != "$ref"}
    _check_model(model, model["properties"])
    _check_model(annotation, model["properties"])

    properties = model["properties"].copy()
    for name, constraint in annotation.get("properties", {}).items():
        properties[name] = _intersect_schemas(properties[name], constraint)
    return {
        "type": "object",
        "properties": properties,
        "required": list(
            dict.fromkeys([*model.get("required", []), *annotation.get("required", [])])
        ),
    }


def _has_schema_default(schema: Schema, components: dict[str, Schema]) -> bool:
    """Check defaults for the whole value, excluding nested values and literal data."""
    schemas = [schema]
    visited: set[str] = set()
    while schemas:
        schema = schemas.pop()
        if not isinstance(schema, dict):
            continue
        if "default" in schema:
            return True
        reference = schema.get("$ref", "")
        if reference.startswith(_REF_PREFIX) and reference not in visited:
            visited.add(reference)
            schemas.append(components.get(reference.removeprefix(_REF_PREFIX), False))
        for keyword in ("allOf", "anyOf", "oneOf"):
            schemas.extend(schema.get(keyword, []))
        for keyword in ("if", "then", "else", "not"):
            if keyword in schema:
                schemas.append(schema[keyword])
    return False


def _build_parameters(
    type_: Any,
    location: ParameterLocation,
    components: dict[str, Schema],
    schema_hook: Optional[SchemaHook],
) -> list[OpenAPIParam]:
    """Build the parameters of one location, adding their definitions to `components`."""
    model = _parameter_model(_add_schema(type_, components, schema_hook), components)
    if _is_object_model(model):
        info = msgspec.inspect.type_info(type_)
        while isinstance(info, msgspec.inspect.Metadata):
            info = info.type
        tag_field = (
            info.tag_field if isinstance(info, msgspec.inspect.StructType) else None
        )
        if location == "path":
            # msgspec reports optional fields for defaults and optional TypedDict keys.
            optional_fields = (
                {field.encode_name for field in info.fields if not field.required}
                if isinstance(
                    info,
                    (
                        msgspec.inspect.StructType,
                        msgspec.inspect.DataclassType,
                        msgspec.inspect.NamedTupleType,
                        msgspec.inspect.TypedDictType,
                    ),
                )
                else set()
            )
            if optional_fields and isinstance(info, msgspec.inspect.TypedDictType):
                raise ValueError(
                    f"path_type TypedDict keys must be required: {', '.join(sorted(optional_fields))}. "
                    "URL placeholders must be supplied. Declare these keys with Required[...], "
                    "or use total=True and remove NotRequired[...]."
                )
            defaults = optional_fields | {
                name
                for name, field in model["properties"].items()
                if name != tag_field and _has_schema_default(field, components)
            }
            if defaults:
                raise ValueError(
                    f"path_type fields must not have defaults: {', '.join(sorted(defaults))}. "
                    "Remove the default, default_factory, or schema default from these fields. "
                    "URL placeholders must be supplied; for example, use 'id: int' "
                    "instead of 'id: int = 1'."
                )
        required = model.get("required", [])
        # Copy fields separately: hooks may reuse a schema dictionary.
        parameters = [
            OpenAPIParam(
                name=name,
                located_in=location,
                required=location == "path" or name in required,
                schema=deepcopy(field),
                description=(field.get("description") or msgspec.UNSET)
                if isinstance(field, dict)
                else msgspec.UNSET,
            )
            for name, field in model["properties"].items()
            if name != tag_field
        ]
    elif location == "path":
        raise ValueError(
            "path_type must be a model whose fields match the URL placeholders."
        )
    else:
        named = _scalar_parameter_type(type_)
        if named is None:
            raise ValueError(
                f"{location}_type has no parameter name; use a model with named "
                "fields or a named type such as an Enum or NewType."
            )
        description = (
            model.get("description") if isinstance(model, dict) else None
        ) or _own_doc(named)
        parameters = [
            OpenAPIParam(
                name=named.__name__,
                located_in=location,
                schema=deepcopy(model),
                description=description or msgspec.UNSET,
            )
        ]

    if location == "header":
        reserved = [
            param.name
            for param in parameters
            if param.name.lower() in _RESERVED_HEADERS
        ]
        if reserved:
            raise ValueError(
                f"Cannot define reserved header parameters: {', '.join(sorted(reserved))}. "
                "Use security schemes for Authorization and media types for "
                "Accept and Content-Type."
            )
    return parameters
