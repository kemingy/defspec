from time import perf_counter
from wsgiref.simple_server import make_server

import falcon
import msgspec
from falcon import App, Request, Response

from defspec import OpenAPI, RenderTemplate


class JSONRequest(msgspec.Struct):
    title: str
    timeout: float


class Query(msgspec.Struct):
    limit: int
    offset: int


class JSONResponse(msgspec.Struct):
    elapsed: float
    queries: list[Query]


class FakeResource:
    def on_post(self, req: Request, resp: Response):
        start = perf_counter()
        request: JSONRequest = msgspec.json.decode(
            req.bounded_stream.read(), type=JSONRequest, strict=False
        )
        print(request)
        query: Query = msgspec.convert(req.params, Query, strict=False)
        response = JSONResponse(elapsed=perf_counter() - start, queries=[query])
        resp.data = msgspec.json.encode(response)


class HealthCheck:
    def on_get(self, req: Request, resp: Response):
        resp.body = "OK"
        resp.content_type = falcon.MEDIA_TEXT


class OpenAPIResource:
    def __init__(self) -> None:
        self.openapi = OpenAPI()
        self.openapi.register_route("/", "get", summary="health check")
        self.openapi.register_route(
            "/fake",
            "post",
            summary="fake endpoint",
            request_type=JSONRequest,
            response_type=JSONResponse,
            query_type=Query,
        )
        self.spec = self.openapi.to_json()

    def on_get(self, req: Request, resp: Response):
        resp.content_type = falcon.MEDIA_JSON
        resp.data = self.spec


class OpenAPIRender:
    def __init__(self, spec_url: str, template: RenderTemplate) -> None:
        self.template = template.value.format(spec_url=spec_url)

    def on_get(self, req: Request, resp: Response):
        resp.content_type = falcon.MEDIA_HTML
        resp.text = self.template


if __name__ == "__main__":
    app = App()
    app.add_route("/", HealthCheck())
    app.add_route("/fake", FakeResource())
    app.add_route("/openapi/spec.json", OpenAPIResource())
    app.add_route(
        "/openapi/redoc", OpenAPIRender("/openapi/spec.json", RenderTemplate.REDOC)
    )
    app.add_route(
        "/openapi/swagger", OpenAPIRender("/openapi/spec.json", RenderTemplate.SWAGGER)
    )
    app.add_route(
        "/openapi/scalar", OpenAPIRender("/openapi/spec.json", RenderTemplate.SCALAR)
    )

    with make_server("", 8000, app) as server:
        print("Serving on port 8000...")
        server.serve_forever()
