import pytest
from app.core.config import settings

@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")

