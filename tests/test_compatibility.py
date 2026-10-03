from __future__ import annotations

from dataclasses import dataclass, make_dataclass
from typing import Annotated, Literal, get_args

import msgspec
import pytest
from openapi_schema_validator import OAS31Validator
from openapi_spec_validator import OpenAPIV31SpecValidator

from defspec import OpenAPI, OpenAPIComponent, SecuritySchemeHTTP, SecuritySchemeOAuth2
from defspec.spec import (
    HTTP_METHODS,
    ClientCredentialsOAuthFlow,
    ImplicitOAuthFlow,
    OAuthFlow,
    OAuthFlowAuthorizationCode,
    ParameterLocation,
    PasswordOAuthFlow,
)


def valid_document(api):
    document = api.to_dict()
    OpenAPIV31SpecValidator(document).validate()
    assert msgspec.json.decode(api.to_json()) == document
    assert msgspec.json.decode(api.to_json(), type=OpenAPI).to_dict() == document
    return document


@pytest.mark.parametrize("method", get_args(HTTP_METHODS))
def test_bodyless_routes(method):
    api = OpenAPI()
    api.register_route("/health", method)
    document = valid_document(api)
    assert "$defs" not in document
    operation = document["paths"]["/health"][method]
    assert "requestBody" not in operation
    assert operation["responses"]["200"] == {"description": "OK"}
    assert "security" not in operation


@pytest.mark.parametrize("method", get_args(HTTP_METHODS))
def test_method_case_is_normalized_before_registration(method):
    api = OpenAPI()
    api.register_route("/health", method.upper())
    api.register_route("/health", method.capitalize(), summary="Updated")
    routes = valid_document(api)["paths"]["/health"]
    assert list(routes) == [method]
    assert routes[method]["operationId"] == f"_health_{method}"
    assert routes[method]["summary"] == "Updated"


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


@pytest.mark.parametrize(
    "type_", [Literal["a", "b"], list[int], Annotated[int, msgspec.Meta(ge=1)]]
)
def test_inline_parameter_schemas(type_):
    api = OpenAPI()
    api.register_route("/", "get", query_type=type_)
    valid_document(api)


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
@pytest.mark.parametrize("type_,alternative", [(int | str, "text"), (int | None, None)])
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
@pytest.mark.parametrize("minimum", [1, 10])
def test_parameter_model_siblings_preserve_constraints(location, minimum):
    class Parameters(msgspec.Struct):
        token: str
        limit: Annotated[int, msgspec.Meta(ge=5)] = 20

    constrained = Annotated[
        Parameters,
        msgspec.Meta(
            extra_json_schema={
                "properties": {
                    "limit": {
                        "minimum": minimum,
                        "maximum": 30,
                        "description": "Constrained limit",
                    }
                },
                "required": ["limit"],
            }
        ),
    ]
    api = OpenAPI()
    path = "/{token}/{limit}" if location == "path" else "/"
    api.register_route(
        path, "post", request_type=Parameters, **{f"{location}_type": constrained}
    )
    document = valid_document(api)
    token, limit = document["paths"][path]["post"]["parameters"]
    assert token["required"] is True
    assert limit["required"] is True
    assert limit["description"] == "Constrained limit"
    validator = OAS31Validator(limit["schema"])
    threshold = max(5, minimum)
    assert not validator.is_valid(threshold - 1)
    assert validator.is_valid(threshold)
    assert not validator.is_valid(31)
    assert not validator.is_valid("10")
    # Parameter annotations must not change the shared request body schema.
    model = document["components"]["schemas"]["Parameters"]
    assert model["required"] == ["token"]
    assert model["properties"]["limit"] == {
        "type": "integer",
        "minimum": 5,
        "default": 20,
    }
    api.register_route("/unconstrained", "get", query_type=Parameters)
    parameters = valid_document(api)["paths"]["/unconstrained"]["get"]["parameters"]
    assert parameters[1]["required"] is False
    assert "maximum" not in parameters[1]["schema"]


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
    assert parameter["description"] == ""


@pytest.mark.parametrize("field_schema", [True, False])
def test_boolean_sibling_constraints(field_schema):
    class Parameters(msgspec.Struct):
        value: int

    constrained = Annotated[
        Parameters,
        msgspec.Meta(extra_json_schema={"properties": {"value": field_schema}}),
    ]
    api = OpenAPI()
    api.register_route("/", "get", query_type=constrained)
    parameter = valid_document(api)["paths"]["/"]["get"]["parameters"][0]
    if field_schema:
        assert parameter["schema"] == {"type": "integer"}
    else:
        assert parameter["schema"] is False


@pytest.mark.parametrize(
    "constraints",
    [
        {"dependentRequired": {"first": ["second"]}},
        {"allOf": [{"required": ["first"]}]},
        {"type": "array"},
        {"properties": {"unknown": {"type": "string"}}},
        {"required": ["unknown"]},
    ],
)
def test_unrepresentable_parameter_siblings_are_rejected_atomically(constraints):
    class Parameters(msgspec.Struct):
        first: str = ""
        second: str = ""

    constrained = Annotated[Parameters, msgspec.Meta(extra_json_schema=constraints)]
    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match="parameter model"):
        api.register_route("/", "get", query_type=constrained)
    assert api.to_dict() == before


