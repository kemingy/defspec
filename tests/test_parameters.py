from __future__ import annotations

import datetime
import enum
import sys
import uuid
from typing import Annotated, Literal, NewType, Optional, Union, get_args

import msgspec
import pytest
from openapi_schema_validator import OAS31Validator

from defspec import OpenAPI, OpenAPIComponent
from defspec.spec import ParameterLocation
from tests.helpers import PathParameters, valid_document


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
def test_parameter_defaults_and_encoded_names(location):
    default_limit = 10

    class Parameters(msgspec.Struct):
        api_key: Annotated[str, msgspec.Meta(description="API key")] = msgspec.field(
            name="X-API-Key"
        )
        limit: int = default_limit

    api = OpenAPI()
    api.register_route("/", "get", **{f"{location}_type": Parameters})
    parameters = valid_document(api)["paths"]["/"]["get"]["parameters"]
    assert [param["name"] for param in parameters] == ["X-API-Key", "limit"]
    assert [param["required"] for param in parameters] == [True, False]
    assert all(param["in"] == location for param in parameters)
    assert parameters[0]["description"] == "API key"
    assert parameters[1]["schema"]["default"] == default_limit


class Color(enum.Enum):
    """Preferred color."""

    RED = "red"


class Undocumented(enum.Enum):
    RED = "red"


UserId = NewType("UserId", int)


class Token:
    """Opaque access token."""


@pytest.mark.parametrize(
    "type_,name,description",
    [
        pytest.param(Color, "Color", "Preferred color.", id="enum"),
        pytest.param(Undocumented, "Undocumented", None, id="undocumented-enum"),
        pytest.param(UserId, "UserId", None, id="newtype"),
        pytest.param(
            Annotated[UserId, msgspec.Meta(ge=1, description="User ID")],
            "UserId",
            "User ID",
            id="annotated-newtype",
        ),
        pytest.param(Token, "Token", "Opaque access token.", id="hook-class"),
    ],
)
def test_user_defined_scalar_parameters(type_, name, description):
    api = OpenAPI()
    api.register_route(
        "/", "get", query_type=type_, schema_hook=lambda _: {"type": "string"}
    )
    (parameter,) = valid_document(api)["paths"]["/"]["get"]["parameters"]
    assert parameter["name"] == name
    assert parameter.get("description") == description


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Python 3.10 uses this text as an automatic enum docstring",
)
def test_explicit_enum_docstring_matching_old_placeholder_is_preserved():
    class Documented(enum.Enum):
        """An enumeration."""

        RED = "red"

    api = OpenAPI()
    api.register_route("/", "get", query_type=Documented)
    (parameter,) = valid_document(api)["paths"]["/"]["get"]["parameters"]
    assert parameter["description"] == "An enumeration."


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
@pytest.mark.parametrize(
    "type_,name,schema",
    [
        (int, "int", {"type": "integer"}),
        (str, "str", {"type": "string"}),
        (datetime.datetime, "datetime", {"type": "string"}),
        (uuid.UUID, "UUID", {"type": "string", "format": "uuid"}),
        (Annotated[int, msgspec.Meta(ge=1)], "int", {"type": "integer", "minimum": 1}),
    ],
)
def test_named_builtin_and_stdlib_scalar_parameters(location, type_, name, schema):
    api = OpenAPI()
    api.register_route("/", "get", **{f"{location}_type": type_})
    (parameter,) = valid_document(api)["paths"]["/"]["get"]["parameters"]
    assert parameter["name"] == name
    assert parameter["in"] == location
    assert parameter["required"] is True
    assert parameter["schema"] == schema


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
@pytest.mark.parametrize(
    "type_",
    [
        list[int],
        dict[str, int],
        Literal["a", "b"],
        Annotated[int | str, msgspec.Meta(description="Value")],
    ],
)
def test_unnamed_typing_parameters_are_rejected_atomically(location, type_):
    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match=f"{location}_type has no parameter name"):
        api.register_route("/", "get", **{f"{location}_type": type_})
    assert api.to_dict() == before


