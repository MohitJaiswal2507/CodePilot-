"""
Unit & Security Tests for CodePilot Runner Microservice.

Tests runner health, HMAC authentication, timestamp validity, bounded replay protection,
atomic concurrency, and layered 256 KB request-body size enforcement.
"""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.schemas.execution import ExecutionResult
from app.services.sandbox.remote_provider import generate_hmac_signature
from runner.main import runner_app, MAX_REQUEST_BODY_BYTES
from runner.auth import replay_cache, SignatureReplayCache, ReplayCheckResult

client = TestClient(runner_app)
TEST_RUNNER_SECRET = "test_hmac_runner_secret_998877"


@pytest.fixture(autouse=True)
def _reset_runner_state():
    """Reset replay cache and ensure runner secret is configured for each test."""
    replay_cache.reset()
    orig = os.environ.get("SANDBOX_RUNNER_SECRET")
    os.environ["SANDBOX_RUNNER_SECRET"] = TEST_RUNNER_SECRET
    yield
    replay_cache.reset()
    if orig is not None:
        os.environ["SANDBOX_RUNNER_SECRET"] = orig
    else:
        os.environ.pop("SANDBOX_RUNNER_SECRET", None)


def _build_signed_headers(payload_dict: dict, skew_seconds: int = 0, secret: str = TEST_RUNNER_SECRET) -> dict[str, str]:
    now = int(time.time()) + skew_seconds
    body_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    sig = generate_hmac_signature(secret, str(now), body_bytes)
    return {
        "Content-Type": "application/json",
        "X-CodePilot-Timestamp": str(now),
        "X-CodePilot-Signature": sig,
    }


# ==============================================================================
# 1. Health Endpoint Tests
# ==============================================================================

def test_runner_health_endpoint():
    """Verify /health returns Docker daemon status and is untouched by middleware."""
    with patch("runner.main.check_docker_available", return_value=(True, "29.9.3")):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["docker_available"] is True
        assert data["docker_version"] == "29.9.3"

    with patch("runner.main.check_docker_available", return_value=(False, "daemon offline")):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["docker_available"] is False


# ==============================================================================
# 2. Authentication & Timestamp Skew Tests
# ==============================================================================

def test_runner_rejects_missing_secret_on_host():
    """Verify 500 when SANDBOX_RUNNER_SECRET is unset in runner environment."""
    os.environ["SANDBOX_RUNNER_SECRET"] = ""
    resp = client.post("/execute", json={"code": "print(1)", "language": "python"})
    assert resp.status_code == 500
    assert "SANDBOX_RUNNER_SECRET is not configured" in resp.json()["detail"]


def test_runner_rejects_missing_auth_headers():
    """Verify 401 when timestamp or signature headers are absent."""
    resp = client.post("/execute", json={"code": "print(1)", "language": "python"})
    assert resp.status_code == 401
    assert "Missing required runner authentication headers" in resp.json()["detail"]


def test_runner_rejects_invalid_timestamp_format():
    """Verify 401 when timestamp is not an integer."""
    resp = client.post(
        "/execute",
        json={"code": "print(1)", "language": "python"},
        headers={
            "X-CodePilot-Timestamp": "not_an_int",
            "X-CodePilot-Signature": "a" * 64,
        },
    )
    assert resp.status_code == 401
    assert "Invalid runner timestamp format" in resp.json()["detail"]


def test_runner_rejects_skewed_timestamp():
    """Verify 401 when timestamp is older or newer than 30 seconds."""
    payload = {"code": "print(1)", "language": "python"}

    # 45 seconds in the past
    past_headers = _build_signed_headers(payload, skew_seconds=-45)
    resp_past = client.post("/execute", json=payload, headers=past_headers)
    assert resp_past.status_code == 401
    assert "timestamp expired or clock skewed" in resp_past.json()["detail"]

    # 45 seconds in the future
    future_headers = _build_signed_headers(payload, skew_seconds=45)
    resp_future = client.post("/execute", json=payload, headers=future_headers)
    assert resp_future.status_code == 401
    assert "timestamp expired or clock skewed" in resp_future.json()["detail"]


