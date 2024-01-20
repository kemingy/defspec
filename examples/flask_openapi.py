from dataclasses import asdict, dataclass
from time import perf_counter

from flask import Flask, request

from defspec import OpenAPI, RenderTemplate


@dataclass
class JSONRequest:
    title: str
    timeout: float


@dataclass
class Query:
    limit: int
    offset: int


@dataclass
class JSONResponse:
    elapsed: float
    queries: list[Query]


app = Flask(__name__)


@app.route("/fake", methods=["POST"])
def fake():
    start = perf_counter()
    req: JSONRequest = JSONRequest(**request.json)
    print(req)
    query: Query = Query(**request.args)
    response = JSONResponse(elapsed=perf_counter() - start, queries=[query])
    return asdict(response)


@app.route("/", methods=["GET"])
def health_check():
    return "OK"


@app.route("/openapi/spec.json", methods=["GET"])
def spec():
    openapi = OpenAPI()
    openapi.register_route("/", "get", summary="health check")
    openapi.register_route(
        "/fake",
        "post",
        summary="fake endpoint",
        request_type=JSONRequest,
        response_type=JSONResponse,
        query_type=Query,
    )
    return openapi.to_dict()


@app.route("/openapi/redoc", methods=["GET"])
def redoc():
    return RenderTemplate.REDOC.value.format(spec_url="/openapi/spec.json")


@app.route("/openapi/swagger", methods=["GET"])
def swagger():
    return RenderTemplate.SWAGGER.value.format(spec_url="/openapi/spec.json")


@app.route("/openapi/scalar", methods=["GET"])
def scalar():
    return RenderTemplate.SCALAR.value.format(spec_url="/openapi/spec.json")


if __name__ == "__main__":
    app.run(debug=True, port=8000)
