from __future__ import annotations

from fastapi.testclient import TestClient

from webhook_platform.config.settings import Settings
from webhook_platform.main import create_app


def test_liveness_and_request_id() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-Id"]


def test_openapi_contains_v1_product_routes() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        document = client.get("/openapi.json").json()
    paths = document["paths"]
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/organizations/{organization_id}/endpoints" in paths
    assert "/api/v1/events" in paths
    assert "/api/v1/organizations/{organization_id}/deliveries/{delivery_id}/replay" in paths


def test_validation_errors_use_stable_safe_envelope() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.post("/api/v1/auth/register", json={})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["request_id"] == response.headers["X-Request-Id"]
    assert "traceback" not in response.text.casefold()


def test_unknown_resource_requires_authentication() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.get("/api/v1/organizations/not-found")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_event_body_limit_rejects_before_authentication() -> None:
    settings = Settings(environment="test", event_body_limit=32)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/events",
            content=b"{" + b'"data":"' + (b"x" * 64) + b'"}',
            headers={
                "Content-Type": "application/json",
                "Origin": "http://localhost:5173",
            },
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "event_too_large"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_openapi_has_explicit_success_response_schemas() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        document = client.get("/openapi.json").json()
    for path, method, status_code in (
        ("/api/v1/auth/register", "post", "201"),
        ("/api/v1/organizations", "get", "200"),
        ("/api/v1/events", "post", "202"),
        ("/api/v1/organizations/{organization_id}/deliveries", "get", "200"),
    ):
        schema = document["paths"][path][method]["responses"][status_code]["content"][
            "application/json"
        ]["schema"]
        assert "$ref" in schema or schema.get("type") == "object"


def test_local_browser_preflight_allows_any_localhost_port() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.options(
            "/api/v1/events",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
            },
        )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_non_local_browser_origin_is_not_allowed_by_default() -> None:
    with TestClient(create_app(Settings(environment="test"))) as client:
        response = client.options(
            "/api/v1/events",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers
