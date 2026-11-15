"""
Unit Tests for RemoteHttpSandboxProvider.

Tests HMAC signature generation, payload formatting, input pre-validation,
provider dispatching, and error mapping from remote HTTP responses.
"""

import json
import time
from unittest.mock import patch, MagicMock
import urllib.error
import pytest

from app.core.config import settings
from app.schemas.execution import ExecutionResult
from app.services.sandbox.remote_provider import (
    RemoteHttpSandboxProvider,
    generate_hmac_signature,
)
from app.services.sandbox_service import get_sandbox_provider, execute_code
from app.services.sandbox.docker_provider import LocalDockerProvider


@pytest.fixture(autouse=True)
def _reset_sandbox_settings():
    """Ensure clean sandbox settings for each test."""
    orig_provider = settings.SANDBOX_PROVIDER
    orig_url = settings.SANDBOX_RUNNER_URL
    orig_secret = settings.SANDBOX_RUNNER_SECRET
    orig_enabled = settings.SANDBOX_ENABLED
    yield
    settings.SANDBOX_PROVIDER = orig_provider
    settings.SANDBOX_RUNNER_URL = orig_url
    settings.SANDBOX_RUNNER_SECRET = orig_secret
    settings.SANDBOX_ENABLED = orig_enabled


def test_provider_factory_resolution():
    """Verify get_sandbox_provider returns the correct provider based on configuration."""
    with patch.object(settings, "SANDBOX_PROVIDER", "docker"):
        p = get_sandbox_provider()
        assert isinstance(p, LocalDockerProvider)

    with patch.object(settings, "SANDBOX_PROVIDER", "remote_http"):
        p = get_sandbox_provider()
        assert isinstance(p, RemoteHttpSandboxProvider)

    with patch.object(settings, "SANDBOX_PROVIDER", "invalid_provider"):
        with pytest.raises(ValueError, match="Unsupported SANDBOX_PROVIDER"):
            get_sandbox_provider()


def test_hmac_signature_generation():
    """Verify deterministic HMAC-SHA256 signature calculation."""
    secret = "test_super_secret_key_123"
    timestamp = "1794760000"
    body = b'{"code":"print(\'hello\')","language":"python"}'

    sig1 = generate_hmac_signature(secret, timestamp, body)
    sig2 = generate_hmac_signature(secret, timestamp, body)

    assert sig1 == sig2
    assert len(sig1) == 64  # SHA-256 hex digest length
    # Changing any byte should change the signature
    sig_altered = generate_hmac_signature(secret, timestamp, b'{"code":"print(\'world\')","language":"python"}')
    assert sig1 != sig_altered


def test_remote_provider_rejects_missing_configuration():
    """Verify RemoteHttpSandboxProvider returns infrastructure_error when URL/secret are unset."""
    provider = RemoteHttpSandboxProvider()

    with patch.object(settings, "SANDBOX_RUNNER_URL", ""), \
         patch.object(settings, "SANDBOX_RUNNER_SECRET", "secret"):
        res = provider.execute(code="print('ok')", language="python")
        assert res.status == "infrastructure_error"
        assert "URL is not configured" in res.stderr

    with patch.object(settings, "SANDBOX_RUNNER_URL", "https://runner.test"), \
         patch.object(settings, "SANDBOX_RUNNER_SECRET", ""):
        res = provider.execute(code="print('ok')", language="python")
        assert res.status == "infrastructure_error"
        assert "secret is not configured" in res.stderr


def test_remote_provider_pre_validates_inputs_without_http():
    """Verify empty code, bad language, or oversized source are rejected before network calls."""
    provider = RemoteHttpSandboxProvider()

    with patch.object(settings, "SANDBOX_RUNNER_URL", "https://runner.test"), \
         patch.object(settings, "SANDBOX_RUNNER_SECRET", "secret"), \
         patch("urllib.request.urlopen") as mock_urlopen:

        res_empty = provider.execute(code="   ", language="python")
        assert res_empty.status == "validation_error"
        assert "Source code cannot be empty" in res_empty.stderr
        mock_urlopen.assert_not_called()

        res_lang = provider.execute(code="print(1)", language="ruby")  # type: ignore
        assert res_lang.status == "validation_error"
        assert "Unsupported language" in res_lang.stderr
        mock_urlopen.assert_not_called()

        res_oversized = provider.execute(code="A" * 60000, language="python")
        assert res_oversized.status == "validation_error"
        assert "Source code exceeds maximum permitted size" in res_oversized.stderr
        mock_urlopen.assert_not_called()


def test_remote_provider_successful_execution():
    """Verify that successful HTTP response from runner parses into ExecutionResult."""
    provider = RemoteHttpSandboxProvider()
    expected_result = {
        "status": "success",
        "stdout": "Hello from remote runner!\n",
        "stderr": "",
        "compilation_error": None,
        "exit_code": 0,
        "duration_ms": 142.5,
        "compile_duration_ms": None,
        "truncated": False,
    }

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(expected_result).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch.object(settings, "SANDBOX_RUNNER_URL", "https://runner.test"), \
         patch.object(settings, "SANDBOX_RUNNER_SECRET", "secret"), \
         patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:

        result = provider.execute(code="print('Hello from remote runner!')", language="python")

        assert result.status == "success"
        assert result.stdout == "Hello from remote runner!\n"
        assert result.exit_code == 0
        assert mock_urlopen.called

        # Verify headers sent to runner
        req_sent = mock_urlopen.call_args[0][0]
        assert req_sent.get_header("Content-type") == "application/json"
        assert req_sent.get_header("X-codepilot-timestamp") is not None
        assert req_sent.get_header("X-codepilot-signature") is not None


def test_remote_provider_handles_network_drop():
    """Verify that connection failure returns infrastructure_error with clean message."""
    provider = RemoteHttpSandboxProvider()

    with patch.object(settings, "SANDBOX_RUNNER_URL", "https://runner.test"), \
         patch.object(settings, "SANDBOX_RUNNER_SECRET", "secret"), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):

        result = provider.execute(code="print('ok')", language="python")
        assert result.status == "infrastructure_error"
        assert "runner is currently offline or unreachable" in result.stderr


def test_remote_provider_handles_auth_failure():
    """Verify HTTP 401 from runner returns sanitized infrastructure_error."""
    provider = RemoteHttpSandboxProvider()

    err = urllib.error.HTTPError(
        url="https://runner.test/execute",
        code=401,
        msg="Unauthorized",
        hdrs=MagicMock(),
        fp=MagicMock(read=lambda: b'{"detail":"Invalid signature"}'),
    )

    with patch.object(settings, "SANDBOX_RUNNER_URL", "https://runner.test"), \
         patch.object(settings, "SANDBOX_RUNNER_SECRET", "secret"), \
         patch("urllib.request.urlopen", side_effect=err):

        result = provider.execute(code="print('ok')", language="python")
        assert result.status == "infrastructure_error"
        assert "runner authentication failed" in result.stderr
