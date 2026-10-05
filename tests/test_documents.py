from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from typing import Annotated

import attrs
import msgspec
import pytest

from defspec import OpenAPI, OpenAPIComponent, SecuritySchemeHTTP
from tests.helpers import assert_snapshot

APIParameter = namedtuple(
    "APIParameter", ["name", "request", "response", "query", "header", "cookie"]
)


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


@pytest.fixture(
    params=[
        pytest.param(
            APIParameter(
                "dataclass",
                RequestBodyClass,
                ResponseClass,
                QueryClass,
                HeaderClass,
                CookieClass,
            ),
            id="dataclass",
        ),
        pytest.param(
            APIParameter(
                "msgspec",
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
                "attrs",
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
    openapi = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={"token": SecuritySchemeHTTP(scheme="bearer")}
        ),
        security=[{"token": []}],
    )
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
    return parameter.name, openapi


def test_openapi_spec(openapi_spec):
    name, api = openapi_spec
    assert_snapshot(api, name)


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
    assert_snapshot(api, "recursive_models")
    assert api.defs is api.components.schemas


def test_parameter_document():
    class Path(msgspec.Struct):
        item_id: int = msgspec.field(name="id", default=1)

    class Query(msgspec.Struct):
        limit: Annotated[int, msgspec.Meta(ge=1, description="Maximum items")] = 10
        search: str = ""

    class Headers(msgspec.Struct):
        api_key: str = msgspec.field(name="X-API-Key")

    class Cookies(msgspec.Struct):
        session: str = ""

    api = OpenAPI()
    api.register_route(
        "/items/{id}",
        "get",
        summary="Find an item",
        path_type=Path,
        query_type=Query,
        header_type=Headers,
        cookie_type=Cookies,
    )
    assert_snapshot(api, "parameters")
