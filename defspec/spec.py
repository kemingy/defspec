from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from typing import Any, Literal, Optional, get_args

import msgspec

from defspec._schema import (
    SchemaHook,
    _add_schema,
    _build_parameters,
    get_def_doc,
)
from defspec.models import (
    DEFAULT_CONTENT_TYPE,
    ClientCredentialsOAuthFlow,
    ImplicitOAuthFlow,
    JSONSchema,
    OAuthFlow,
    OAuthFlowAuthorizationCode,
    OpenAPIComponent,
    OpenAPIInfo,
    OpenAPIParam,
    OpenAPIRequestBody,
    OpenAPIResponse,
    OpenAPIRoute,
    ParameterLocation,
    PasswordOAuthFlow,
    Schema,
    SecuritySchemeAPIKey,
    SecuritySchemeHTTP,
    SecuritySchemeOAuth2,
    SecuritySchemeOpenID,
)
from defspec.server import serve_openapi_http_daemon

__all__ = [
    "DEFAULT_CONTENT_TYPE",
    "HTTP_METHODS",
    "ClientCredentialsOAuthFlow",
    "ImplicitOAuthFlow",
    "JSONSchema",
    "OAuthFlow",
    "OAuthFlowAuthorizationCode",
    "OpenAPI",
    "OpenAPIComponent",
    "OpenAPIInfo",
    "OpenAPIParam",
    "OpenAPIRequestBody",
    "OpenAPIResponse",
    "OpenAPIRoute",
    "ParameterLocation",
    "PasswordOAuthFlow",
    "Schema",
    "SchemaHook",
    "SecuritySchemeAPIKey",
    "SecuritySchemeHTTP",
    "SecuritySchemeOAuth2",
    "SecuritySchemeOpenID",
    "get_def_doc",
]

_PATH_TEMPLATE = re.compile(r"\{([^{}]+)\}")


@lru_cache(maxsize=8192)
def _normalized_path(path: str) -> str:
    """Cache path strings while checking mutable routes and operation IDs live."""
    return _PATH_TEMPLATE.sub("{}", path)


def _parse_path(path: str) -> tuple[str, frozenset[str]]:
    """Read URL placeholders and reject malformed or repeated names."""
    parts = _PATH_TEMPLATE.split(path)
    literals = parts[::2]
    if any("{" in part or "}" in part for part in literals):
        raise ValueError(f"Malformed path template: {path!r}")
    names = parts[1::2]
    placeholders = frozenset(names)
    if len(names) != len(placeholders):
        raise ValueError(
            f"Repeated placeholder in path {path!r}; use a different name for each path parameter."
        )
    return "{}".join(literals), placeholders


HTTP_METHODS = Literal[
    "get", "post", "put", "delete", "head", "options", "trace", "patch", "query"
]


