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

DefSpec supports **OpenAPI 3.1.x** (3.1.0 by default).

- Models use `components.schemas` and `#/components/schemas/...` references.
  When migrating, update saved `$defs` references. The `defs=` constructor argument
  is removed; `openapi.defs` remains an alias for `openapi.components.schemas`.
- Query, header, cookie, and path models expand into one parameter per encoded
  field name; generated msgspec tags are omitted. Wrap unions such as `int | str`
  in a model. Named scalars, such as `int` or `UUID`, use the type name as the parameter
  name. Defaults make non-path fields optional unless the schema requires them.
  Path fields must match the URL placeholders and cannot have defaults or default
  factories. Each placeholder must have a unique name.
- Field constraints and descriptions are preserved; parameter schemas are copied
  independently. Model titles, descriptions, and `forbid_unknown_fields` are ignored
  during expansion. Constraints that cannot be expanded raise `ValueError`, including
  `additionalProperties: false` annotations that forbid declared fields.
- Header names `Authorization`, `Accept`, and `Content-Type` are rejected regardless
  of case. Use security schemes and request/response content types instead.
- `request_type=None` omits the body; `response_type=None` omits response content.
  Use `type(None)` for JSON null. Routes document a `200` response by default.
- Omit `security` to inherit global security; use `security=[]` for public routes.
  OAuth flows omit absent fields and keep the required `scopes` map.
- Default operation IDs include a stable path hash: `_users_<hash>_get` for
  GET `/users`. Set `operation_id` to choose your own name.
- Invalid routes, equivalent path templates, duplicate operation IDs, and
  empty or conflicting schema names raise `ValueError` without changing the
  document. HTTP methods are case-insensitive. Use distinct model names and
  `operation_id` values to resolve conflicts.

Custom schema hooks follow msgspec's rules: return a schema dictionary or `True`
for an unconstrained schema. The tests validate generated documents against
OpenAPI 3.1. Validate custom schemas and direct edits before use.