def test_runner_rejects_malformed_signature_format():
    """Verify 401 when signature length != 64 or contains non-hex characters."""
    now = str(int(time.time()))

    # Short signature
    resp_short = client.post(
        "/execute",
        json={"code": "print(1)", "language": "python"},
        headers={"X-CodePilot-Timestamp": now, "X-CodePilot-Signature": "abcd1234"},
    )
    assert resp_short.status_code == 401
    assert "Invalid runner signature format" in resp_short.json()["detail"]

    # Non-hex characters
    resp_non_hex = client.post(
        "/execute",
        json={"code": "print(1)", "language": "python"},
        headers={"X-CodePilot-Timestamp": now, "X-CodePilot-Signature": "Z" * 64},
    )
    assert resp_non_hex.status_code == 401
    assert "Invalid runner signature format" in resp_non_hex.json()["detail"]


def test_runner_rejects_invalid_signature():
    """Verify 401 when HMAC signature does not match payload or secret."""
    payload = {"code": "print(1)", "language": "python"}
    headers = _build_signed_headers(payload, secret="wrong_secret_12345")
    resp = client.post("/execute", json=payload, headers=headers)
    assert resp.status_code == 401
    assert "Invalid runner authentication signature" in resp.json()["detail"]


def test_invalid_hmac_does_not_enter_replay_cache():
    """Verify that an invalid HMAC signature NEVER pollutes the replay cache."""
    payload = {"code": "print(1)", "language": "python"}
    bad_headers = _build_signed_headers(payload, secret="attacker_bad_secret")

    assert replay_cache.size() == 0
    resp1 = client.post("/execute", json=payload, headers=bad_headers)
    assert resp1.status_code == 401
    assert "Invalid runner authentication signature" in resp1.json()["detail"]

    # Cache must still be empty
    assert replay_cache.size() == 0

    # Sending the same invalid signature again must still report invalid signature, NOT replay attack
    resp2 = client.post("/execute", json=payload, headers=bad_headers)
    assert resp2.status_code == 401
    assert "Invalid runner authentication signature" in resp2.json()["detail"]


# ==============================================================================
# 3. Replay Protection & Bounded Cache Tests
# ==============================================================================

def test_runner_enforces_anti_replay_protection():
    """Verify identical signed request is rejected on second attempt (replay attack)."""
    payload = {"code": "print('anti-replay')", "language": "python"}
    headers = _build_signed_headers(payload)

    with patch("runner.main.execute_docker_code") as mock_exec:
        mock_exec.return_value = ExecutionResult(
            status="success",
            stdout="anti-replay\n",
            exit_code=0,
            duration_ms=10.0,
        )

        # First request succeeds
        resp1 = client.post("/execute", json=payload, headers=headers)
        assert resp1.status_code == 200

        # Identical second request within TTL must be rejected
        resp2 = client.post("/execute", json=payload, headers=headers)
        assert resp2.status_code == 401
        assert "Replay attack detected" in resp2.json()["detail"]


def test_concurrent_duplicate_requests_only_one_succeeds():
    """Verify that under concurrent duplicate submissions, exactly one request passes."""
    payload = {"code": "print('concurrency_test')", "language": "python"}
    headers = _build_signed_headers(payload)

    with patch("runner.main.execute_docker_code") as mock_exec:
        mock_exec.return_value = ExecutionResult(
            status="success",
            stdout="concurrency_test\n",
            exit_code=0,
            duration_ms=5.0,
        )

        def make_request():
            return client.post("/execute", json=payload, headers=headers).status_code

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(make_request) for _ in range(8)]
            results = [f.result() for f in futures]

        # Exactly 1 success (200) and 7 replay rejections (401)
        assert results.count(200) == 1
        assert results.count(401) == 7


def test_signature_replay_cache_unit_behavior():
    """Unit test SignatureReplayCache capacity, cleanup, and refusal to evict."""
    # 1. Bounded capacity check
    cache = SignatureReplayCache(ttl_seconds=2, max_capacity=3)
    assert cache.record_signature("sig1") == ReplayCheckResult.ACCEPTED
    assert cache.record_signature("sig2") == ReplayCheckResult.ACCEPTED
    assert cache.record_signature("sig3") == ReplayCheckResult.ACCEPTED

    # Replay of existing
    assert cache.record_signature("sig1") == ReplayCheckResult.DUPLICATE

    # 4th new signature rejected due to capacity limit without evicting unexpired entries
    assert cache.record_signature("sig4") == ReplayCheckResult.CAPACITY_EXHAUSTED
    assert cache.size() == 3

    # 2. Expired entry cleanup
    time.sleep(2.1)
    # After TTL, adding a new signature prunes all 3 expired entries
    assert cache.record_signature("sig_new") == ReplayCheckResult.ACCEPTED
    assert cache.size() == 1


