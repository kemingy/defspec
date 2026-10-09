import pytest


@pytest.fixture(params=["3.1.0", "3.2.0"])
def openapi_version(request):
    """Run complete-document snapshots against both supported minor versions."""
    return request.param
