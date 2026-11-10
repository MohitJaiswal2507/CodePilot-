import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.services.llm_gateway import generate_text
from app.services.observability import LLMTelemetryEvent, record_llm_telemetry
from app.services.review_graph import execute_code_review


def _make_gemini_response(
    text: str,
    model_version: str = "gemini-3.5-flash-lite-001",
    prompt_tokens: int | None = 120,
    output_tokens: int | None = 45,
    total_tokens: int | None = 165,
    thoughts_tokens: int | None = 12,
    include_usage: bool = True,
):
    usage = None
    if include_usage:
        usage = SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
            total_token_count=total_tokens,
            thoughts_token_count=thoughts_tokens,
        )
    return SimpleNamespace(
        text=text,
        model_version=model_version,
        usage_metadata=usage,
    )


# ==============================================================================
# 1. GATEWAY EXTRACTION, RETRIES, FALLBACK & LATENCY TESTS
# ==============================================================================

def test_token_usage_model_version_and_latency_extraction(tmp_path, monkeypatch):
    log_file = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_secret_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_gemini_response(
        text="Binary search runs in O(log n).",
        model_version="gemini-2.5-flash-002",
        prompt_tokens=210,
        output_tokens=64,
        total_tokens=290,
        thoughts_tokens=16,
    )

    res = generate_text(
        prompt="Explain binary search",
        model="gemini-2.5-flash",
        feature="rag_answer",
        client=mock_client,
    )

    assert res.text == "Binary search runs in O(log n)."
    assert res.model_used == "gemini-2.5-flash"
    assert res.model_version == "gemini-2.5-flash-002"
    assert res.prompt_tokens == 210
    assert res.output_tokens == 64
    assert res.total_tokens == 290
    assert res.thoughts_tokens == 16
    assert res.latency_ms >= 0.0
    assert res.retries == 0
    assert res.fallback_used is False

    records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["prompt_tokens"] == 210
    assert records[0]["output_tokens"] == 64
    assert records[0]["total_tokens"] == 290
    assert records[0]["thoughts_tokens"] == 16
    assert records[0]["model_version"] == "gemini-2.5-flash-002"
    assert records[0]["feature"] == "rag_answer"
    assert records[0]["success"] is True


def test_missing_usage_metadata_leaves_tokens_none(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_gemini_response(
        text="Response without usage metadata",
        model_version=None,  # type: ignore
        include_usage=False,
    )

    res = generate_text(prompt="Hello", model="gemini-3.5-flash-lite", client=mock_client)

    assert res.prompt_tokens is None
    assert res.output_tokens is None
    assert res.total_tokens is None
    assert res.thoughts_tokens is None
    assert res.model_version is None


def test_retry_count_tracked_across_transient_rate_limits(tmp_path, monkeypatch):
    log_file = tmp_path / "retry_telemetry.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        Exception("429 RESOURCE_EXHAUSTED: Rate limit exceeded"),
        Exception("503 UNAVAILABLE: Temporary spike"),
        _make_gemini_response(text="Recovered answer", prompt_tokens=10, output_tokens=5, total_tokens=15, thoughts_tokens=None),
    ]
    mock_sleep = MagicMock()

    res = generate_text(
        prompt="Retry test",
        model="gemini-3.5-flash-lite",
        feature="rag_answer",
        client=mock_client,
        sleep_fn=mock_sleep,
    )

    assert res.text == "Recovered answer"
    assert res.retries == 2
    assert res.fallback_used is False
    assert mock_sleep.call_count == 2

    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["retries"] == 2
    assert record["fallback_used"] is False
    assert record["success"] is True


def test_fallback_tracking_when_primary_model_unavailable(tmp_path, monkeypatch):
    log_file = tmp_path / "fallback_telemetry.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = [
        Exception("404 NOT_FOUND: primary model missing"),
        _make_gemini_response(text="Fallback model succeeded", model_version="gemini-3.5-flash-lite-001"),
    ]

    res = generate_text(
        prompt="Rewrite query",
        model="gemini-custom-unavailable",
        feature="rag_rewrite",
        client=mock_client,
        allow_fallback=True,
    )

    assert res.fallback_used is True
    assert res.model_used == "gemini-3.5-flash-lite"

    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["fallback_used"] is True
    assert record["model_used"] == "gemini-3.5-flash-lite"
    assert record["success"] is True


