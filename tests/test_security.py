import msgspec
import pytest

from defspec import OpenAPI, OpenAPIComponent, SecuritySchemeHTTP, SecuritySchemeOAuth2
from defspec.spec import (
    ClientCredentialsOAuthFlow,
    ImplicitOAuthFlow,
    OAuthFlow,
    OAuthFlowAuthorizationCode,
    PasswordOAuthFlow,
)
from tests.helpers import assert_snapshot, valid_document


@pytest.mark.parametrize(
    "field,flow",
    [
        ("implicit", ImplicitOAuthFlow("https://example.com/auth")),
        ("password", PasswordOAuthFlow("https://example.com/token")),
        ("client_credentials", ClientCredentialsOAuthFlow("https://example.com/token")),
        (
            "authorization_code",
            OAuthFlowAuthorizationCode(
                "https://example.com/auth", "https://example.com/token"
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    "refresh_url", [msgspec.UNSET, None, "https://example.com/refresh"]
)
def test_oauth_optional_fields_and_required_scopes(field, flow, refresh_url):
    flow = type(flow)(**(msgspec.structs.asdict(flow) | {"refresh_url": refresh_url}))
    api = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={"oauth": SecuritySchemeOAuth2(OAuthFlow(**{field: flow}))}
        )
    )
    flows = valid_document(api)["components"]["securitySchemes"]["oauth"]["flows"]
    assert len(flows) == 1
    serialized = next(iter(flows.values()))
    assert serialized["scopes"] == {}
    if isinstance(refresh_url, str):
        assert serialized["refreshUrl"] == refresh_url
    else:
        assert "refreshUrl" not in serialized


def test_oauth_requires_a_flow():
    with pytest.raises(ValueError, match="At least one"):
        OAuthFlow()


def test_operation_security_overrides():
    api = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={"token": SecuritySchemeHTTP("bearer")}
        ),
        security=[{"token": []}],
    )
    api.register_route("/inherited", "get")
    api.register_route("/public", "get", security=[])
    api.register_route("/explicit", "get", security=[{"token": []}])
    paths = valid_document(api)["paths"]
    assert "security" not in paths["/inherited"]["get"]
    assert paths["/public"]["get"]["security"] == []
    assert paths["/explicit"]["get"]["security"] == [{"token": []}]
    api.paths["/explicit"]["get"].security = []
    assert valid_document(api)["paths"]["/explicit"]["get"]["security"] == []


def test_oauth_document():
    flows = OAuthFlow(
        authorization_code=OAuthFlowAuthorizationCode(
            "https://example.com/auth",
            "https://example.com/token",
            refresh_url="https://example.com/refresh",
            scopes={"read": "Read items"},
        ),
        implicit=ImplicitOAuthFlow("https://example.com/auth"),
        password=PasswordOAuthFlow("https://example.com/token", refresh_url=None),
        client_credentials=ClientCredentialsOAuthFlow("https://example.com/token"),
    )
    api = OpenAPI(
        components=OpenAPIComponent(
            security_schemes={"oauth": SecuritySchemeOAuth2(flows)}
        ),
        security=[{"oauth": ["read"]}],
    )
    api.register_route("/items", "get")
    api.register_route("/health", "get", security=[])
    assert_snapshot(api, "oauth")
