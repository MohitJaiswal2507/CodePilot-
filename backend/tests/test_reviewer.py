import time
import json
import pytest
import jwt
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.main import app
from app.db.session import SessionLocal
from app.models.code_review import CodeReview
from app.core.config import settings
from app.services.reviewer_tools import inspect_static_code, generate_edge_test_cases, execute_code_in_sandbox
from app.services.review_graph import execute_code_review

client = TestClient(app)

# Test signing key for JWTs
ed_private_key = ed25519.Ed25519PrivateKey.generate()
ed_public_key = ed_private_key.public_key()


def generate_test_jwt(user_id: str, email: str = "test@example.com") -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now - 10,
        "exp": now + 3600,
    }
    if settings.NEON_AUTH_ISSUER:
        payload["iss"] = settings.NEON_AUTH_ISSUER
    if settings.NEON_AUTH_AUDIENCE:
        payload["aud"] = settings.NEON_AUTH_AUDIENCE
    return jwt.encode(payload, ed_private_key, algorithm="EdDSA")


@pytest.fixture(autouse=True)
def mock_jwks_global():
    mock_key = MagicMock()
    mock_key.key = ed_public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    with patch("app.core.auth.get_jwks_client", return_value=mock_client), \
         patch.object(settings, "ENVIRONMENT", "production"):
        yield


@pytest.fixture
def clean_reviews():
    test_users = ["reviewer_user_alice", "reviewer_user_bob"]
    db = SessionLocal()
    try:
        for u in test_users:
            db.query(CodeReview).filter(CodeReview.owner_user_id == u).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        for u in test_users:
            db.query(CodeReview).filter(CodeReview.owner_user_id == u).delete()
        db.commit()
    finally:
        db.close()


# -----------------------------------------------------------------------------
# 1. Static Tool Tests
# -----------------------------------------------------------------------------
def test_static_code_inspection_python_syntax_error():
    broken_py = "def foo(\n  return 42"
    result = inspect_static_code(broken_py, "python")
    assert result["has_syntax_error"] is True
    assert result["error_line"] is not None
    assert "SyntaxError" in result["syntax_error"]


def test_static_code_inspection_python_valid():
    valid_py = "def add(a, b):\n    return a + b\n"
    result = inspect_static_code(valid_py, "python")
    assert result["has_syntax_error"] is False
    assert result["error_line"] is None


def test_static_code_inspection_cpp_unbalanced_brace():
    broken_cpp = "int main() {\n    int x = 5;\n"
    result = inspect_static_code(broken_cpp, "cpp")
    assert result["has_syntax_error"] is True
    assert "Unclosed delimiter" in result["syntax_error"]


def test_static_tools_sandbox_integration():
    res = execute_code_in_sandbox("print('hello')", "python")
    assert res["status"] == "sandbox_deferred"
    assert res["executed"] is False


def test_edge_case_generation():
    cases = generate_edge_test_cases("int sum(int a, int b) { return a + b; }", "cpp")
    assert len(cases) >= 5
    categories = [c["category"] for c in cases]
    assert "Empty / Null Input" in categories
    assert "Integer Overflow" in categories


# -----------------------------------------------------------------------------
# 2. LangGraph Workflow Direct Execution Tests
# -----------------------------------------------------------------------------
def test_execute_code_review_valid_with_mock_llm():
    def mock_llm(prompt: str) -> str:
        return json.dumps({
            "summary": "Efficient binary search implementation.",
            "overall_assessment": "excellent",
            "quality_score": 9,
            "detected_issues": [],
            "edge_cases": [
                {
                    "category": "Empty Input",
                    "scenario": "Empty array passed",
                    "behavior": "Returns -1",
                    "handled": True
                }
            ],
            "complexity": {
                "time_complexity": "O(log n)",
                "time_reasoning": "Search space is halved each step.",
                "space_complexity": "O(1)",
                "space_reasoning": "Uses pointers only."
            },
            "improvement_suggestions": ["Add type hints for enhanced readability."],
            "corrected_code": "def binary_search(arr, target):\n    ...",
            "explanation_of_changes": "Added type hints."
        })

    code = "def binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if arr[mid] == target: return mid\n        elif arr[mid] < target: low = mid + 1\n        else: high = mid - 1\n    return -1"

    result = execute_code_review(
        code=code,
        language="python",
        user_id="user_alice",
        llm_callable=mock_llm,
    )

    assert result.overall_assessment == "excellent"
    assert result.quality_score == 9
    assert result.complexity.time_complexity == "O(log n)"
    assert len(result.edge_cases) >= 1
    assert result.edge_cases[0].handled is True


