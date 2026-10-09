from copy import deepcopy
from typing import Literal

import msgspec
import pytest
from jsonschema.exceptions import SchemaError

from defspec import OpenAPI, OpenAPIComponent, SecuritySchemeOAuth2
from defspec.models import OpenAPIRequestBody
from defspec.spec import ImplicitOAuthFlow, OAuthFlow
from tests import helpers


@pytest.fixture
def snapshot_path(tmp_path, monkeypatch):
    monkeypatch.setattr(helpers, "_SNAPSHOTS", tmp_path)
    return tmp_path / "document.json"


@pytest.mark.parametrize("method", ["post", "query"])
def test_document_validation_checks_schema_objects(method):
    api = OpenAPI()
    api.register_route("/search", "post", request_type=str)
    api.register_route("/search", "query", request_type=int)
    helpers.valid_document(api)
    body = api.paths["/search"][method].request_body
    assert isinstance(body, OpenAPIRequestBody)
    body.content["application/json"]["schema"] = {"type": "invalid"}
    with pytest.raises(SchemaError):
        helpers.valid_document(api)


@pytest.mark.parametrize("referenced", [False, True])
def test_snapshot_ignores_required_and_enum_order(snapshot_path, referenced):
    class Payload(msgspec.Struct):
        choice: Literal["red", "blue"]
        count: int

    class Custom:
        pass

    model = msgspec.json.schema_components((Payload,))[1]["Payload"]
    model.pop("title")
    type_ = Payload if referenced else Custom
    api = OpenAPI()
    api.register_route(
        "/",
        "post",
        request_type=type_,
        response_type=type_,
        query_type=type_,
        schema_hook=lambda _: deepcopy(model),
    )
    snapshot_path.write_bytes(api.to_json())
    if referenced:
        schemas = [api.components.schemas["Payload"]]
    else:
        operation = api.paths["/"]["post"]
        assert isinstance(operation.request_body, OpenAPIRequestBody)
        schemas = [
            operation.request_body.content["application/json"]["schema"],
            operation.responses["200"].content["application/json"]["schema"],
        ]
    for schema in schemas:
        schema["required"].reverse()
        schema["properties"]["choice"]["enum"].reverse()
    api.paths["/"]["post"].parameters[0].schema["enum"].reverse()
    before = api.to_dict()
    helpers.assert_snapshot(api, "document")
    assert api.to_dict() == before


def test_snapshot_accepts_mixed_enum_values(snapshot_path):
    class Payload:
        pass

    schema = {"enum": [None, False, 1, "red", {"first": 1, "second": 2}, [1, 2]]}
    api = OpenAPI()
    api.register_route("/", "post", request_type=Payload, schema_hook=lambda _: schema)
    snapshot_path.write_bytes(api.to_json())
    schema["enum"].reverse()
    schema["enum"][1] = {"second": 2, "first": 1}
    helpers.assert_snapshot(api, "document")


@pytest.mark.parametrize("keyword", ["required", "enum"])
def test_snapshot_detects_changed_required_and_enum_values(snapshot_path, keyword):
    class Payload:
        pass

    schema = {
        "type": "object",
        "properties": {"name": {"enum": ["red", "blue"]}},
        "required": ["name"],
    }
    api = OpenAPI()
    api.register_route("/", "post", request_type=Payload, schema_hook=lambda _: schema)
    snapshot_path.write_bytes(api.to_json())
    values = (
        schema["required"]
        if keyword == "required"
        else schema["properties"]["name"]["enum"]
    )
    values.pop()
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")


@pytest.mark.parametrize("keyword", ["const", "default", "enum", "examples"])
def test_snapshot_preserves_literal_value_array_order(snapshot_path, keyword):
    class Payload:
        pass

    literal = {"required": ["first", "second"], "enum": ["red", "blue"]}
    schema = {keyword: [literal] if keyword in ("enum", "examples") else literal}
    api = OpenAPI()
    api.register_route("/", "post", request_type=Payload, schema_hook=lambda _: schema)
    snapshot_path.write_bytes(api.to_json())
    literal["required"].reverse()
    literal["enum"].reverse()
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")


