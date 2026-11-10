import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.schemas.execution import ExecutionResult
from app.services.sandbox_limiter import sandbox_limiter
from app.services.sandbox_service import check_docker_available

client = TestClient(app)

# Ephemeral Ed25519 keypair for JWT verification in API tests
_ed_private_key = ed25519.Ed25519PrivateKey.generate()
_ed_public_key = _ed_private_key.public_key()


def _generate_test_jwt(user_id: str, email: str = "sandbox-tester@codepilot.ai") -> str:
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
    return jwt.encode(payload, _ed_private_key, algorithm="EdDSA")


@pytest.fixture(autouse=True)
def _mock_auth_and_reset_limiter():
    """Mock JWKS signature verification to use our test key and reset limiter per test."""
    sandbox_limiter.reset()

    mock_key = MagicMock()
    mock_key.key = _ed_public_key
    mock_jwks_client = MagicMock()
    mock_jwks_client.get_signing_key_from_jwt.return_value = mock_key

    with patch("app.core.auth.get_jwks_client", return_value=mock_jwks_client), \
         patch.object(settings, "ENVIRONMENT", "development"):
        yield

    sandbox_limiter.reset()


def _auth_headers(user_id: str = "sandbox_user_1") -> dict[str, str]:
    return {"Authorization": f"Bearer {_generate_test_jwt(user_id)}"}


# ==============================================================================
# 1. AUTHENTICATION & ACCESS CONTROL TESTS
# ==============================================================================

def test_unauthenticated_request_rejected():
    res = client.post(
        "/api/v1/sandbox/execute",
        json={"code": "print('hello')", "language": "python"},
    )
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]


def test_malformed_token_rejected():
    res = client.post(
        "/api/v1/sandbox/execute",
        headers={"Authorization": "Bearer not-a-valid-token"},
        json={"code": "print('hello')", "language": "python"},
    )
    assert res.status_code == 401


# ==============================================================================
# 2. AUTHENTICATED EXECUTION TESTS (PYTHON, JAVA, CPP)
# ==============================================================================

@patch("app.api.routes.sandbox.execute_code")
def test_authenticated_python_execution(mock_exec):
    mock_exec.return_value = ExecutionResult(
        status="success",
        stdout="Hello, CodePilot!\n",
        stderr="",
        exit_code=0,
        duration_ms=14.2,
        truncated=False,
    )

    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers("user_py"),
        json={"code": "print(input())", "language": "python", "stdin": "Hello, CodePilot!\n"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["stdout"] == "Hello, CodePilot!\n"
    assert body["exit_code"] == 0
    assert body["duration_ms"] == 14.2
    assert body["truncated"] is False

    # Verify route delegates strictly to execute_code with server-controlled defaults
    mock_exec.assert_called_once_with(
        code="print(input())",
        language="python",
        stdin="Hello, CodePilot!\n",
    )


@patch("app.api.routes.sandbox.execute_code")
def test_authenticated_java_execution(mock_exec):
    mock_exec.return_value = ExecutionResult(
        status="success",
        stdout="Java 21 OK\n",
        stderr="",
        exit_code=0,
        duration_ms=42.5,
    )

    java_code = 'public class Main { public static void main(String[] args) { System.out.println("Java 21 OK"); } }'
    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers("user_java"),
        json={"code": java_code, "language": "java"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["stdout"] == "Java 21 OK\n"


@patch("app.api.routes.sandbox.execute_code")
def test_authenticated_cpp_execution(mock_exec):
    mock_exec.return_value = ExecutionResult(
        status="success",
        stdout="C++ 14 OK\n",
        stderr="",
        exit_code=0,
        duration_ms=3.1,
    )

    cpp_code = '#include <iostream>\nint main() { std::cout << "C++ 14 OK\\n"; return 0; }'
    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers("user_cpp"),
        json={"code": cpp_code, "language": "cpp"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["stdout"] == "C++ 14 OK\n"


# ==============================================================================
# 3. REQUEST VALIDATION & SERVER-CONTROLLED CONFIG ENFORCEMENT
# ==============================================================================

def test_invalid_language_rejected():
    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "console.log('hi')", "language": "javascript"},
    )
    assert res.status_code == 422


def test_client_cannot_supply_docker_args_or_image_overrides():
    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={
            "code": "print(1)",
            "language": "python",
            "image": "alpine:latest",
            "docker_args": ["--privileged"],
            "custom_timeout": 9999,
        },
    )
    assert res.status_code == 422


