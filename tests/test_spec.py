import json
from collections import namedtuple
from dataclasses import dataclass

import attrs
import msgspec
import pytest

from defspec import OpenAPI, OpenAPIInfo

APIParameter = namedtuple(
    "APIParameter", ["request", "response", "query", "header", "cookie"]
)

# => dataclass


@dataclass
class QueryClass:
    limit: int
    offset: int
    query: str


@dataclass
class CookieClass:
    session_id: str
    token: str


@dataclass
class HeaderClass:
    """Set your API key here."""

    x_api_key: str


@dataclass
class RequestBodyClass:
    name: str
    num: int
    fake: bool
    nested_query: QueryClass


@dataclass
class ResponseClass:
    elapsed: float
    queries: list[QueryClass]


@dataclass
class CustomClass:
    text: str
    num: complex


# => msgspec


class QueryStruct(msgspec.Struct):
    limit: int
    offset: int
    query: str


class CookieStruct(msgspec.Struct):
    session_id: str
    token: str


class HeaderStruct(msgspec.Struct):
    """Set your API key here."""

    x_api_key: str


class RequestBodyStruct(msgspec.Struct):
    name: str
    num: int
    fake: bool
    nested_query: QueryStruct


class ResponseStruct(msgspec.Struct):
    elapsed: float
    queries: list[QueryStruct]


class CustomStruct(msgspec.Struct):
    text: str
    num: complex


# => attrs


@attrs.define
class QueryAttrs:
    limit: int
    offset: int
    query: str


@attrs.define
class CookieAttrs:
    session_id: str
    token: str


@attrs.define
class HeaderAttrs:
    """Set your API key here."""

    x_api_key: str


@attrs.define
class RequestBodyAttrs:
    name: str
    num: int
    fake: bool
    nested_query: QueryAttrs


@attrs.define
class ResponseAttrs:
    elapsed: float
    queries: list[QueryAttrs]


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
    spec = openapi.to_dict()
    assert spec["$defs"][name] == {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "num": {"type": "string", "format": "complex"},
        },
        "title": name,
        "required": ["text", "num"],
    }


def test_openapi_info():
    info = OpenAPIInfo()
    assert info.version == "0.1.0"

    info.version = "0.2.0"
    openapi = OpenAPI(info=info)
    assert openapi.info.version == "0.2.0"

    openapi_dict = openapi.to_dict()
    assert openapi_dict["info"]["version"] == "0.2.0"

    openapi_json_bytes = openapi.to_json()
    openapi_json = json.loads(openapi_json_bytes)
    assert openapi_json["info"]["version"] == "0.2.0"


@pytest.fixture(
    params=[
        pytest.param(
            APIParameter(
                RequestBodyClass, ResponseClass, QueryClass, HeaderClass, CookieClass
            ),
            id="dataclass",
        ),
        pytest.param(
            APIParameter(
                RequestBodyStruct,
                ResponseStruct,
                QueryStruct,
                HeaderStruct,
                CookieStruct,
            ),
            id="msgspec",
        ),
        pytest.param(
            APIParameter(
                RequestBodyAttrs,
                ResponseAttrs,
                QueryAttrs,
                HeaderAttrs,
                CookieAttrs,
            ),
            id="attrs",
        ),
    ]
)
def openapi_spec(request):
    openapi = OpenAPI()
    parameter = request.param
    openapi.register_route(
        path="/test",
        method="post",
        summary="basic test",
        request_type=parameter.request,
        response_type=parameter.response,
        query_type=parameter.query,
        header_type=parameter.header,
        cookie_type=parameter.cookie,
    )
    openapi.register_route(
        path="/test/msgpack",
        method="post",
        request_content_type="application/msgpack",
        response_content_type="application/msgpack",
        request_type=parameter.request,
        response_type=parameter.response,
    )
    openapi.register_route(
        path="/",
        method="get",
        summary="health check",
    )
    return openapi


def test_openapi_spec(openapi_spec):
    spec = openapi_spec.to_dict()
    assert list(spec["paths"].keys()) == ["/test", "/test/msgpack", "/"]
    assert list(spec["paths"]["/test"].keys()) == ["post"]
    assert list(spec["paths"]["/"].keys()) == ["get"]

    assert list(openapi_spec.defs.keys())

    health_check = spec["paths"]["/"]["get"]
    assert health_check["summary"] == "health check"
    assert health_check["operationId"] == "get__"
    assert health_check["responses"] == {"200": {"description": "OK"}}
    assert "parameters" not in health_check

    test = spec["paths"]["/test"]["post"]
    assert test["summary"] == "basic test"
    assert test["operationId"] == "post__test"

    request = test["requestBody"]["content"]["application/json"]["schema"]
    assert request["$ref"].startswith("#/$defs/RequestBody")

    response = test["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].startswith("#/$defs/Response")

    query, header, cookie = test["parameters"]
    assert query["schema"]["$ref"].startswith("#/$defs/Query")
    assert header["schema"]["$ref"].startswith("#/$defs/Header")
    assert header["description"] == "Set your API key here."
    assert cookie["schema"]["$ref"].startswith("#/$defs/Cookie")

    msgpack = spec["paths"]["/test/msgpack"]["post"]
    request = msgpack["requestBody"]["content"]["application/msgpack"]["schema"]
    assert request["$ref"].startswith("#/$defs/RequestBody")
    response = msgpack["responses"]["200"]["content"]["application/msgpack"]["schema"]
    assert response["$ref"].startswith("#/$defs/Response")
