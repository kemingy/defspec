from dataclasses import dataclass
from typing import get_args

import msgspec
import pytest

from defspec import OpenAPI, OpenAPIInfo
from defspec.spec import HTTP_METHODS
from tests.helpers import PathParameters, valid_document


@pytest.mark.parametrize(
    "version,method",
    [
        (version, method)
        for version in ("3.1.0", "3.2.0")
        for method in get_args(HTTP_METHODS)
        if method != "query" or version == "3.2.0"
    ],
)
def test_bodyless_routes(method, version):
    api = OpenAPI(openapi=version)
    api.register_route("/health", method)
    document = valid_document(api)
    assert "$defs" not in document
    operation = document["paths"]["/health"][method]
    assert "requestBody" not in operation
    assert operation["responses"]["200"] == {"description": "OK"}
    assert "security" not in operation


@pytest.mark.parametrize(
    "version,method",
    [
        (version, method)
        for version in ("3.1.0", "3.2.0")
        for method in get_args(HTTP_METHODS)
        if method != "query" or version == "3.2.0"
    ],
)
def test_method_case_is_normalized_before_registration(method, version):
    api = OpenAPI(openapi=version)
    api.register_route("/health", method.upper())
    api.register_route("/health", method.capitalize(), summary="Updated")
    routes = valid_document(api)["paths"]["/health"]
    assert list(routes) == [method]
    assert routes[method]["operationId"] == f"_health_0587c50e302cd55b_{method}"
    assert routes[method]["summary"] == "Updated"


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


@pytest.mark.parametrize("path", ["/a/{id}/{id}", "/a/{id}{id}"])
def test_repeated_path_placeholders_are_rejected_atomically(path):
    api = OpenAPI()
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match="Repeated placeholder.*different name"):
        api.register_route(path, "get", path_type=PathParameters)
    assert api.to_dict() == before


def test_equivalent_path_templates_are_rejected():
    @dataclass
    class OtherPath:
        name: int

    api = OpenAPI()
    api.register_route("/users/{id}", "get", path_type=PathParameters)
    with pytest.raises(ValueError, match="Equivalent path"):
        api.register_route("/users/{name}", "post", path_type=OtherPath)
    valid_document(api)


@pytest.mark.parametrize("paths", [("/a/b", "/a_b"), ("/a_b", "/a/b")])
def test_default_operation_ids_are_unique_and_stable(paths):
    api = OpenAPI()
    for path in paths:
        api.register_route(path, "GET")
    expected = {
        "/a/b": "_a_b_662b7b62a798bb2d_get",
        "/a_b": "_a_b_328ff01fbf3d95bf_get",
    }
    document = valid_document(api)
    assert {
        path: routes["get"]["operationId"] for path, routes in document["paths"].items()
    } == expected

    api = msgspec.json.decode(api.to_json(), type=OpenAPI)
    api.register_route(paths[0], "Get", summary="Updated")
    route = valid_document(api)["paths"][paths[0]]["get"]
    assert route["operationId"] == expected[paths[0]]
    assert route["summary"] == "Updated"


def test_operation_id_collisions_and_explicit_ids():
    api = OpenAPI()
    api.register_route("/a/b", "get")
    api.register_route("/a_b", "get", operation_id="get_flat_ab")
    before = api.to_dict()
    for operation_id in ("get_flat_ab", api.paths["/a/b"]["get"].operation_id):
        with pytest.raises(ValueError, match="Duplicate operationId"):
            api.register_route("/other", "post", operation_id=operation_id)
        assert api.to_dict() == before
    api.register_route("/a_b", "get", operation_id="get_flat_ab", summary="Updated")
    document = valid_document(api)
    assert document["paths"]["/a_b"]["get"]["operationId"] == "get_flat_ab"
    assert document["paths"]["/a_b"]["get"]["summary"] == "Updated"


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