def test_oversized_source_and_stdin_rejected():
    # Exceeds schema 50 KB source cap
    res_src = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "a" * 51201, "language": "python"},
    )
    assert res_src.status_code == 422

    # Exceeds schema 64 KB stdin cap
    res_stdin = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "print(1)", "language": "python", "stdin": "x" * 65537},
    )
    assert res_stdin.status_code == 422

    # Multi-byte UTF-8 payload within char length but > 50 KB UTF-8 bytes
    utf8_src = "\U0001f680" * 15000  # 15k chars (< 51200 chars), 60,000 bytes (> 51200 bytes)
    res_utf8 = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": utf8_src, "language": "python"},
    )
    assert res_utf8.status_code == 422
    assert res_utf8.json()["status"] == "validation_error"


# ==============================================================================
# 4. STRUCTURED FAILURE MAPPING & INFO-LEAK PREVENTION
# ==============================================================================

@patch("app.api.routes.sandbox.execute_code")
def test_execution_timeout_response(mock_exec):
    mock_exec.return_value = ExecutionResult(
        status="timeout",
        stdout="",
        stderr="Execution timed out after 5 seconds.",
        exit_code=124,
        duration_ms=5000.0,
    )

    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "while True: pass", "language": "python"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "timeout"
    assert body["exit_code"] == 124
    assert "timed out" in body["stderr"].lower()


@patch("app.api.routes.sandbox.execute_code")
def test_runtime_error_response(mock_exec):
    mock_exec.return_value = ExecutionResult(
        status="runtime_error",
        stdout="",
        stderr='Traceback (most recent call last):\n  File "main.py", line 1, in <module>\nZeroDivisionError: division by zero\n',
        exit_code=1,
        duration_ms=11.0,
    )

    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "1 / 0", "language": "python"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "runtime_error"
    assert body["exit_code"] == 1
    assert "ZeroDivisionError" in body["stderr"]


@patch("app.api.routes.sandbox.execute_code")
def test_output_limit_exceeded_response(mock_exec):
    mock_exec.return_value = ExecutionResult(
        status="output_limit_exceeded",
        stdout=("A" * 65536) + "\n[Output truncated: exceeded 64 KB limit]",
        stderr="",
        exit_code=137,
        duration_ms=48.0,
        truncated=True,
    )

    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "while True: print('A' * 4096)", "language": "python"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "output_limit_exceeded"
    assert body["truncated"] is True
    assert "[Output truncated: exceeded 64 KB limit]" in body["stdout"]


@patch("app.api.routes.sandbox.execute_code")
def test_docker_unavailable_sanitizes_internal_details(mock_exec):
    # Simulate internal service error containing socket path and image digest details
    mock_exec.return_value = ExecutionResult(
        status="infrastructure_error",
        stdout="",
        stderr=(
            "Cannot connect to npipe:////./pipe/docker_engine; "
            "image python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b missing"
        ),
        exit_code=125,
        duration_ms=12.0,
    )

    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "print('hi')", "language": "python"},
    )
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "infrastructure_error"
    assert body["stderr"] == "Code execution sandbox service is temporarily unavailable."
    assert body["exit_code"] is None
    # Verify host paths, Docker pipes, and image digests do NOT leak to API client
    raw_json = res.text
    assert "docker_engine" not in raw_json
    assert "sha256:" not in raw_json
    assert "npipe://" not in raw_json
    assert "C:\\" not in raw_json


@patch("app.api.routes.sandbox.execute_code")
def test_unexpected_exception_returns_sanitized_500(mock_exec):
    mock_exec.side_effect = RuntimeError(r"Internal failure reading C:\Users\secret\.env")

    res = client.post(
        "/api/v1/sandbox/execute",
        headers=_auth_headers(),
        json={"code": "print('hi')", "language": "python"},
    )
    assert res.status_code == 500
    assert "unexpected internal error" in res.json()["detail"].lower()
    assert "Users" not in res.text
    assert ".env" not in res.text


# ==============================================================================
# 5. CONCURRENCY LIMIT & RATE LIMIT TESTS
# ==============================================================================