@pytest.mark.parametrize("module", ["test", "email", "code"])
@pytest.mark.parametrize("type_", [Color, UserId])
def test_scalar_parameter_names_are_independent_of_module_names(
    monkeypatch, module, type_
):
    monkeypatch.setattr(type_, "__module__", module)
    api = OpenAPI()
    api.register_route("/", "get", query_type=type_)
    (parameter,) = valid_document(api)["paths"]["/"]["get"]["parameters"]
    assert parameter["name"] == type_.__name__


@pytest.mark.parametrize("location", get_args(ParameterLocation))
@pytest.mark.parametrize("wrapper", ["plain", "annotated", "newtype"])
@pytest.mark.parametrize("tag,tag_field", [(True, "type"), (0, "kind")])
def test_tagged_parameter_models_omit_only_the_generated_tag(
    location, wrapper, tag, tag_field
):
    class Parameters(
        msgspec.Struct, tag=tag, tag_field=tag_field, forbid_unknown_fields=True
    ):
        value: int = msgspec.field(name="id", default=1)

    type_ = (
        Annotated[Parameters, msgspec.Meta(description="Parameter model")]
        if wrapper == "annotated"
        else NewType("ParameterAlias", Parameters)
        if wrapper == "newtype"
        else Parameters
    )
    api = OpenAPI()
    path = "/{id}" if location == "path" else "/"
    api.register_route(
        path,
        "post",
        request_type=Parameters,
        response_type=Parameters,
        **{f"{location}_type": type_},
    )
    document = valid_document(api)
    (parameter,) = document["paths"][path]["post"]["parameters"]
    assert parameter["name"] == "id"
    assert parameter["required"] is (location == "path")
    component = document["components"]["schemas"]["Parameters"]
    assert tag_field in component["properties"]
    assert component["properties"][tag_field]["enum"] == [
        Parameters.__struct_config__.tag
    ]
    assert component["required"] == [tag_field]
    assert msgspec.convert({"id": 2}, type=type_) == Parameters(value=2)


def test_normal_fields_named_type_and_nested_struct_tags_are_preserved():
    class Payload(msgspec.Struct, tag=True):
        value: int

    Query = msgspec.defstruct(
        "Query", [("type", Literal["user"]), ("payload", Payload)]
    )

    api = OpenAPI()
    api.register_route("/", "get", query_type=Query)
    document = valid_document(api)
    type_, payload = document["paths"]["/"]["get"]["parameters"]
    assert type_["name"] == "type"
    assert type_["required"] is True
    assert type_["schema"]["enum"] == ["user"]
    assert payload["name"] == "payload"
    assert payload["schema"] == {"$ref": "#/components/schemas/Payload"}
    assert document["components"]["schemas"]["Payload"]["required"] == ["type", "value"]


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
@pytest.mark.parametrize(
    "type_,alternative",
    [
        pytest.param(int | str, "text", id="pep604-union"),
        pytest.param(Union[int, str], "text", id="typing-union"),
        pytest.param(int | None, None, id="pep604-optional"),
        pytest.param(Optional[int], None, id="typing-optional"),
    ],
)
def test_unnamed_scalar_parameters_are_rejected_atomically(
    location, type_, alternative
):
    class Payload(msgspec.Struct):
        value: int

    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(
        ValueError,
        match=f"{location}_type has no parameter name; use a model with named fields",
    ):
        api.register_route(
            "/", "get", request_type=Payload, **{f"{location}_type": type_}
        )
    assert api.to_dict() == before

    parameters = msgspec.defstruct("Parameters", [("value", type_)])
    api.register_route("/", "get", **{f"{location}_type": parameters})
    parameter = valid_document(api)["paths"]["/"]["get"]["parameters"][0]
    assert parameter["name"] == "value"
    assert parameter["in"] == location
    validator = OAS31Validator(parameter["schema"])
    assert validator.is_valid(1)
    assert validator.is_valid(alternative)
    assert not validator.is_valid([])