def test_failed_gemini_request_records_failure_telemetry(tmp_path, monkeypatch):
    log_file = tmp_path / "failure_telemetry.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception(
        "429 RESOURCE_EXHAUSTED quota exceeded per day"
    )

    with pytest.raises(RuntimeError, match="daily quota exceeded"):
        generate_text(
            prompt="Fail test",
            model="gemini-2.5-pro",
            feature="code_review",
            client=mock_client,
            allow_fallback=False,
        )

    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["success"] is False
    assert record["error_category"] == "quota_exhausted"
    assert record["model_used"] == "gemini-2.5-pro"
    assert record["prompt_tokens"] is None
    assert record["latency_ms"] >= 0.0


# ==============================================================================
# 2. CODE REVIEWER JSON PARSE FALLBACK & TELEMETRY PRIVACY TESTS
# ==============================================================================

def test_code_reviewer_json_parse_fallback_records_telemetry(tmp_path, monkeypatch):
    log_file = tmp_path / "reviewer_fallback.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_123")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_gemini_response(
        text="NOT VALID JSON: SECRET_USER_CODE_LEAK",
        model_version="gemini-2.5-flash-001",
        prompt_tokens=300,
        output_tokens=20,
        total_tokens=320,
        thoughts_tokens=None,
    )

    with patch("app.services.llm_gateway.genai.Client", return_value=mock_client):
        result = execute_code_review(
            code="def secret_fn():\n    token = 'JWT_TOP_SECRET_ABC'\n    return 1",
            language="python",
            user_id="sensitive_user_999",
            model="gemini-2.5-flash",
        )

    assert result.overall_assessment == "needs_improvement"

    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["event_type"] == "llm_call"
    assert lines[0]["success"] is True
    assert lines[1]["event_type"] == "json_parse_fallback"
    assert lines[1]["parse_fallback"] is True
    assert lines[1]["error_category"] == "json_parse_error"
    assert lines[1]["model_used"] == "gemini-2.5-flash"

    # Sensitive data exclusion verification across all telemetry lines
    raw_log_text = log_file.read_text(encoding="utf-8")
    assert "secret_fn" not in raw_log_text
    assert "JWT_TOP_SECRET_ABC" not in raw_log_text
    assert "sensitive_user_999" not in raw_log_text
    assert "SECRET_USER_CODE_LEAK" not in raw_log_text
    assert "test_key_123" not in raw_log_text


def test_disabled_observability_skips_jsonl_creation(tmp_path, monkeypatch):
    log_file = tmp_path / "should_not_exist.jsonl"
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    recorded = record_llm_telemetry(
        LLMTelemetryEvent(
            feature="rag_answer",
            model_used="gemini-3.5-flash-lite",
            latency_ms=15.0,
            success=True,
        )
    )

    assert recorded is False
    assert not log_file.exists()


def test_observability_io_failure_is_safe_and_sensitive_exc_not_logged(tmp_path, monkeypatch):
    bad_path = tmp_path / "existing_dir_as_file"
    bad_path.mkdir()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "super_secret_api_key_999")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(bad_path))

    # Passing a directory as file path triggers OSError; telemetry must fail safely
    recorded = record_llm_telemetry(
        LLMTelemetryEvent(
            feature="rag_answer",
            model_used="gemini-3.5-flash-lite",
            latency_ms=5.0,
            success=False,
            error_category="api_error",
        )
    )
    assert recorded is False

    # Even when exception text embeds sensitive payload, gateway records only error_category
    valid_log = tmp_path / "safe_error.jsonl"
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(valid_log))
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception(
        "Unexpected error with prompt='SECRET_PDF_CHUNK_XYZ' and jwt='eyJhbGciOi...'"
    )

    with pytest.raises(RuntimeError):
        generate_text(
            prompt="SECRET_PDF_CHUNK_XYZ",
            model="gemini-3.5-flash-lite",
            client=mock_client,
        )

    raw = valid_log.read_text(encoding="utf-8")
    assert "SECRET_PDF_CHUNK_XYZ" not in raw
    assert "eyJhbGciOi" not in raw
    assert "super_secret_api_key_999" not in raw
    assert json.loads(raw.strip())["error_category"] == "api_error"