@patch("app.api.routes.sandbox.execute_code")
def test_concurrency_limit_blocks_excess_parallel_requests_and_releases_slots(mock_exec, monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_MAX_CONCURRENT_EXECUTIONS", 1)
    monkeypatch.setattr(settings, "SANDBOX_MAX_USER_CONCURRENT_EXECUTIONS", 1)

    entered = threading.Event()
    release = threading.Event()

    def _blocking_exec(**kwargs):
        entered.set()
        release.wait(timeout=5)
        return ExecutionResult(status="success", stdout="done\n", exit_code=0, duration_ms=10.0)

    mock_exec.side_effect = _blocking_exec

    headers_a = _auth_headers("user_concurrent_a")
    headers_b = _auth_headers("user_concurrent_b")

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_first = pool.submit(
            client.post,
            "/api/v1/sandbox/execute",
            headers=headers_a,
            json={"code": "print(1)", "language": "python"},
        )
        assert entered.wait(timeout=3), "First request did not enter execute_code"

        # Second request for a different user must hit global concurrency cap (1) -> 429
        res_second = client.post(
            "/api/v1/sandbox/execute",
            headers=headers_b,
            json={"code": "print(2)", "language": "python"},
        )
        assert res_second.status_code == 429
        assert "Retry-After" in res_second.headers

        # Release the first request and verify completion
        release.set()
        res_first = future_first.result(timeout=5)
        assert res_first.status_code == 200
        assert res_first.json()["stdout"] == "done\n"

    # After release, another request must succeed cleanly (no slot leak)
    res_third = client.post(
        "/api/v1/sandbox/execute",
        headers=headers_b,
        json={"code": "print(3)", "language": "python"},
    )
    assert res_third.status_code == 200


@patch("app.api.routes.sandbox.execute_code")
def test_per_user_rate_limit_enforced(mock_exec, monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(settings, "SANDBOX_RATE_LIMIT_WINDOW_SECONDS", 60)
    mock_exec.return_value = ExecutionResult(status="success", stdout="ok\n", exit_code=0, duration_ms=2.0)

    headers = _auth_headers("rate_limited_user")
    for _ in range(2):
        ok_res = client.post(
            "/api/v1/sandbox/execute",
            headers=headers,
            json={"code": "print('ok')", "language": "python"},
        )
        assert ok_res.status_code == 200

    blocked_res = client.post(
        "/api/v1/sandbox/execute",
        headers=headers,
        json={"code": "print('ok')", "language": "python"},
    )
    assert blocked_res.status_code == 429
    assert "Rate limit exceeded" in blocked_res.json()["detail"]
    assert "Retry-After" in blocked_res.headers


# ==============================================================================
# 6. OPT-IN REAL DOCKER E2E API TEST
# ==============================================================================

IS_DOCKER_AVAILABLE, _ = check_docker_available()
RUN_REAL_DOCKER = os.getenv("RUN_REAL_DOCKER_SANDBOX_TESTS", "0").lower() in ("1", "true")


@pytest.mark.skipif(
    not (IS_DOCKER_AVAILABLE and RUN_REAL_DOCKER),
    reason="Real Docker API integration test is opt-in (set RUN_REAL_DOCKER_SANDBOX_TESTS=1)",
)
def test_real_docker_api_python_java_cpp_execution():
    headers = _auth_headers("real_e2e_user")

    py_res = client.post(
        "/api/v1/sandbox/execute",
        headers=headers,
        json={"code": "print(int(input()) * 2)", "language": "python", "stdin": "21\n"},
    )
    assert py_res.status_code == 200
    assert py_res.json()["status"] == "success"
    assert py_res.json()["stdout"].strip() == "42"

    cpp_res = client.post(
        "/api/v1/sandbox/execute",
        headers=headers,
        json={
            "code": '#include <iostream>\nint main(){ std::cout << 7 * 6 << std::endl; return 0; }',
            "language": "cpp",
        },
    )
    assert cpp_res.status_code == 200
    assert cpp_res.json()["status"] == "success"
    assert cpp_res.json()["stdout"].strip() == "42"

    java_res = client.post(
        "/api/v1/sandbox/execute",
        headers=headers,
        json={
            "code": 'public class Main { public static void main(String[] args) { System.out.println(20 + 22); } }',
            "language": "java",
        },
    )
    assert java_res.status_code == 200
    assert java_res.json()["status"] == "success"
    assert java_res.json()["stdout"].strip() == "42"

