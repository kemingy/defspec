# DefSpec

[![Python Check](https://github.com/kemingy/defspec/actions/workflows/check.yml/badge.svg)](https://github.com/kemingy/defspec/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/defspec.svg)](https://pypi.org/project/defspec/)

Create the OpenAPI spec and document from `dataclass`, `attrs`, `msgspec`, etc.

## Why not ...

> [!NOTE]
> There are also lots of other projects can generate the OpenAPI document or even validate the data. This project is **not** intended to replace them.

This project is a legacy of a private initiative. During the development, I discovered that using [`msgspec`](https://github.com/jcrist/msgspec) could elegantly define and generate the API schema. The OpenAPI component can be utilized to generate the API documentation for various projects. As a result, I made the decision to extract it and transform it into a public project.

You can use this project as a low-level component or a drop-in module when you don't want to introduce too many other dependencies.

## Installation

```bash
pip install defspec
# to enable the offline feature
pip install defspec[offline]
```

## Examples

- `flask`: [examples/flask](examples/flask_openapi.py)
- `falcon`: [examples/falcon](examples/falcon_openapi.py)
- `offline`: [examples/offline](examples/offline_openapi.py)

You can run the above examples and open the OpenAPI document in your browser:

- `swagger`: http://127.0.0.1:8000/openapi/swagger
- `redoc`: http://127.0.0.1:8000/openapi/redoc
- `scalar`: http://127.0.0.1:8000/openapi/scalar

## Usage

```python
from dataclasses import dataclass
from typing import List

from defspec import OpenAPI, OpenAPIComponent, SecuritySchemeHTTP


@dataclass
class User:
    name: str
    age: int


openapi = OpenAPI(
    components=OpenAPIComponent(
        security_schemes={"token": SecuritySchemeHTTP(scheme="bearer")}
    ),
    security=[{"token": []}],
)
openapi.register_route("/", method="get", summary="Hello World")
openapi.register_route(
    "/users", method="post", summary="Get all the user info", response_type=List[User]
)

# get the OpenAPI spec
print(openapi.to_dict())
# get the OpenAPI spec bytes
with open("openapi.json", "wb") as f:
    f.write(openapi.to_json())

# serve as a HTTP server
openapi.serve_as_http_daemon(port=8000, run_in_background=True)
```

## OpenAPI compatibility

DefSpec generates **OpenAPI 3.1.x** documents (3.1.0 by default). OpenAPI 3.0,
3.2, and Swagger 2.0 are not supported; selecting those versions raises
`ValueError`. The test suite validates generated documents with
`openapi-spec-validator`, including JSON serialization and decoding back into
DefSpec's types. This checks specification conformance, not compatibility with
every documentation renderer or client generator.

Generated models live in `components.schemas`, with references such as
`#/components/schemas/User`. Recursive models and tagged unions use the same
reference location. Reusing an identical schema is supported. Two different
schemas with the same generated name raise `ValueError`; give those models
distinct names. This also protects schemas supplied through `OpenAPIComponent`.
Failed route registration leaves the document unchanged.

### Parameters, bodies, and security

Object models supplied through `query_type`, `header_type`, `cookie_type`, or
`path_type` expand into one parameter per field. Encoded field names are used
verbatim; for example, use `msgspec.field(name="X-API-Key")` for a header alias.
Field descriptions and schema constraints are preserved. Fields with defaults
are optional unless explicitly required by a schema constraint; path parameters
are always mandatory in OpenAPI.
Named scalar/enum parameter types remain supported outside paths, using the
type's `__name__` as the parameter name.
Each parameter owns a copy of its field schema; editing that dictionary does not
modify component schemas or other parameters.

Header names `Authorization`, `Accept`, and `Content-Type` are rejected, regardless
of case, because OpenAPI tools must ignore parameter definitions with these names.
Use security schemes for authorization and `request_content_type` or
`response_content_type` for media types.

For an `Annotated` model, `properties` and `required` constraints beside its
`$ref` can further constrain declared fields. Overlapping field schemas are
combined with `allOf`, and required fields from both sources are retained without
changing the shared component schema. Boolean field schemas (`true` and `false`)
are also supported, including those returned inside a custom `schema_hook` schema.
Constraints that cannot be expanded this way, such as `dependentRequired`,
model-level `allOf`, or `additionalProperties`, and constraints introducing
undeclared fields raise `ValueError`. This check applies to inline object schemas,
referenced components, and reference siblings. Only `type: object`, `properties`,
`required`, `title`, `description`, and `$comment` are supported on expanded object
models. A local component `$ref` can select the model being expanded; other
model-level references and `$id`/`$defs` scopes are rejected because expansion
cannot preserve them. Field schemas retain their own constraints and references.

```python
from dataclasses import dataclass

from defspec import OpenAPI


@dataclass
class UserPath:
    id: int


@dataclass
class SearchQuery:
    limit: int = 20


openapi = OpenAPI()
openapi.register_route(
    "/users/{id}",
    "get",
    path_type=UserPath,
    query_type=SearchQuery,
    operation_id="get_user",
    security=[],
)
```

Every path placeholder must match a `path_type` field, with no extra fields.
Equivalent templates such as `/users/{id}` and `/users/{name}` cannot both be
registered. Methods must be lowercase; `connect` is not supported by OpenAPI 3.1.
Operation IDs must be unique. The default is the method plus the path with
slashes replaced by underscores; supply `operation_id` when those defaults
collide, such as `/a/b` and `/a_b`.

`request_type=None` omits the request body, and `response_type=None` describes a
response without content. Use `type(None)` to describe an explicit JSON null
body, or a nullable type such as `str | None` for a nullable value. Registered
routes currently generate a `200` response; callers can customize the operation's
`responses` mapping directly for other status codes.

Omitting `security` (or passing `None`) inherits the document's global security.
Passing `security=[]` explicitly makes the operation public. OAuth flows omit
absent flow objects and refresh URLs while retaining the required `scopes` map,
even when empty.

### Migrating existing documents

- Read generated schemas from `spec["components"]["schemas"]` instead of
  `spec["$defs"]`. The Python `openapi.defs` property remains an alias for
  `openapi.components.schemas`, but the `defs=` constructor argument is removed.
- Update saved references from `#/$defs/...` to `#/components/schemas/...`.
- Parameter models now expose individual fields rather than one class-named
  object parameter. Update consumers that inspect parameter names or descriptions.
- Declare `path_type` for templated routes, and resolve schema-name and operation-ID
  conflicts that previously produced invalid or silently overwritten documents.

Custom schemas returned by `schema_hook` and direct mutations of the document
must also follow OpenAPI 3.1. DefSpec does not run a full validator during
serialization; applications that modify schemas or operations directly should
validate the final document.
