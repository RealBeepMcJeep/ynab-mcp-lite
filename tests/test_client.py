"""Client-layer tests: auth header, error mapping, connection failures."""

import httpx
import pytest

from ynab_mcp_lite.ynab import YnabClient, YnabError


def make_client(handler, token: str = "tok-123") -> YnabClient:
    return YnabClient(
        token=token,
        base_url="https://api.ynab.com/v1",
        transport=httpx.MockTransport(handler),
    )


def test_authorization_header_sent():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {}})

    with make_client(handler) as client:
        client.get("/user")
    assert seen["auth"] == "Bearer tok-123"


def test_401_maps_to_structured_error():
    def handler(request):
        return httpx.Response(
            401, json={"error": {"name": "unauthorized", "detail": "Unauthorized"}}
        )

    with make_client(handler) as client, pytest.raises(YnabError) as ei:
        client.get("/user")
    err = ei.value
    assert err.status == 401
    assert err.name == "unauthorized"
    assert "tok-123" not in str(err.to_dict())


def test_429_becomes_rate_limited():
    def handler(request):
        return httpx.Response(
            429, json={"error": {"name": "too_many_requests", "detail": ""}}
        )

    with make_client(handler) as client, pytest.raises(YnabError) as ei:
        client.get("/plans")
    assert ei.value.status == 429
    assert ei.value.name == "rate_limited"


def test_connection_error_maps_cleanly():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with make_client(handler) as client, pytest.raises(YnabError) as ei:
        client.get("/plans")
    assert ei.value.name == "connection_error"
    assert ei.value.status is None


def test_success_passthrough():
    def handler(request):
        return httpx.Response(200, json={"data": {"plans": []}})

    with make_client(handler) as client:
        assert client.get("/plans") == {"data": {"plans": []}}
