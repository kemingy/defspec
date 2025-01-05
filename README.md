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

from defspec import OpenAPI


@dataclass
class User:
    name: str
    age: int


openapi = OpenAPI()
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
