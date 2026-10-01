from fastapi.testclient import TestClient

from willay.api.main import create_app
from willay.shared.config import Settings

# Without `with TestClient(...)` the lifespan does not run, so no database is touched.
SETTINGS = Settings(database_url="postgresql+asyncpg://unused/unused")


def test_health_returns_ok() -> None:
    response = TestClient(create_app(SETTINGS)).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_the_dashboard_origin_only() -> None:
    client = TestClient(create_app(SETTINGS))
    preflight = {"Access-Control-Request-Method": "GET"}

    allowed = client.options("/v1/me", headers={"Origin": "http://localhost:4200", **preflight})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:4200"

    denied = client.options("/v1/me", headers={"Origin": "http://evil.test", **preflight})
    assert "access-control-allow-origin" not in denied.headers
