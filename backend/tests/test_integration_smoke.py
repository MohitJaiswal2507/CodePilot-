import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.schemas.execution import ExecutionResult
from app.schemas.reviewer import CodeReviewResult, ComplexityAnalysis
from app.services.vector_store import VectorStoreService
from tests.test_auth import ed_public_key, generate_test_jwt
from tests.test_rag_isolation import _create_sample_pdf

client = TestClient(app)


class _EmbeddingResult:
    def __init__(self, vectors):
        self._vectors = vectors

    def tolist(self):
        return self._vectors


class _DeterministicEmbedder:
    """Offline embedder stub that avoids loading or downloading SentenceTransformer models."""

    def encode(self, texts, **kwargs):
        return _EmbeddingResult([[1.0, 0.0, 0.0, 0.0] for _ in texts])


def _auth_headers(user_id: str, email: str) -> dict[str, str]:
    token = generate_test_jwt(user_id=user_id, email=email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def verified_jwt_env(monkeypatch):
    """Enable strict production JWT verification backed by the local Ed25519 test key."""
    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_jwks = MagicMock()
    mock_jwks.get_signing_key_from_jwt.return_value = mock_key

    monkeypatch.setattr("app.core.auth.get_jwks_client", lambda: mock_jwks)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")


@pytest.fixture
def isolated_vector_store(tmp_path, monkeypatch):
    """Provide an isolated temporary ChromaDB instance with deterministic offline embeddings."""
    old_instance = VectorStoreService._instance
    VectorStoreService._instance = None
    temp_store = VectorStoreService(persist_dir=str(tmp_path / "chroma_smoke"))
    temp_store._embedder = _DeterministicEmbedder()
    monkeypatch.setattr(VectorStoreService, "get_instance", classmethod(lambda cls: temp_store))
    try:
        yield temp_store
    finally:
        VectorStoreService._instance = old_instance


def test_smoke_health_and_db_readiness():
    """Health endpoint reports test environment and healthy SQLite DB readiness."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "ok"
    assert data["environment"] == "test"


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/api/conversations", None),
        ("GET", "/api/tutor/documents", None),
        ("POST", "/api/tutor/query", {"question": "What is binary search?"}),
        ("GET", "/api/reviewer/history", None),
        ("POST", "/api/reviewer/review", {"code": "print(1)", "language": "python"}),
        ("POST", "/api/v1/sandbox/execute", {"code": "print(1)", "language": "python"}),
    ],
)
def test_smoke_unauthenticated_access_rejected(verified_jwt_env, method, path, json_body):
    """All protected feature routes fail closed with 401 when unauthenticated."""
    response = client.request(method, path, json=json_body)
    assert response.status_code == 401


def test_smoke_conversation_crud_and_user_isolation(verified_jwt_env):
    """User A creates and retrieves a conversation; User B cannot list or fetch it."""
    suffix = uuid.uuid4().hex[:8]
    headers_a = _auth_headers(f"smoke_conv_a_{suffix}", f"a_{suffix}@example.com")
    headers_b = _auth_headers(f"smoke_conv_b_{suffix}", f"b_{suffix}@example.com")

    create_res = client.post(
        "/api/conversations",
        headers=headers_a,
        json={"title": "Smoke Test Session"},
    )
    assert create_res.status_code == 201
    conv_id = create_res.json()["id"]

    list_a = client.get("/api/conversations", headers=headers_a)
    assert list_a.status_code == 200
    assert any(c["id"] == conv_id for c in list_a.json()["conversations"])

    detail_a = client.get(f"/api/conversations/{conv_id}", headers=headers_a)
    assert detail_a.status_code == 200
    assert detail_a.json()["id"] == conv_id

    list_b = client.get("/api/conversations", headers=headers_b)
    assert list_b.status_code == 200
    assert all(c["id"] != conv_id for c in list_b.json()["conversations"])

    detail_b = client.get(f"/api/conversations/{conv_id}", headers=headers_b)
    assert detail_b.status_code == 404


def test_smoke_pdf_upload_rag_query_and_user_isolation(
    verified_jwt_env,
    isolated_vector_store,
    monkeypatch,
):
    """User A uploads a PDF and queries it via mocked LLM; User B cannot see or query it."""
    suffix = uuid.uuid4().hex[:8]
    user_a = f"smoke_rag_a_{suffix}"
    user_b = f"smoke_rag_b_{suffix}"
    headers_a = _auth_headers(user_a, f"rag_a_{suffix}@example.com")
    headers_b = _auth_headers(user_b, f"rag_b_{suffix}@example.com")

    monkeypatch.setattr(
        "app.services.rag_service.call_gemini",
        lambda prompt, model=None, allow_fallback=False: (
            "Binary search runs in O(log n) time [Document: algorithms_smoke.pdf, Page: 1]."
        ),
    )

    pdf_bytes = _create_sample_pdf("Binary search divides a sorted array in half in O(log n) time.")
    upload_res = client.post(
        "/api/tutor/upload",
        headers=headers_a,
        files={"file": ("algorithms_smoke.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    assert upload_res.json()["document"]["document_name"] == "algorithms_smoke.pdf"

    query_a = client.post(
        "/api/tutor/query",
        headers=headers_a,
        json={"question": "What is the time complexity of binary search?"},
    )
    assert query_a.status_code == 200
    data_a = query_a.json()
    assert data_a["insufficient_context"] is False
    assert "O(log n)" in data_a["answer"]
    assert len(data_a["citations"]) >= 1

    docs_b = client.get("/api/tutor/documents", headers=headers_b)
    assert docs_b.status_code == 200
    assert docs_b.json()["total_documents"] == 0

    query_b = client.post(
        "/api/tutor/query",
        headers=headers_b,
        json={"question": "What is the time complexity of binary search?"},
    )
    assert query_b.status_code == 200
    assert query_b.json()["insufficient_context"] is True


def test_smoke_code_review_persists_and_isolates_history(verified_jwt_env, monkeypatch):
    """User A submits a code review via mocked LangGraph workflow; User B cannot access it."""
    suffix = uuid.uuid4().hex[:8]
    headers_a = _auth_headers(f"smoke_rev_a_{suffix}", f"rev_a_{suffix}@example.com")
    headers_b = _auth_headers(f"smoke_rev_b_{suffix}", f"rev_b_{suffix}@example.com")

    mock_review = CodeReviewResult(
        summary="Clean iterative implementation.",
        overall_assessment="excellent",
        quality_score=9,
        detected_issues=[],
        edge_cases=[],
        complexity=ComplexityAnalysis(
            time_complexity="O(n)",
            time_reasoning="Single linear pass.",
            space_complexity="O(1)",
            space_reasoning="Constant extra variables.",
        ),
        improvement_suggestions=["Add type hints."],
    )
    monkeypatch.setattr(
        "app.api.routes.reviewer.execute_code_review",
        lambda **kwargs: mock_review,
    )

    submit_res = client.post(
        "/api/reviewer/review",
        headers=headers_a,
        json={"code": "def total(nums):\n    return sum(nums)", "language": "python"},
    )
    assert submit_res.status_code == 201
    review_id = submit_res.json()["id"]
    assert submit_res.json()["review"]["quality_score"] == 9

    history_a = client.get("/api/reviewer/history", headers=headers_a)
    assert history_a.status_code == 200
    assert any(item["id"] == review_id for item in history_a.json()["reviews"])

    history_b = client.get("/api/reviewer/history", headers=headers_b)
    assert history_b.status_code == 200
    assert all(item["id"] != review_id for item in history_b.json()["reviews"])

    detail_b = client.get(f"/api/reviewer/{review_id}", headers=headers_b)
    assert detail_b.status_code == 404


def test_smoke_sandbox_validation_and_mocked_execution(verified_jwt_env, monkeypatch):
    """Sandbox route validates input and delegates authenticated execution to mocked service."""
    suffix = uuid.uuid4().hex[:8]
    headers = _auth_headers(f"smoke_sb_{suffix}", f"sb_{suffix}@example.com")

    invalid_res = client.post(
        "/api/v1/sandbox/execute",
        headers=headers,
        json={"code": "puts 1", "language": "ruby"},
    )
    assert invalid_res.status_code == 422

    captured = {}

    def fake_execute_code(*, code: str, language: str, stdin=None) -> ExecutionResult:
        captured["code"] = code
        captured["language"] = language
        captured["stdin"] = stdin
        return ExecutionResult(
            status="success",
            stdout="42\n",
            stderr="",
            exit_code=0,
            duration_ms=12.5,
            timed_out=False,
            truncated=False,
        )

    monkeypatch.setattr("app.api.routes.sandbox.execute_code", fake_execute_code)

    exec_res = client.post(
        "/api/v1/sandbox/execute",
        headers=headers,
        json={"code": "print(42)", "language": "python", "stdin": ""},
    )
    assert exec_res.status_code == 200
    data = exec_res.json()
    assert data["status"] == "success"
    assert data["stdout"] == "42\n"
    assert captured == {"code": "print(42)", "language": "python", "stdin": ""}