@pytest.mark.parametrize("location", get_args(ParameterLocation))
@pytest.mark.parametrize("field_schema", [True, False])
def test_boolean_parameter_schemas(location, field_schema):
    class Parameters:
        pass

    def schema_hook(type_):
        assert type_ is Parameters
        return {
            "type": "object",
            "properties": {"payload": field_schema},
            "required": ["payload"],
        }

    api = OpenAPI()
    path = "/{payload}" if location == "path" else "/"
    api.register_route(
        path, "get", schema_hook=schema_hook, **{f"{location}_type": Parameters}
    )
    parameter = valid_document(api)["paths"][path]["get"]["parameters"][0]
    assert parameter["schema"] is field_schema
    assert "description" not in parameter


def test_boolean_parameter_type_schema() -> None:
    class Parameters:
        pass

    def schema_hook(type_: type) -> bool:
        return True

    api = OpenAPI()
    api.register_route("/", "get", query_type=Parameters, schema_hook=schema_hook)
    parameter = valid_document(api)["paths"]["/"]["get"]["parameters"][0]
    assert parameter["name"] == "Parameters"
    assert parameter["schema"] is True


@pytest.mark.parametrize("location", get_args(ParameterLocation))
@pytest.mark.parametrize("component_schema", [True, False])
def test_boolean_component_parameter_schema(location, component_schema):
    class Parameters:
        pass

    api = OpenAPI(components=OpenAPIComponent(schemas={"Parameters": component_schema}))
    if location == "path":
        with pytest.raises(ValueError, match="path_type must be a model"):
            api.register_route(
                "/{value}",
                "get",
                schema_hook=lambda _: {"$ref": "#/components/schemas/Parameters"},
                path_type=Parameters,
            )
        assert not api.paths
    else:
        api.register_route(
            "/",
            "get",
            schema_hook=lambda _: {"$ref": "#/components/schemas/Parameters"},
            **{f"{location}_type": Parameters},
        )
        parameter = valid_document(api)["paths"]["/"]["get"]["parameters"][0]
        assert parameter["schema"] == {"$ref": "#/components/schemas/Parameters"}


@pytest.mark.parametrize("constrained", [False, True])
def test_parameter_schema_edits_do_not_change_components_or_other_parameters(
    constrained,
):
    class Parameters(msgspec.Struct):
        value: Annotated[int, msgspec.Meta(ge=0)]
        items: list[int]

    type_ = (
        Annotated[
            Parameters,
            msgspec.Meta(
                extra_json_schema={
                    "properties": {
                        "value": {"maximum": 10},
                        "items": {"maxItems": 2},
                    }
                }
            ),
        ]
        if constrained
        else Parameters
    )
    api = OpenAPI()
    api.register_route(
        "/", "post", request_type=Parameters, query_type=type_, header_type=type_
    )
    before = valid_document(api)
    # Header parameters come last and previously shared the current component.
    value, items = api.paths["/"]["post"].parameters[2:]
    assert isinstance(value.schema, dict)
    assert isinstance(items.schema, dict)
    value_schema = value.schema["allOf"][0] if constrained else value.schema
    items_schema = items.schema["allOf"][0] if constrained else items.schema
    value_schema["minimum"] = 3
    items_schema["items"]["minimum"] = 5
    after = valid_document(api)
    assert after["components"] == before["components"]
    assert (
        after["paths"]["/"]["post"]["parameters"][:2]
        == before["paths"]["/"]["post"]["parameters"][:2]
    )
    # The original model remains reusable after a parameter is customized.
    api.register_route("/other", "get", query_type=Parameters)
    assert valid_document(api)["components"] == before["components"]


def test_inline_parameter_fields_do_not_share_hook_schema_dictionaries():
    class Parameters:
        pass

    field = {"type": "array", "items": {"type": "integer"}}
    model = {"type": "object", "properties": {"first": field, "second": field}}
    api = OpenAPI()
    api.register_route("/", "get", query_type=Parameters, schema_hook=lambda _: model)
    first, second = api.paths["/"]["get"].parameters
    assert isinstance(first.schema, dict)
    assert isinstance(second.schema, dict)
    first.schema["items"]["minimum"] = 1
    assert second.schema == {"type": "array", "items": {"type": "integer"}}
    assert field == second.schema
    valid_document(api)


