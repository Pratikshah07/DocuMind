from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db


def test_health_reports_ok_with_database(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["components"]["database"] == {"status": "ok", "detail": None}


def test_health_reports_degraded_when_database_down(client: TestClient) -> None:
    class BrokenSession(Session):
        def execute(self, *args, **kwargs):  # type: ignore[override]
            raise ConnectionError("db down")

    client.app.dependency_overrides[get_db] = lambda: BrokenSession()

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert body["components"]["database"]["status"] == "error"
    # The internal exception text must not leak into the response.
    assert "db down" not in body["components"]["database"]["detail"]


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    generated = client.get("/api/health")
    assert len(generated.headers["X-Request-ID"]) == 32

    echoed = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_cors_allows_configured_origin_only(client: TestClient) -> None:
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_openapi_schema_is_served(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert "/api/health" in schema["paths"]