class OpenAPI(msgspec.Struct, kw_only=True):
    """OpenAPI specification.

    Defaults to OpenAPI 3.2.0. Pass openapi="3.1.0" for 3.1 consumers.

    Usage:
        >>> openapi = OpenAPI()
        >>> # init with customized info
        >>> openapi = OpenAPI(
        >>>     info=OpenAPIInfo(title="My API", version="1.2.3"),
        >>>     components=OpenAPIComponent(
        >>>         security_schemes={
        >>>             "APIKey": SecuritySchemeAPIKey(name="X-Auth-Token")
        >>>         }
        >>>     ),
        >>> )
    """

    openapi: str = "3.2.0"
    info: OpenAPIInfo = msgspec.field(default_factory=OpenAPIInfo)
    paths: dict[str, dict[str, OpenAPIRoute]] = msgspec.field(
        default_factory=lambda: defaultdict(dict)
    )
    components: OpenAPIComponent = msgspec.field(default_factory=OpenAPIComponent)
    security: list[dict[str, list[str]]] = msgspec.field(default_factory=list)

    def __post_init__(self):
        if not re.fullmatch(r"3\.(1|2)\.\d+", self.openapi):
            raise ValueError("Only OpenAPI 3.1.x and 3.2.x are supported.")
        for routes in self.paths.values():
            for method in routes:
                self._check_method(method)

    @property
    def defs(self) -> dict[str, Schema]:
        """Compatibility alias for components.schemas; never serialized as $defs."""
        return self.components.schemas

    def _check_method(self, method: str) -> None:
        if method not in get_args(HTTP_METHODS) or (
            method == "query" and self.openapi.startswith("3.1.")
        ):
            raise ValueError(f"Unsupported OpenAPI {self.openapi} method: {method!r}")

    def _check_route(self, path: str, method: str, operation_id: str) -> frozenset[str]:
        self._check_method(method)
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError(
                "Paths must start with '/' and omit queries and fragments."
            )
        normalized, placeholders = _parse_path(path)
        for existing_path, routes in self.paths.items():
            if (
                placeholders
                and existing_path != path
                and "{" in existing_path
                and _normalized_path(existing_path) == normalized
            ):
                raise ValueError(
                    f"Equivalent path template already exists: {existing_path!r}"
                )
            for existing_method, route in routes.items():
                if route.operation_id == operation_id and (
                    existing_path != path or existing_method != method
                ):
                    raise ValueError(
                        f"Duplicate operationId {operation_id!r}; provide a unique operation_id."
                    )
        return placeholders

    def register_route(  # noqa: PLR0913
        self,
        path: str,
        method: str,
        summary: Optional[str] = None,
        request_type: Any = None,
        request_content_type: Optional[str] = None,
        response_type: Any = None,
        response_content_type: Optional[str] = None,
        query_type: Any = None,
        header_type: Any = None,
        cookie_type: Any = None,
        deprecated: bool = False,
        schema_hook: Optional[SchemaHook] = None,
        *,
        path_type: Any = None,
        operation_id: Optional[str] = None,
        security: Optional[list[dict[str, list[str]]]] = None,
    ):
        """Add or replace an endpoint in the OpenAPI document, with a 200 response.

        Each field in a query, header, cookie, or path model becomes a named parameter.
        A named scalar type, such as int, UUID, an Enum, or a NewType, becomes one parameter
        named after the type. Native scalar docstrings are omitted; use msgspec.Meta
        to provide a description.
        Fields with defaults are optional unless the schema requires them. Path fields
        must match the URL placeholders and cannot have defaults or default factories,
        because a URL placeholder cannot be missing.
        TypedDict path keys must be required. Use Required[...] for keys declared
        in a total=False TypedDict.
        Generated struct tags are omitted from parameters. Parameter schemas are
        copied so editing a parameter does not change a shared body schema.

        Pass type(None) to describe a JSON null body. Passing None means no body.
        Invalid routes, conflicting names, and unsupported parameter constraints
        raise ValueError. Failed registration leaves the document unchanged.

        Args:
            path: Endpoint URL, such as /users/{id}.
            method: HTTP method in any letter case. QUERY requires OpenAPI 3.2.
                CONNECT and custom methods are unsupported.
            summary: Short description shown in the API documentation.
            request_type: Type of the request body, or None to omit it.
            request_content_type: Request media type; defaults to application/json.
            response_type: Type of the response body, or None for no response content.
            response_content_type: Response media type; defaults to application/json.
            query_type: Model with query fields, or a named scalar type.
            header_type: Model with header fields, or a named scalar type.
            cookie_type: Model with cookie fields, or a named scalar type.
            deprecated: Mark this endpoint as deprecated.
            schema_hook: Function that describes types msgspec does not recognize.
                Return a schema dictionary or True for an unconstrained schema.
            path_type: Model with one field for each URL placeholder. For /users/{id},
                define 'class PathParams(msgspec.Struct): id: int' and pass PathParams.
            operation_id: Unique name used by API clients. Defaults to the path with
                slashes replaced by underscores, a stable hash of the original path,
                and the lowercase method: _users_<hash>_get.
            security: None uses global security; [] makes this endpoint public.
        """
        method = method.lower()
        operation_id = (
            operation_id
            if operation_id is not None
            else f"{path.replace('/', '_')}_{sha256(path.encode()).hexdigest()[:16]}_{method}"
        )
        placeholders = self._check_route(path, method, operation_id)
        if placeholders and path_type is None:
            raise ValueError(
                f"Path {path!r} needs path_type with fields named: {', '.join(sorted(placeholders))}. "
                "Define a model and pass it as path_type. For example, for '/users/{id}', "
                "define 'class PathParams(msgspec.Struct): id: int' and pass path_type=PathParams."
            )
        # Stage all changes so a failure cannot overwrite an existing operation
        # or leave unused schema definitions behind.
        components = self.components.schemas.copy()
        request_body = (
            OpenAPIRequestBody.with_schema_content_type(
                _add_schema(request_type, components, schema_hook),
                request_content_type,
            )
            if request_type is not None
            else msgspec.UNSET
        )
        response = (
            OpenAPIResponse.with_schema_content_type(
                _add_schema(response_type, components, schema_hook),
                response_content_type,
            )
            if response_type is not None
            else OpenAPIResponse()
        )
        parameters: list[OpenAPIParam] = []
        location: ParameterLocation
        for location, type_ in (
            ("query", query_type),
            ("header", header_type),
            ("cookie", cookie_type),
            ("path", path_type),
        ):
            if type_ is None:
                continue
            parameters.extend(
                _build_parameters(type_, location, components, schema_hook)
            )
        path_parameters = {
            param.name for param in parameters if param.located_in == "path"
        }
        if placeholders != path_parameters:
            details = []
            if missing := placeholders - path_parameters:
                details.append(f"missing fields: {', '.join(sorted(missing))}")
            if extra := path_parameters - placeholders:
                details.append(f"unexpected fields: {', '.join(sorted(extra))}")
            raise ValueError(
                f"path_type must match the placeholders in {path!r} ({'; '.join(details)}). "
                "Use matching field names or msgspec.field(name=...) to set their encoded names."
            )
        route = OpenAPIRoute(
            summary=summary or f"{method} from {path.replace('/', ' ')}",
            operation_id=operation_id,
            request_body=request_body,
            responses={"200": response},
            parameters=parameters,
            deprecated=deprecated,
            security=msgspec.UNSET if security is None else security,
        )
        self.components.schemas.update(components)
        self.paths.setdefault(path, {})[method] = route

    def to_json(self) -> bytes:
        """Convert to a JSON bytes that is commonly used in HTTP endpoint."""
        return msgspec.json.encode(self)

    def to_dict(self) -> dict:
        """Convert to a dict."""
        return msgspec.to_builtins(self)

    def serve_as_http_daemon(
        self, host: str = "127.0.0.1", port: int = 8080, run_in_background: bool = False
    ):
        """Serve the OpenAPI specification and UI as a HTTP server.

        - `/openapi/spec.json`: the OpenAPI specification
        - `/openapi/swagger`: the Swagger UI
        - `/openapi/redoc`: the ReDoc UI
        - `/openapi/scalar`: the Scalar UI

        Args:
            host: host to serve
            port: port to serve
            run_in_background: whether to run in a daemon thread
        """
        serve_openapi_http_daemon(host, port, run_in_background, self.to_json())
