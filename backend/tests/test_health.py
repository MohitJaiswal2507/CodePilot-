from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import get_db
from app.main import app

client = TestClient(app)

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["health"] == "/api/health"
    assert "message" in data

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "CodePilot AI Backend"
    assert data["version"] == "0.1.0"
    assert data["environment"] == settings.ENVIRONMENT
    assert data["database"] == "ok"
    assert "timestamp" in data

def test_health_endpoint_degraded_when_db_unavailable():
    broken_db = MagicMock()
    broken_db.execute.side_effect = RuntimeError("postgres://secret:password@db/prod refused")

    def override_get_db():
        yield broken_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unavailable"
        assert data["environment"] == settings.ENVIRONMENT
        assert "postgres://" not in response.text
        assert "refused" not in response.text
    finally:
        app.dependency_overrides.pop(get_db, None)