def test_execute_code_review_malformed_llm_output_fallback():
    def mock_malformed_llm(prompt: str) -> str:
        return "This is plain unstructured text without any JSON formatting."

    code = "def solve():\n    pass"
    result = execute_code_review(
        code=code,
        language="python",
        user_id="user_alice",
        llm_callable=mock_malformed_llm,
    )
    # Must fallback gracefully to structured schema
    assert result.overall_assessment in ["needs_improvement", "problematic"]
    assert result.quality_score >= 1
    assert result.complexity.time_complexity is not None


# -----------------------------------------------------------------------------
# 3. API Endpoints & Multi-User Security Tests
# -----------------------------------------------------------------------------
def test_submit_code_review_unauthenticated():
    res = client.post("/api/reviewer/review", json={"code": "int x = 1;", "language": "cpp"})
    assert res.status_code == 401


def test_submit_code_review_empty_code():
    token = generate_test_jwt("reviewer_user_alice")
    res = client.post(
        "/api/reviewer/review",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "   ", "language": "python"}
    )
    assert res.status_code == 422


def test_submit_code_review_unsupported_language():
    token = generate_test_jwt("reviewer_user_alice")
    res = client.post(
        "/api/reviewer/review",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "console.log('hi');", "language": "javascript"}
    )
    assert res.status_code == 422
    assert any("language" in str(err) for err in res.json()["detail"])


@patch("app.api.routes.reviewer.execute_code_review")
def test_submit_and_retrieve_review_lifecycle(mock_review_exec, clean_reviews):
    mock_res = {
        "summary": "Valid bubble sort implementation.",
        "overall_assessment": "good",
        "quality_score": 7,
        "detected_issues": [
            {
                "type": "performance",
                "severity": "medium",
                "message": "Quadratic time complexity O(n^2)",
                "line_number": 2,
                "suggestion": "Consider QuickSort or MergeSort"
            }
        ],
        "edge_cases": [
            {
                "category": "Duplicate Values",
                "scenario": "All elements equal",
                "behavior": "Stable sort completes in O(n^2)",
                "handled": True
            }
        ],
        "complexity": {
            "time_complexity": "O(n^2)",
            "time_reasoning": "Nested loops iterate up to n times.",
            "space_complexity": "O(1)",
            "space_reasoning": "In-place element swaps."
        },
        "improvement_suggestions": ["Add early-exit flag for sorted arrays."],
        "corrected_code": "def bubble_sort(arr):\n    pass",
        "explanation_of_changes": "Optimized with early termination flag.",
        "static_analysis_notes": "Static syntax verification passed."
    }
    from app.schemas.reviewer import CodeReviewResult
    mock_review_exec.return_value = CodeReviewResult.model_validate(mock_res)

    user_a = "reviewer_user_alice"
    token_a = generate_test_jwt(user_a, "alice@codepilot.ai")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    code = "def bubble_sort(arr):\n    for i in range(len(arr)):\n        for j in range(len(arr)-1):\n            if arr[j] > arr[j+1]: arr[j], arr[j+1] = arr[j+1], arr[j]"

    # 1. Submit review
    post_res = client.post(
        "/api/reviewer/review",
        headers=headers_a,
        json={"code": code, "language": "python"}
    )
    assert post_res.status_code == 201
    data = post_res.json()
    review_id = data["id"]
    assert review_id is not None
    assert data["review"]["overall_assessment"] == "good"
    assert data["review"]["complexity"]["time_complexity"] == "O(n^2)"

    # 2. Get review by ID
    get_res = client.get(f"/api/reviewer/{review_id}", headers=headers_a)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == review_id

    # 3. List history for Alice
    hist_res = client.get("/api/reviewer/history", headers=headers_a)
    assert hist_res.status_code == 200
    assert hist_res.json()["total"] == 1
    assert hist_res.json()["reviews"][0]["id"] == review_id