def test_snapshot_preserves_parameter_order(snapshot_path):
    class Query(msgspec.Struct):
        first: str
        second: str

    api = OpenAPI()
    api.register_route("/", "get", query_type=Query)
    snapshot_path.write_bytes(api.to_json())
    api.paths["/"]["get"].parameters.reverse()
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")


def test_snapshot_preserves_tuple_item_order(snapshot_path):
    api = OpenAPI()
    api.register_route("/", "post", request_type=tuple[str, int])
    snapshot_path.write_bytes(api.to_json())
    body = api.paths["/"]["post"].request_body
    assert isinstance(body, OpenAPIRequestBody)
    schema = body.content["application/json"]["schema"]
    schema["prefixItems"].reverse()
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")


def test_snapshot_preserves_media_example_array_order(snapshot_path):
    api = OpenAPI()
    api.register_route("/", "post", request_type=dict)
    body = api.paths["/"]["post"].request_body
    assert isinstance(body, OpenAPIRequestBody)
    media = body.content["application/json"]
    media["example"] = {"schema": {"required": ["first", "second"]}}
    snapshot_path.write_bytes(api.to_json())
    media["example"]["schema"]["required"].reverse()
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")


def test_snapshot_accepts_schema_keywords_as_oauth_scope_names(snapshot_path):
    api = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={
                "oauth": SecuritySchemeOAuth2(
                    OAuthFlow(
                        implicit=ImplicitOAuthFlow(
                            "https://example.com/auth",
                            scopes={
                                "schema": "Read a schema",
                                "schemas": "Read schemas",
                            },
                        )
                    )
                )
            }
        )
    )
    snapshot_path.write_bytes(api.to_json())
    helpers.assert_snapshot(api, "document")


@pytest.mark.parametrize("name", ["schema", "schemas", "example", "x-header"])
@pytest.mark.parametrize("use_content", [False, True])
def test_snapshot_normalizes_encoding_header_schemas_only(
    snapshot_path, name, use_content
):
    class Payload:
        pass

    api = OpenAPI()
    api.register_route(
        "/",
        "post",
        request_type=Payload,
        request_content_type="multipart/form-data",
        schema_hook=lambda _: {
            "type": "object",
            "properties": {"part": {"type": "string"}},
        },
    )
    schema = {
        "type": "object",
        "properties": {
            "first": {"enum": ["red", "blue"]},
            "second": {"type": "string"},
        },
        "required": ["first", "second"],
    }
    literal = {"required": ["first", "second"]}
    header = (
        {"content": {"application/json": {"schema": schema, "example": literal}}}
        if use_content
        else {"schema": schema, "example": literal}
    )
    body = api.paths["/"]["post"].request_body
    assert isinstance(body, OpenAPIRequestBody)
    body.content["multipart/form-data"]["encoding"] = {
        "part": {"headers": {name: header}}
    }
    snapshot_path.write_bytes(api.to_json())
    schema["required"].reverse()
    schema["properties"]["first"]["enum"].reverse()
    helpers.assert_snapshot(api, "document")
    literal["required"].reverse()
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")


@pytest.mark.parametrize(
    "keyword,original,replacement",
    [
        ("enum", [1], [True]),
        ("enum", [0], [False]),
        ("const", 1, True),
        ("default", 0, False),
        ("examples", [1], [True]),
    ],
)
def test_snapshot_distinguishes_booleans_from_numbers(
    snapshot_path, keyword, original, replacement
):
    class Payload:
        pass

    schema = {keyword: original}
    api = OpenAPI()
    api.register_route("/", "post", request_type=Payload, schema_hook=lambda _: schema)
    snapshot_path.write_bytes(api.to_json())
    schema[keyword] = replacement
    with pytest.raises(AssertionError):
        helpers.assert_snapshot(api, "document")
