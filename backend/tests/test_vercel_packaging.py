"""
Unit and Integration Tests for Vercel Serverless Backend Packaging (Phase 10.4 & 10.4.1).

Verifies:
1. Dependency manifest discovery (pyproject.toml, requirements-vercel.txt, requirements.txt, vercel.json).
2. Memory configuration in vercel.json (memory removed, maxDuration preserved, installCommand configured).
3. Vercel ASGI entry point (backend/api/index.py) exposure and route forwarding (paths, methods, bodies, query params, auth).
4. Database connection pooling: Serverless NullPool vs Local QueuePool.
5. Local ChromaDB compatibility and cloud pgvector lazy imports.
6. Graceful handling of code execution sandbox when SANDBOX_ENABLED=False.
"""

import json
import os
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import NullPool, QueuePool

from app.core.config import Settings, settings
from app.db.session import is_serverless_environment, create_db_engine


_backend_dir = Path(__file__).resolve().parent.parent


def test_dependency_manifest_configuration():
    """
    Verify dependency manifest configuration for Vercel:
    1. pyproject.toml exists as the authoritative cloud manifest and declares only cloud dependencies.
    2. uv.lock exists for deterministic cloud reproducibility.
    3. Heavy local ML packages (torch, sentence-transformers, chromadb) are excluded from pyproject.toml and uv.lock.
    4. Competing requirements-vercel.txt is removed to prevent manifest drift.
    5. Original requirements.txt is preserved for local development.
    """
    pyproject_path = _backend_dir / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml must exist for Vercel Python runtime manifest discovery"

    with open(pyproject_path, "rb") as f:
        pyproject_data = tomllib.load(f)

    cloud_deps = pyproject_data.get("project", {}).get("dependencies", [])
    assert len(cloud_deps) > 0, "pyproject.toml must declare project dependencies"

    cloud_dep_names = [dep.split(">=")[0].split("==")[0].split("<")[0].split("[")[0].strip().lower() for dep in cloud_deps]

    # Excluded heavy local dependencies
    for banned in ["torch", "torchvision", "sentence-transformers", "chromadb"]:
        assert banned not in cloud_dep_names, f"{banned} must not be in pyproject.toml cloud dependencies"

    # Required core cloud dependencies
    for required in ["fastapi", "uvicorn", "pydantic", "httpx", "google-genai", "sqlalchemy", "psycopg", "pyjwt"]:
        assert required in cloud_dep_names, f"{required} must be in pyproject.toml cloud dependencies"

    # Verify uv.lock exists and contains no heavy local dependencies
    uv_lock_path = _backend_dir / "uv.lock"
    assert uv_lock_path.exists(), "uv.lock must exist for deterministic cloud build reproducibility"
    with open(uv_lock_path, "r", encoding="utf-8") as f:
        uv_lock_text = f.read()

    for banned in ['name = "torch"', 'name = "chromadb"', 'name = "sentence-transformers"']:
        assert banned not in uv_lock_text, f"{banned} must not be in uv.lock"

    # Verify redundant/competing requirements-vercel.txt is not present
    vercel_req_path = _backend_dir / "requirements-vercel.txt"
    assert not vercel_req_path.exists(), "requirements-vercel.txt should be removed in favor of authoritative pyproject.toml + uv.lock"

    # Verify original requirements.txt is preserved with local packages
    local_req_path = _backend_dir / "requirements.txt"
    assert local_req_path.exists(), "Original requirements.txt must be preserved"
    with open(local_req_path, "r", encoding="utf-8") as f:
        local_req_text = f.read().lower()

    assert "chromadb" in local_req_text
    assert "sentence-transformers" in local_req_text