@pytest.mark.parametrize(
    "name",
    [
        "Accept",
        "accept",
        "Content-Type",
        "cOnTeNt-TyPe",
        "Authorization",
        "authorization",
    ],
)
@pytest.mark.parametrize("source", ["model", "inline", "scalar"])
def test_reserved_header_names_are_rejected_atomically(name, source):
    class Headers(msgspec.Struct):
        value: str = msgspec.field(name=name)

    class CustomHeaders:
        pass

    if source == "model":
        type_ = Headers
    elif source == "inline":
        type_ = CustomHeaders
    else:
        type_ = type(name, (), {})

    def schema_hook(cls):
        assert cls is type_
        if source == "scalar":
            return {"type": "string"}
        return {"type": "object", "properties": {name: {"type": "string"}}}

    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match="reserved header"):
        api.register_route("/", "get", header_type=type_, schema_hook=schema_hook)
    assert api.to_dict() == before


def test_path_parameters_are_always_required():
    api = OpenAPI()
    api.register_route("/users/{id}", "get", path_type=PathParameters)
    parameters = valid_document(api)["paths"]["/users/{id}"]["get"]["parameters"]
    assert parameters[0]["name"] == "id"
    assert parameters[0]["in"] == "path"
    assert parameters[0]["required"] is True


@pytest.mark.parametrize("type_,default", [(int, 1), (Optional[int], None)])
def test_path_defaults_are_omitted_only_from_parameter_schemas(type_, default):
    model = msgspec.defstruct("Path", [("id", type_, default)])
    api = OpenAPI()
    api.register_route(
        "/users/{id}",
        "post",
        request_type=model,
        response_type=model,
        query_type=model,
        header_type=model,
        cookie_type=model,
        path_type=model,
    )
    document = valid_document(api)
    query, header, cookie, path = document["paths"]["/users/{id}"]["post"]["parameters"]
    assert path["required"] is True
    original = document["components"]["schemas"]["Path"]["properties"]["id"]
    for parameter in (query, header, cookie):
        assert parameter["required"] is False
        assert parameter["schema"] == original
    expected = original.copy()
    expected.pop("default")
    assert path["schema"] == expected
    assert original["default"] == default
    assert model().id == default
    assert OAS31Validator(path["schema"]).is_valid(default)


def test_path_defaults_are_omitted_from_intersected_constraints():
    default = 5
    model = msgspec.defstruct("Path", [("id", int, default)])
    constrained = Annotated[
        model,
        msgspec.Meta(
            extra_json_schema={"properties": {"id": {"minimum": 2, "default": 3}}}
        ),
    ]
    api = OpenAPI()
    api.register_route(
        "/{id}",
        "get",
        request_type=model,
        query_type=constrained,
        path_type=constrained,
    )
    document = valid_document(api)
    query, path = document["paths"]["/{id}"]["get"]["parameters"]
    assert query["schema"]["allOf"] == [
        {"type": "integer", "default": default},
        {"minimum": 2, "default": 3},
    ]
    assert path["schema"]["allOf"] == [{"type": "integer"}, {"minimum": 2}]
    assert path["required"] is True
    assert (
        document["components"]["schemas"]["Path"]["properties"]["id"]["default"]
        == default
    )
    validator = OAS31Validator(path["schema"])
    assert validator.is_valid(2)
    assert not validator.is_valid(1)


def test_path_default_removal_preserves_defaults_inside_nested_values():
    default = 5
    nested = msgspec.defstruct("Nested", [("value", int, default)], frozen=True)
    model = msgspec.defstruct("Path", [("id", nested, nested())])
    api = OpenAPI()
    api.register_route(
        "/{id}", "get", request_type=model, query_type=model, path_type=model
    )
    document = valid_document(api)
    query, path = document["paths"]["/{id}"]["get"]["parameters"]
    assert query["schema"]["default"] == {"value": default}
    assert path["schema"] == {"$ref": "#/components/schemas/Nested"}
    assert (
        document["components"]["schemas"]["Nested"]["properties"]["value"]["default"]
        == default
    )