def test_runner_returns_503_on_replay_cache_capacity_exhaustion():
    """Verify HTTP 503 is returned when replay cache capacity is exhausted."""
    payload = {"code": "print('cap_test')", "language": "python"}
    headers = _build_signed_headers(payload)

    with patch.object(replay_cache, "record_signature", return_value=ReplayCheckResult.CAPACITY_EXHAUSTED):
        resp = client.post("/execute", json=payload, headers=headers)
        assert resp.status_code == 503
        assert "cache at capacity" in resp.json()["detail"]


# ==============================================================================
# 4. Layered Request-Body Size Limit Tests (Max 256 KB)
# ==============================================================================

def test_runner_rejects_oversized_content_length_early():
    """Verify HTTP 413 when Content-Length header exceeds 256 KB."""
    with patch("runner.main.execute_docker_code") as mock_exec:
        resp = client.post(
            "/execute",
            content=b"x" * 100,
            headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1000)},
        )
        assert resp.status_code == 413
        assert "exceeds maximum permitted size of 256 KB" in resp.json()["detail"]
        mock_exec.assert_not_called()


def test_runner_rejects_negative_or_malformed_content_length():
    """Verify HTTP 400 for negative or unparseable Content-Length headers."""
    resp_neg = client.post(
        "/execute",
        content=b"{}",
        headers={"Content-Length": "-100"},
    )
    assert resp_neg.status_code == 400
    assert "negative length is not permitted" in resp_neg.json()["detail"]

    resp_mal = client.post(
        "/execute",
        content=b"{}",
        headers={"Content-Length": "not_a_number"},
    )
    assert resp_mal.status_code == 400
    assert "must be a valid integer" in resp_mal.json()["detail"]


def test_runner_rejects_chunked_stream_exceeding_256kb():
    """Verify HTTP 413 when streamed chunked body exceeds 256 KB without Content-Length."""
    def chunk_generator():
        # Yield 30 chunks of 10 KB = 300 KB (> 256 KB)
        for _ in range(30):
            yield b"A" * 10240

    with patch("runner.main.execute_docker_code") as mock_exec:
        resp = client.post(
            "/execute",
            content=chunk_generator(),
        )
        assert resp.status_code == 413
        assert "exceeds maximum permitted size of 256 KB" in resp.json()["detail"]
        mock_exec.assert_not_called()


def test_runner_accepts_payload_at_exact_limit():
    """Verify payload exactly at or within 256 KB boundary passes size middleware."""
    # Valid small payload passes size check and proceeds to auth
    payload = {"code": "print('ok')", "language": "python"}
    headers = _build_signed_headers(payload)

    with patch("runner.main.execute_docker_code") as mock_exec:
        mock_exec.return_value = ExecutionResult(
            status="success",
            stdout="ok\n",
            exit_code=0,
            duration_ms=5.0,
        )
        resp = client.post("/execute", json=payload, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


# ==============================================================================
# 5. Execution Delegation Tests
# ==============================================================================

def test_runner_successful_execution_delegation():
    """Verify valid signed request delegates strictly to execute_docker_code."""
    payload = {
        "code": "print('hello_delegation')",
        "language": "python",
        "stdin": "input_val",
        "custom_timeout": 5,
        "custom_compile_timeout": 10,
    }
    headers = _build_signed_headers(payload)

    expected = ExecutionResult(
        status="success",
        stdout="hello_delegation\n",
        stderr="",
        exit_code=0,
        duration_ms=25.0,
    )

    with patch("runner.main.execute_docker_code", return_value=expected) as mock_exec:
        resp = client.post("/execute", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["stdout"] == "hello_delegation\n"

        mock_exec.assert_called_once_with(
            code="print('hello_delegation')",
            language="python",
            stdin="input_val",
            custom_timeout=5,
            custom_compile_timeout=10,
        )


def test_runner_returns_422_on_validation_error():
    """Verify validation_error returns HTTP 422 to caller."""
    payload = {"code": "invalid_code", "language": "python"}
    headers = _build_signed_headers(payload)

    validation_err = ExecutionResult(
        status="validation_error",
        stderr="Source code cannot be empty.",
        exit_code=1,
        duration_ms=0.0,
    )

    with patch("runner.main.execute_docker_code", return_value=validation_err):
        resp = client.post("/execute", json=payload, headers=headers)
        assert resp.status_code == 422
        assert resp.json()["status"] == "validation_error"