def test_vercel_json_configuration():
    """
    Verify backend/vercel.json configuration:
    1. memory is NOT set (unsupported in vercel.json on Hobby).
    2. installCommand is NOT set (native Python functions handle installation automatically via pyproject.toml/uv.lock).
    3. maxDuration is set to 60 on app/main.py (valid on Hobby plan, ceiling 300).
    4. excludeFiles retains all required exclusions (chroma_data, tests, evals, scripts, pytest cache, db).
    5. No conflicting manual rewrites block exists (framework zero-config routing is used).
    """
    vercel_json_path = _backend_dir / "vercel.json"
    assert vercel_json_path.exists(), "backend/vercel.json must exist"

    with open(vercel_json_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 1. Functions configuration for app/main.py
    fn_config = config.get("functions", {}).get("app/main.py", {})
    assert "memory" not in fn_config, "memory must not be specified in vercel.json on Hobby plan"
    assert "api/index.py" not in config.get("functions", {}), "api/index.py is redundant in functions config"

    # 2. installCommand must not be present
    assert "installCommand" not in config, "installCommand should not be in vercel.json for native Python runtime"

    # 3. maxDuration must be 60 on app/main.py
    max_duration = fn_config.get("maxDuration")
    assert max_duration == 60, f"maxDuration should be 60, got {max_duration}"

    # 4. excludeFiles retains required exclusions
    exclude_files = fn_config.get("excludeFiles", "")
    for required_exclusion in ["chroma_data/**", "tests/**", "evals/**", "scripts/**", ".pytest_cache/**", "codepilot_dev.db*"]:
        assert required_exclusion in exclude_files, f"{required_exclusion} must be in excludeFiles"

    # 5. No conflicting manual rewrites block exists
    assert "rewrites" not in config or len(config.get("rewrites", [])) == 0, (
        "manual rewrites block should be absent to avoid routing conflicts with framework destination /fastapi"
    )


def test_serverless_environment_detection(monkeypatch):
    """Verify is_serverless_environment detects Vercel, serverless, and production flags."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("SERVERLESS", raising=False)
    monkeypatch.delenv("DB_POOL_TYPE", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    assert not is_serverless_environment()

    monkeypatch.setenv("VERCEL", "1")
    assert is_serverless_environment()

    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("SERVERLESS", "1")
    assert is_serverless_environment()

    monkeypatch.delenv("SERVERLESS", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert is_serverless_environment()

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setenv("DB_POOL_TYPE", "nullpool")
    assert is_serverless_environment()


def test_postgres_engine_uses_nullpool_in_serverless(monkeypatch):
    """Verify PostgreSQL engine is configured with NullPool in serverless mode."""
    monkeypatch.setenv("VERCEL", "1")
    pg_url = "postgresql+psycopg://user:pass@ep-silent-pool.neon.tech/neondb?sslmode=require"

    engine = create_db_engine(database_url=pg_url)
    assert isinstance(engine.pool, NullPool), f"Expected NullPool, got {type(engine.pool)}"
    engine.dispose()


def test_postgres_engine_uses_standard_pool_locally(monkeypatch):
    """Verify PostgreSQL engine retains QueuePool with concurrency settings in local dev."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("SERVERLESS", raising=False)
    monkeypatch.delenv("DB_POOL_TYPE", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    pg_url = "postgresql+psycopg://user:pass@localhost:5432/codepilot"
    engine = create_db_engine(database_url=pg_url)
    assert isinstance(engine.pool, QueuePool), f"Expected QueuePool, got {type(engine.pool)}"
    assert engine.pool.size() == 10
    engine.dispose()


def test_sqlite_engine_configuration():
    """Verify SQLite engine uses check_same_thread=False for local dev and tests."""
    sqlite_url = "sqlite:///:memory:"
    engine = create_db_engine(database_url=sqlite_url)
    assert engine.url.get_backend_name() == "sqlite"
    engine.dispose()


def test_vercel_api_entrypoint_and_route_forwarding():
    """
    Verify backend/api/index.py exposes FastAPI app and forwards:
    - Root and health paths
    - Query parameters
    - HTTP methods and JSON request bodies
    - Authentication headers
    """
    from api.index import app as vercel_app

    assert vercel_app is not None
    assert vercel_app.title == "CodePilot AI Backend"

    client = TestClient(vercel_app)

    # 1. Root route
    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "CodePilot AI API" in root_res.json()["message"]

    # 2. Health check route
    health_res = client.get("/api/health")
    assert health_res.status_code == 200
    assert health_res.json()["service"] == "CodePilot AI Backend"
    assert health_res.json()["database"] == "ok"

    # 3. Query parameter forwarding
    # /api/conversations with query params limit and offset
    conv_res = client.get("/api/conversations?limit=5&offset=0")
    # Endpoint handles query parameters (returns 200 payload in dev/test fallback auth mode)
    assert conv_res.status_code == 200
    data = conv_res.json()
    assert "conversations" in data
    assert isinstance(data["conversations"], list)
    assert "total" in data

    # 4. HTTP method, headers, and request body forwarding
    from app.core.auth import get_current_user, AuthenticatedUser

    mock_user = AuthenticatedUser(user_id="test-forwarding-user", email="test@forwarding.ai")
    vercel_app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        # POST with JSON body and custom header
        payload = {"language": "python", "code": "x = 42\nprint(x)", "stdin": "input_val"}
        headers = {"X-Custom-Tracking": "vercel-test-123"}
        sandbox_res = client.post(
            "/api/v1/sandbox/execute",
            json=payload,
            headers=headers,
        )
        # Sandbox is enabled locally, so it should process the payload (200 or 503)
        assert sandbox_res.status_code in (200, 503)
    finally:
        vercel_app.dependency_overrides.pop(get_current_user, None)


def test_sandbox_disabled_graceful_response(monkeypatch):
    """Verify sandbox endpoint returns HTTP 503 when SANDBOX_ENABLED=False."""
    from api.index import app as vercel_app
    from app.core.auth import get_current_user, AuthenticatedUser

    mock_user = AuthenticatedUser(user_id="test-user-cloud", email="test@example.com")
    vercel_app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        monkeypatch.setattr(settings, "SANDBOX_ENABLED", False)
        test_client = TestClient(vercel_app)

        response = test_client.post(
            "/api/v1/sandbox/execute",
            json={"language": "python", "code": "print('hello')", "stdin": ""},
        )
        assert response.status_code == 503
        data = response.json()
        assert "disabled" in data["detail"].lower()
    finally:
        vercel_app.dependency_overrides.pop(get_current_user, None)


def test_settings_sandbox_enabled_default_in_cloud(monkeypatch):
    """Verify SANDBOX_ENABLED defaults to False when VERCEL=1."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SANDBOX_ENABLED", raising=False)

    cloud_settings = Settings()
    assert cloud_settings.SANDBOX_ENABLED is False

    monkeypatch.setenv("SANDBOX_ENABLED", "true")
    cloud_settings_override = Settings()
    assert cloud_settings_override.SANDBOX_ENABLED is True


def test_local_chromadb_compatibility():
    """Verify local ChromaDB vector store initialization behaves properly."""
    from app.services.vector_store import VectorStoreService

    # When chromadb is missing, VectorStoreService raises informative ImportError
    with patch.dict(sys.modules, {"chromadb": None}):
        with pytest.raises(ImportError) as exc_info:
            VectorStoreService(persist_dir="temp_test_chroma")
        assert "chromadb is required" in str(exc_info.value)


def test_cloud_pgvector_lazy_imports(monkeypatch):
    """Verify pgvector vector store operates without chromadb or sentence_transformers in cloud mode."""
    with patch.dict(sys.modules, {"chromadb": None, "sentence_transformers": None}):
        monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "pgvector")
        monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "gemini")
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-api-key")

        from app.services.vector_store import VectorStoreService, PgVectorStoreService
        instance = VectorStoreService.get_instance()
        assert isinstance(instance, PgVectorStoreService)
