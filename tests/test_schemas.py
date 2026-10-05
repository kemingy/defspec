from dataclasses import dataclass, make_dataclass

import attrs
import msgspec
import pytest

from defspec import OpenAPI, OpenAPIComponent
from tests.helpers import PathParameters, valid_document


def test_boolean_body_schemas() -> None:
    class Payload:
        pass

    def schema_hook(type_: type) -> bool:
        return True

    api = OpenAPI()
    api.register_route(
        "/",
        "post",
        request_type=Payload,
        response_type=Payload,
        schema_hook=schema_hook,
    )
    operation = valid_document(api)["paths"]["/"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] is True
    assert (
        operation["responses"]["200"]["content"]["application/json"]["schema"] is True
    )


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


@pytest.mark.parametrize("nested", [False, True])
def test_empty_model_names_are_rejected_atomically(nested):
    unnamed = msgspec.defstruct("", [("value", int)])
    type_ = msgspec.defstruct("Wrapper", [("value", unnamed)]) if nested else unnamed
    api = OpenAPI()
    api.register_route("/", "get", response_type=PathParameters)
    before = valid_document(api)
    with pytest.raises(ValueError, match="Model names must not be empty"):
        api.register_route("/", "post", request_type=type_)
    assert api.to_dict() == before


def test_existing_components_are_not_overwritten():
    api = OpenAPI(
        components=OpenAPIComponent(schemas={"PathParameters": {"type": "string"}})
    )
    before = api.to_dict()
    with pytest.raises(ValueError, match="Conflicting schema name"):
        api.register_route("/", "post", request_type=PathParameters)
    assert api.to_dict() == before


@pytest.mark.parametrize("type_", [type(None), str | None])
def test_explicit_null_bodies(type_):
    api = OpenAPI()
    api.register_route("/", "post", request_type=type_, response_type=type_)
    operation = valid_document(api)["paths"]["/"]["post"]
    assert "application/json" in operation["requestBody"]["content"]
    assert "application/json" in operation["responses"]["200"]["content"]


@dataclass
class CustomClass:
    text: str
    num: complex


class CustomStruct(msgspec.Struct):
    text: str
    num: complex


@attrs.define
class CustomAttrs:
    text: str
    num: complex


@pytest.mark.parametrize(
    "cls",
    [
        pytest.param(CustomClass, id="dataclass"),
        pytest.param(CustomStruct, id="msgspec"),
        pytest.param(CustomAttrs, id="attrs"),
    ],
)
def test_custom_schema(cls):
    def schema_hook(cls):
        if cls is complex:
            return {"type": "string", "format": "complex"}
        raise NotImplementedError()

    name = cls.__name__
    openapi = OpenAPI()
    openapi.register_route(
        path="/",
        method="post",
        request_type=cls,
        response_type=cls,
        query_type=cls,
        schema_hook=schema_hook,
    )
    spec = valid_document(openapi)
    assert spec["components"]["schemas"][name] == {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "num": {"type": "string", "format": "complex"},
        },
        "title": name,
        "required": ["text", "num"],
    }