@pytest.mark.parametrize("location", get_args(ParameterLocation))
@pytest.mark.parametrize("referenced", [False, True])
@pytest.mark.parametrize(
    "constraints",
    [
        {"dependentRequired": {"first": ["second"]}},
        {"allOf": [{"required": ["first"]}]},
        {"additionalProperties": False},
        {
            "$id": "https://example.com/parameters",
            "$defs": {"Value": {"type": "string"}},
            "properties": {
                "first": {"$ref": "#/$defs/Value"},
                "second": {"type": "string"},
            },
        },
        {"required": ["unknown"]},
        {"$ref": "https://example.com/other"},
    ],
)
def test_unrepresentable_object_parameters_are_rejected_atomically(
    location, referenced, constraints
):
    class Parameters:
        pass

    model = {
        "type": "object",
        "properties": {
            "first": {"type": "string"},
            "second": {"type": "string"},
        },
        **constraints,
    }
    api = OpenAPI(
        components=OpenAPIComponent(schemas={"Parameters": model} if referenced else {})
    )

    def schema_hook(type_):
        assert type_ is Parameters
        return {"$ref": "#/components/schemas/Parameters"} if referenced else model

    api.register_route("/", "get")
    before = api.to_dict()
    path = "/{first}/{second}" if location == "path" else "/"
    with pytest.raises(ValueError, match="parameter model"):
        api.register_route(
            path, "get", schema_hook=schema_hook, **{f"{location}_type": Parameters}
        )
    assert api.to_dict() == before


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


class PathParameters(msgspec.Struct):
    user_id: int = msgspec.field(default=1, name="id")


def test_path_parameters_are_always_required():
    api = OpenAPI()
    api.register_route("/users/{id}", "get", path_type=PathParameters)
    parameters = valid_document(api)["paths"]["/users/{id}"]["get"]["parameters"]
    assert parameters[0]["name"] == "id"
    assert parameters[0]["in"] == "path"
    assert parameters[0]["required"] is True


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
    ],
)
def test_invalid_path_parameters_are_atomic(path, type_, message):
    api = OpenAPI()
    before = api.to_dict()
    with pytest.raises(ValueError, match=message):
        api.register_route(path, "get", path_type=type_)
    assert api.to_dict() == before


@pytest.mark.parametrize(
    "path,method",
    [
        ("/", "connect"),
        ("/", "CONNECT"),
        ("relative", "get"),
        ("/users/{id", "get"),
        ("/users/{}", "get"),
        ("/users/{{id}}", "get"),
        ("/users/{id}}", "get"),
        ("/users?x=1", "get"),
    ],
)
def test_invalid_routes(path, method):
    api = OpenAPI()
    with pytest.raises(ValueError):
        api.register_route(path, method)
    assert not api.paths


def test_equivalent_path_templates_are_rejected():
    @dataclass
    class OtherPath:
        name: int

    api = OpenAPI()
    api.register_route("/users/{id}", "get", path_type=PathParameters)
    with pytest.raises(ValueError, match="Equivalent path"):
        api.register_route("/users/{name}", "post", path_type=OtherPath)
    valid_document(api)


def test_operation_id_collisions_and_explicit_ids():
    api = OpenAPI()
    api.register_route("/a/b", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match="Duplicate operationId"):
        api.register_route("/a_b", "get")
    assert api.to_dict() == before
    api.register_route("/a_b", "get", operation_id="get_flat_ab")
    with pytest.raises(ValueError, match="Duplicate operationId"):
        api.register_route("/other", "post", operation_id="get_flat_ab")
    api.register_route("/a_b", "get", operation_id="get_flat_ab", summary="Updated")
    document = valid_document(api)
    assert document["paths"]["/a/b"]["get"]["operationId"] == "_a_b_get"
    assert document["paths"]["/a_b"]["get"]["operationId"] == "get_flat_ab"


def test_route_checks_use_current_paths_after_direct_edits():
    api = OpenAPI()
    api.register_route("/users/{id}", "get", path_type=PathParameters)
    routes = api.paths.pop("/users/{id}")
    routes["get"].parameters[0].name = "name"
    routes["get"].operation_id = "edited"
    api.paths["/users/{name}"] = routes
    before = valid_document(api)
    with pytest.raises(ValueError, match="Equivalent path"):
        api.register_route("/users/{id}", "post", path_type=PathParameters)
    with pytest.raises(ValueError, match="Duplicate operationId"):
        api.register_route("/other", "get", operation_id="edited")
    assert api.to_dict() == before
    api.paths.clear()
    api.register_route(
        "/users/{id}", "get", path_type=PathParameters, operation_id="edited"
    )
    valid_document(api)


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