@patch("app.api.routes.reviewer.execute_code_review")
def test_cross_user_code_review_isolation(mock_review_exec, clean_reviews):
    """Verify that User B cannot view, list, or delete User A's code reviews."""
    mock_res = {
        "summary": "Simple addition function.",
        "overall_assessment": "excellent",
        "quality_score": 10,
        "detected_issues": [],
        "edge_cases": [],
        "complexity": {
            "time_complexity": "O(1)",
            "time_reasoning": "Single arithmetic operation.",
            "space_complexity": "O(1)",
            "space_reasoning": "No memory allocation."
        },
        "improvement_suggestions": [],
        "corrected_code": None,
        "explanation_of_changes": None,
        "static_analysis_notes": None
    }
    from app.schemas.reviewer import CodeReviewResult
    mock_review_exec.return_value = CodeReviewResult.model_validate(mock_res)

    user_a = "reviewer_user_alice"
    user_b = "reviewer_user_bob"
    token_a = generate_test_jwt(user_a, "alice@codepilot.ai")
    token_b = generate_test_jwt(user_b, "bob@codepilot.ai")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice submits a review
    post_res = client.post(
        "/api/reviewer/review",
        headers=headers_a,
        json={"code": "def add(a, b): return a + b", "language": "python"}
    )
    assert post_res.status_code == 201
    review_a_id = post_res.json()["id"]

    # Bob lists history -> must be empty for Bob!
    hist_b = client.get("/api/reviewer/history", headers=headers_b)
    assert hist_b.status_code == 200
    assert hist_b.json()["total"] == 0
    assert len(hist_b.json()["reviews"]) == 0

    # Bob attempts to get Alice's review -> 404
    get_b_attempt = client.get(f"/api/reviewer/{review_a_id}", headers=headers_b)
    assert get_b_attempt.status_code == 404

    # Bob attempts to delete Alice's review -> 404
    del_b_attempt = client.delete(f"/api/reviewer/{review_a_id}", headers=headers_b)
    assert del_b_attempt.status_code == 404

    # Alice deletes her own review -> 200
    del_a = client.delete(f"/api/reviewer/{review_a_id}", headers=headers_a)
    assert del_a.status_code == 200


@patch("app.api.routes.reviewer.execute_code_review")
def test_review_graph_exception_returns_sanitized_500_without_leaking_details(mock_review_exec, caplog):
    mock_review_exec.side_effect = RuntimeError(
        r"Gemini SDK failure reading C:\Users\secret\.env at https://internal.db.local/api?key=LEAKED_KEY"
    )
    token = generate_test_jwt("reviewer_user_alice")

    with caplog.at_level("ERROR", logger="app.api.routes.reviewer"):
        res = client.post(
            "/api/reviewer/review",
            headers={"Authorization": f"Bearer {token}"},
            json={"code": "def SECRET_USER_FN():\n    return 42\n", "language": "python"},
        )

    assert res.status_code == 500
    assert res.json()["detail"] == "Failed to complete code review due to an unexpected internal error."
    for sensitive in ("C:\\Users", ".env", "internal.db.local", "LEAKED_KEY", "SECRET_USER_FN"):
        assert sensitive not in res.text

    # Diagnostic detail logged server-side, without submitted source code
    assert any("Code review execution failed" in rec.message for rec in caplog.records)
    assert all("SECRET_USER_FN" not in rec.getMessage() for rec in caplog.records)


@patch("app.api.routes.reviewer.execute_code_review")
def test_review_db_commit_failure_triggers_rollback_and_returns_sanitized_500(mock_review_exec, clean_reviews):
    from sqlalchemy.orm import Session
    from app.schemas.reviewer import CodeReviewResult

    mock_review_exec.return_value = CodeReviewResult.model_validate({
        "summary": "Valid addition function.",
        "overall_assessment": "excellent",
        "quality_score": 10,
        "detected_issues": [],
        "edge_cases": [],
        "complexity": {
            "time_complexity": "O(1)",
            "time_reasoning": "Constant time operation.",
            "space_complexity": "O(1)",
            "space_reasoning": "No extra memory allocated.",
        },
        "improvement_suggestions": [],
        "corrected_code": None,
        "explanation_of_changes": None,
        "static_analysis_notes": "Static syntax verification passed.",
    })

    token = generate_test_jwt("reviewer_user_alice")
    headers = {"Authorization": f"Bearer {token}"}

    orig_rollback = Session.rollback
    with patch.object(
        Session,
        "commit",
        side_effect=RuntimeError("postgresql://admin:db_secret@neon.internal:5432/neondb commit failed"),
    ), patch.object(
        Session,
        "rollback",
        autospec=True,
        side_effect=orig_rollback,
    ) as mock_rollback:
        res = client.post(
            "/api/reviewer/review",
            headers=headers,
            json={"code": "def add(a, b):\n    return a + b\n", "language": "python"},
        )

    assert res.status_code == 500
    assert res.json()["detail"] == "Failed to save code review due to an internal error."
    mock_rollback.assert_called_once()
    for sensitive in ("postgresql://", "db_secret", "neon.internal", "neondb", "commit failed"):
        assert sensitive not in res.text

    # Verify DB session remains healthy for subsequent reads
    hist_res = client.get("/api/reviewer/history", headers=headers)
    assert hist_res.status_code == 200
    assert hist_res.json()["total"] == 0