@pytest.mark.parametrize(
    "version", ["3.0.3", "3.3.0", "2.0", "3.1.invalid", "3.2", "3.2.0-rc1"]
)
def test_unsupported_versions(version):
    with pytest.raises(ValueError, match="3.1.x"):
        OpenAPI(openapi=version)


@pytest.mark.parametrize("version", ["3.1.0", "3.1.1", "3.1.2", "3.2.0", "3.2.1"])
def test_patch_version_and_registration_after_decode(version):
    api = msgspec.json.decode(OpenAPI(openapi=version).to_json(), type=OpenAPI)
    api.register_route("/", "get")
    assert valid_document(api)["openapi"] == version


def test_default_version():
    assert valid_document(OpenAPI())["openapi"] == "3.2.0"


@pytest.mark.parametrize("method", ["query", "QUERY", "Query"])
def test_query_method_requires_32(method):
    api = OpenAPI()
    api.register_route("/search", method, request_type=dict[str, str])
    assert "query" in valid_document(api)["paths"]["/search"]
    api = OpenAPI(openapi="3.1.0")
    api.register_route("/", "get")
    before = api.to_dict()
    with pytest.raises(ValueError, match="Unsupported OpenAPI 3.1"):
        api.register_route("/search", method, request_type=dict[str, str])
    assert api.to_dict() == before


@pytest.mark.parametrize("version", ["3.1.0", "3.1.2", "3.2.0", "3.2.1"])
@pytest.mark.parametrize("method", ["get", "query", "connect"])
def test_constructor_and_decode_validate_methods(version, method):
    source = OpenAPI()
    source.register_route("/search", "get")
    operation = source.paths["/search"]["get"]
    paths = {"/search": {method: operation}}
    document = source.to_dict() | {
        "openapi": version,
        "paths": {"/search": {method: source.to_dict()["paths"]["/search"]["get"]}},
    }
    encoded = msgspec.json.encode(document)
    if method == "connect" or (method == "query" and version.startswith("3.1.")):
        with pytest.raises(ValueError, match="Unsupported OpenAPI"):
            OpenAPI(openapi=version, paths=paths)
        with pytest.raises(msgspec.ValidationError, match="Unsupported OpenAPI"):
            msgspec.json.decode(encoded, type=OpenAPI)
    else:
        constructed = OpenAPI(openapi=version, paths=paths)
        decoded = msgspec.json.decode(encoded, type=OpenAPI)
        assert valid_document(constructed) == document
        assert valid_document(decoded) == document


def test_registration_checks_method_after_version_change():
    api = OpenAPI()
    api.openapi = "3.1.0"
    before = api.to_dict()
    with pytest.raises(ValueError, match="Unsupported OpenAPI 3.1"):
        api.register_route("/search", "query", request_type=int)
    assert api.to_dict() == before


def test_query_and_post_coexist_after_decode():
    api = OpenAPI()
    api.register_route("/search", "post", request_type=str)
    api.register_route("/search", "query", request_type=dict[str, str])
    document = valid_document(api)
    assert set(document["paths"]["/search"]) == {"post", "query"}
    api = msgspec.json.decode(api.to_json(), type=OpenAPI)
    api.register_route("/search", "QUERY", summary="Updated", request_type=int)
    updated = valid_document(api)
    assert updated["paths"]["/search"]["post"] == document["paths"]["/search"]["post"]
    assert updated["paths"]["/search"]["query"]["summary"] == "Updated"


def test_openapi_info():
    info = OpenAPIInfo()
    assert info.version == "0.1.0"

    info.version = "0.2.0"
    openapi = OpenAPI(info=info)
    assert openapi.info.version == "0.2.0"

    openapi_dict = openapi.to_dict()
    assert openapi_dict["info"]["version"] == "0.2.0"

    openapi_json_bytes = openapi.to_json()
    openapi_json = msgspec.json.decode(openapi_json_bytes)
    assert openapi_json["info"]["version"] == "0.2.0"