@pytest.mark.parametrize(
    "keyword", ["allOf", "anyOf", "oneOf", "if", "then", "else", "not"]
)
def test_path_defaults_are_omitted_without_changing_nested_schemas_or_literal_data(
    keyword,
):
    class Parameters:
        pass

    nested = {
        "properties": {"default": {"type": "integer", "default": 1}},
        "items": {"type": "integer", "default": 1},
        "enum": [{"default": 1}],
        "const": {"default": 1},
        "examples": [{"default": 1}],
    }
    child = {"default": {"default": 1}, **nested}
    field = {
        "default": {"default": 2 if keyword == "not" else 1},
        keyword: [child] if keyword in ("allOf", "anyOf", "oneOf") else child,
    }
    model = {"type": "object", "properties": {"id": field}}
    api = OpenAPI()
    api.register_route(
        "/{id}",
        "get",
        query_type=Parameters,
        path_type=Parameters,
        schema_hook=lambda _: model,
    )
    query, path = valid_document(api)["paths"]["/{id}"]["get"]["parameters"]
    assert query["schema"] == field
    assert path["schema"] == {
        keyword: [nested] if keyword in ("allOf", "anyOf", "oneOf") else nested
    }
    assert child["default"] == {"default": 1}


def test_missing_path_model_error_explains_how_to_supply_it():
    api = OpenAPI()
    with pytest.raises(ValueError) as error:
        api.register_route("/users/{id}", "get")
    message = str(error.value)
    assert "'/users/{id}' needs path_type with fields named: id" in message
    assert "class PathParams(msgspec.Struct): id: int" in message
    assert "path_type=PathParams" in message
    assert not api.paths


@pytest.mark.parametrize(
    "path,details",
    [
        ("/users/{name}", "missing fields: name; unexpected fields: id"),
        ("/users/{id}/{name}", "missing fields: name"),
        ("/users", "unexpected fields: id"),
    ],
)
def test_mismatched_path_model_error_names_the_fields_to_fix(path, details):
    api = OpenAPI()
    with pytest.raises(ValueError) as error:
        api.register_route(path, "get", path_type=PathParameters)
    assert details in str(error.value)
    assert "msgspec.field(name=...)" in str(error.value)
    assert not api.paths


@pytest.mark.parametrize(
    "path,type_,message",
    [
        ("/users/{id}", None, "path_type"),
        ("/users/{name}", PathParameters, "path_type"),
        ("/users", PathParameters, "path_type"),
        (
            "/users/{id}",
            int,
            "path_type must be a model whose fields match the URL placeholders",
        ),
        (
            "/users/{int}",
            int,
            "path_type must be a model whose fields match the URL placeholders",
        ),
        (
            "/users/{Union}",
            int | str,
            "path_type must be a model whose fields match the URL placeholders",
        ),
    ],
)
def test_invalid_path_parameters_are_atomic(path, type_, message):
    api = OpenAPI()
    before = api.to_dict()
    with pytest.raises(ValueError, match=message):
        api.register_route(path, "get", path_type=type_)
    assert api.to_dict() == before


@pytest.mark.parametrize("schema", [True, {"type": "integer"}])
def test_scalar_path_hook_is_rejected_when_name_matches_placeholder(schema):
    class Value:
        pass

    calls = []

    def schema_hook(type_):
        calls.append(type_)
        return schema

    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match="path_type must be a model"):
        api.register_route(
            "/users/{Value}",
            "get",
            request_type=PathParameters,
            path_type=Value,
            schema_hook=schema_hook,
        )
    assert calls == [Value]
    assert api.to_dict() == before


def test_adjacent_path_placeholders_are_preserved():
    class FilePath(msgspec.Struct):
        name: str
        extension: str

    api = OpenAPI()
    api.register_route("/files/{name}.{extension}", "get", path_type=FilePath)
    parameters = valid_document(api)["paths"]["/files/{name}.{extension}"]["get"][
        "parameters"
    ]
    assert [param["name"] for param in parameters] == ["name", "extension"]
