from __future__ import annotations

from typing import Annotated, get_args

import msgspec
import pytest
from openapi_schema_validator import OAS31Validator

from defspec import OpenAPI, OpenAPIComponent
from defspec.spec import ParameterLocation
from tests.helpers import valid_document


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
@pytest.mark.parametrize("source", ["native", "inline", "reference"])
@pytest.mark.parametrize(
    "meta",
    [
        msgspec.Meta(description="Model-level description"),
        msgspec.Meta(title="Model-level title"),
        msgspec.Meta(extra_json_schema={"description": "Model-level description"}),
        msgspec.Meta(extra_json_schema={"title": "Model-level title"}),
    ],
)
def test_model_metadata_is_ignored(location, source, meta):
    class Parameters(msgspec.Struct):
        value: int

    class Custom:
        pass

    model = {
        "type": "object",
        "title": "Custom",
        "description": "Inline model description",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }
    api = OpenAPI()
    if source == "reference":
        api.components.schemas["Custom"] = model
    type_ = Parameters if source == "native" else Custom
    schema = {"$ref": "#/components/schemas/Custom"} if source == "reference" else model
    path = "/{value}" if location == "path" else "/"
    api.register_route(
        path,
        "get",
        request_type=Parameters,
        schema_hook=lambda _: schema,
        **{f"{location}_type": Annotated[type_, meta]},
    )
    parameters = valid_document(api)["paths"][path]["get"]["parameters"]
    assert parameters == [
        {
            "name": "value",
            "in": location,
            "required": True,
            "schema": {"type": "integer"},
        }
    ]


@pytest.mark.parametrize("location", get_args(ParameterLocation))
def test_forbid_unknown_fields_model_is_expanded(location):
    class Parameters(msgspec.Struct, forbid_unknown_fields=True):
        value: int

    api = OpenAPI()
    path = "/{value}" if location == "path" else "/"
    api.register_route(path, "get", **{f"{location}_type": Parameters})
    parameters = valid_document(api)["paths"][path]["get"]["parameters"]
    assert [param["name"] for param in parameters] == ["value"]


@pytest.mark.parametrize("location", get_args(ParameterLocation))
@pytest.mark.parametrize("properties", [None, {}, {"token": {}}])
def test_closed_sibling_schema_restricting_model_fields_is_rejected_atomically(
    location, properties
):
    class Parameters(msgspec.Struct):
        token: str
        limit: int = 20

    constraints = {"additionalProperties": False}
    if properties is not None:
        constraints["properties"] = properties
    constrained = Annotated[Parameters, msgspec.Meta(extra_json_schema=constraints)]
    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    path = "/{token}/{limit}" if location == "path" else "/"
    with pytest.raises(
        ValueError, match="parameter model constraints: additionalProperties"
    ):
        api.register_route(
            path, "get", request_type=Parameters, **{f"{location}_type": constrained}
        )
    assert api.to_dict() == before


@pytest.mark.parametrize("location", get_args(ParameterLocation))
def test_closed_sibling_schema_preserving_all_model_fields_is_expanded(location):
    class Parameters(msgspec.Struct):
        token: str
        limit: int = 20

    constrained = Annotated[
        Parameters,
        msgspec.Meta(
            extra_json_schema={
                "properties": {"token": {}, "limit": {"minimum": 5}},
                "additionalProperties": False,
            }
        ),
    ]
    api = OpenAPI()
    path = "/{token}/{limit}" if location == "path" else "/"
    api.register_route(path, "get", **{f"{location}_type": constrained})
    token, limit = valid_document(api)["paths"][path]["get"]["parameters"]
    assert [token["name"], limit["name"]] == ["token", "limit"]
    assert token["required"] is True
    assert limit["required"] is (location == "path")
    validator = OAS31Validator(limit["schema"])
    assert validator.is_valid(5)
    assert not validator.is_valid(4)
    assert not validator.is_valid("5")


@pytest.mark.parametrize("location", ["query", "header", "cookie"])
def test_array_like_model_is_rejected_atomically(location):
    class Parameters(msgspec.Struct, array_like=True):
        value: int

    api = OpenAPI()
    before = api.to_dict()
    with pytest.raises(ValueError, match="parameter model without named fields"):
        api.register_route("/", "get", **{f"{location}_type": Parameters})
    assert api.to_dict() == before


def test_generated_model_metadata_is_allowed():
    class Parameters(msgspec.Struct):
        """A generated model description."""

        value: int

    api = OpenAPI()
    api.register_route("/", "post", request_type=Parameters, query_type=Parameters)
    document = valid_document(api)
    component = document["components"]["schemas"]["Parameters"]
    assert component["title"] == "Parameters"
    assert component["description"] == "A generated model description."
    assert document["paths"]["/"]["post"]["parameters"][0]["name"] == "value"


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
        {"additionalProperties": {"type": "string"}},
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
        {"additionalProperties": {"type": "string"}},
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