def test_plain_paths_dict_preserves_other_methods_and_route_references():
    api = OpenAPI(paths={})
    api.register_route("/", "get")
    routes = api.paths["/"]
    api.register_route("/", "post")
    api.register_route("/", "GET", summary="Updated")
    assert api.paths["/"] is routes
    assert list(routes) == ["get", "post"]
    assert routes["get"].summary == "Updated"
    valid_document(api)


@pytest.mark.parametrize("same_route", [True, False])
def test_conflicting_models_are_rejected_without_mutation(same_route):
    first = make_dataclass("Payload", [("alpha", str)])
    second = make_dataclass("Payload", [("beta", int)])
    first.__module__ = "first"
    second.__module__ = "second"
    api = OpenAPI()
    if not same_route:
        api.register_route("/first", "post", request_type=first)
    before = api.to_dict()
    with pytest.raises(ValueError, match="Conflicting schema name"):
        api.register_route("/second", "post", request_type=first, response_type=second)
    assert api.to_dict() == before
    valid_document(api)


def test_existing_components_are_not_overwritten():
    api = OpenAPI(
        components=OpenAPIComponent(schemas={"PathParameters": {"type": "string"}})
    )
    before = api.to_dict()
    with pytest.raises(ValueError, match="Conflicting schema name"):
        api.register_route("/", "post", request_type=PathParameters)
    assert api.to_dict() == before


class Node(msgspec.Struct):
    children: list[Node] = msgspec.field(default_factory=list)


class Cat(msgspec.Struct, tag=True):
    name: str


class Dog(msgspec.Struct, tag=True):
    age: int


def test_recursive_shared_and_discriminated_schemas():
    api = OpenAPI()
    api.register_route("/tree", "post", request_type=Node, response_type=Node)
    api.register_route("/pets", "post", request_type=Cat | Dog, response_type=Cat | Dog)
    api.register_route("/tree-copy", "get", response_type=Node)
    document = valid_document(api)
    schemas = document["components"]["schemas"]
    assert schemas["Node"]["properties"]["children"]["items"] == {
        "$ref": "#/components/schemas/Node"
    }
    pet_schema = document["paths"]["/pets"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert pet_schema["discriminator"]["mapping"] == {
        "Cat": "#/components/schemas/Cat",
        "Dog": "#/components/schemas/Dog",
    }
    assert api.defs is api.components.schemas


@pytest.mark.parametrize(
    "field,flow",
    [
        ("implicit", ImplicitOAuthFlow("https://example.com/auth")),
        ("password", PasswordOAuthFlow("https://example.com/token")),
        ("client_credentials", ClientCredentialsOAuthFlow("https://example.com/token")),
        (
            "authorization_code",
            OAuthFlowAuthorizationCode(
                "https://example.com/auth", "https://example.com/token"
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    "refresh_url", [msgspec.UNSET, None, "https://example.com/refresh"]
)
def test_oauth_optional_fields_and_required_scopes(field, flow, refresh_url):
    flow = type(flow)(**(msgspec.structs.asdict(flow) | {"refresh_url": refresh_url}))
    api = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={"oauth": SecuritySchemeOAuth2(OAuthFlow(**{field: flow}))}
        )
    )
    flows = valid_document(api)["components"]["securitySchemes"]["oauth"]["flows"]
    assert len(flows) == 1
    serialized = next(iter(flows.values()))
    assert serialized["scopes"] == {}
    if isinstance(refresh_url, str):
        assert serialized["refreshUrl"] == refresh_url
    else:
        assert "refreshUrl" not in serialized


def test_oauth_requires_a_flow():
    with pytest.raises(ValueError, match="At least one"):
        OAuthFlow()


def test_operation_security_overrides():
    api = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={"token": SecuritySchemeHTTP("bearer")}
        ),
        security=[{"token": []}],
    )
    api.register_route("/inherited", "get")
    api.register_route("/public", "get", security=[])
    api.register_route("/explicit", "get", security=[{"token": []}])
    paths = valid_document(api)["paths"]
    assert "security" not in paths["/inherited"]["get"]
    assert paths["/public"]["get"]["security"] == []
    assert paths["/explicit"]["get"]["security"] == [{"token": []}]
    api.paths["/explicit"]["get"].security = []
    assert valid_document(api)["paths"]["/explicit"]["get"]["security"] == []


@pytest.mark.parametrize("type_", [type(None), str | None])
def test_explicit_null_bodies(type_):
    api = OpenAPI()
    api.register_route("/", "post", request_type=type_, response_type=type_)
    operation = valid_document(api)["paths"]["/"]["post"]
    assert "application/json" in operation["requestBody"]["content"]
    assert "application/json" in operation["responses"]["200"]["content"]


@pytest.mark.parametrize("version", ["3.0.3", "3.2.0", "2.0", "3.1.invalid"])
def test_unsupported_versions(version):
    with pytest.raises(ValueError, match="3.1.x"):
        OpenAPI(openapi=version)


def test_patch_version_and_registration_after_decode():
    api = msgspec.json.decode(OpenAPI(openapi="3.1.1").to_json(), type=OpenAPI)
    api.register_route("/", "get")
    valid_document(api)
