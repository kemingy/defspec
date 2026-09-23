from __future__ import annotations

from dataclasses import dataclass, make_dataclass
from typing import Annotated, Literal, cast

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
    PasswordOAuthFlow,
)


def valid_document(api):
    document = api.to_dict()
    OpenAPIV31SpecValidator(document).validate()
    assert msgspec.json.decode(api.to_json()) == document
    assert msgspec.json.decode(api.to_json(), type=OpenAPI).to_dict() == document
    return document


@pytest.mark.parametrize(
    "method", ["get", "post", "put", "delete", "head", "options", "trace", "patch"]
)
def test_bodyless_routes(method):
    api = OpenAPI()
    api.register_route("/health", method)
    document = valid_document(api)
    assert "$defs" not in document
    operation = document["paths"]["/health"][method]
    assert "requestBody" not in operation
    assert operation["responses"]["200"] == {"description": "OK"}
    assert "security" not in operation


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


@pytest.mark.parametrize("location", ["query", "header", "cookie", "path"])
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


@pytest.mark.parametrize("location", ["query", "header", "cookie", "path"])
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
    "path,type_",
    [
        ("/users/{id}", None),
        ("/users/{name}", PathParameters),
        ("/users", PathParameters),
        ("/users/{id}", int),
    ],
)
def test_invalid_path_parameters_are_atomic(path, type_):
    api = OpenAPI()
    before = api.to_dict()
    with pytest.raises(ValueError, match="path_type"):
        api.register_route(path, "get", path_type=type_)
    assert api.to_dict() == before


@pytest.mark.parametrize(
    "path,method",
    [
        ("/", "connect"),
        ("/", "GET"),
        ("relative", "get"),
        ("/users/{id", "get"),
        ("/users/{}", "get"),
        ("/users?x=1", "get"),
    ],
)
def test_invalid_routes(path, method):
    api = OpenAPI()
    with pytest.raises(ValueError):
        api.register_route(path, cast(HTTP_METHODS, method))
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
