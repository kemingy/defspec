import msgspec

from defspec import OpenAPI
from defspec.template import RenderEmbedTemplate


class JSONRequest(msgspec.Struct, frozen=True):
    title: str
    timeout: float


class Query(msgspec.Struct, frozen=True):
    limit: int
    offset: int


class JSONResponse(msgspec.Struct, frozen=True):
    elapsed: float
    queries: list[Query]


if __name__ == "__main__":
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
    spec = openapi.to_json(use_ref=False).decode()

    for key in RenderEmbedTemplate:
        with open(f"{key.name.lower()}.html", "w") as file:
            file.write(key.value.format(spec_object=spec))
