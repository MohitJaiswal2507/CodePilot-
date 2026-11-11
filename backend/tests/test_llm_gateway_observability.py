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


# ==============================================================================
# 3. REQUEST TIMEOUT & PER-ATTEMPT LATENCY TELEMETRY TESTS
# ==============================================================================

def test_gateway_passes_configured_timeout_via_http_options(monkeypatch):
    from google.genai import types

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_timeout_cfg")
    monkeypatch.setattr(settings, "GEMINI_REQUEST_TIMEOUT_MS", 45000)
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_gemini_response("OK")

    with patch("app.services.llm_gateway.genai.Client", return_value=mock_client) as mock_ctor:
        res = generate_text(prompt="Ping", model="gemini-3.5-flash-lite")

    assert res.text == "OK"
    mock_ctor.assert_called_once()
    call_kwargs = mock_ctor.call_args.kwargs
    assert call_kwargs["api_key"] == "test_key_timeout_cfg"
    assert isinstance(call_kwargs["http_options"], types.HttpOptions)
    assert call_kwargs["http_options"].timeout == 45000


def test_gateway_measures_attempt_latency_separately_from_total_latency(tmp_path, monkeypatch):
    log_file = tmp_path / "attempt_latency.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_retry")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    # Deterministic virtual clock:
    # wall_start=0.0, attempt1_start=0.0, attempt1_fail=0.05 (50ms),
    # sleep adds +2.0s -> attempt2_start=2.05, attempt2_success=2.12 (70ms, total=2120ms)
    clock = {"t": 0.0}

    def fake_perf_counter():
        return clock["t"]

    def fake_sleep(_sec):
        clock["t"] += 2.0

    calls = {"n": 0}

    def fake_generate_content(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            clock["t"] += 0.05
            raise Exception("503 UNAVAILABLE")
        clock["t"] += 0.07
        return _make_gemini_response("Recovered response")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = fake_generate_content

    with patch("app.services.llm_gateway.time.perf_counter", side_effect=fake_perf_counter):
        res = generate_text(
            prompt="Explain quicksort",
            model="gemini-3.5-flash-lite",
            feature="rag_answer",
            client=mock_client,
            max_retries=2,
            sleep_fn=fake_sleep,
        )

    assert res.retries == 1
    assert res.attempt_latency_ms == pytest.approx(70.0)
    assert res.attempt_latencies_ms == pytest.approx([50.0, 70.0])
    assert res.latency_ms == pytest.approx(2120.0)
    assert res.attempt_latency_ms < res.latency_ms

    record = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert record["attempt_latency_ms"] == pytest.approx(70.0)
    assert record["attempt_latencies_ms"] == pytest.approx([50.0, 70.0])
    assert record["latency_ms"] == pytest.approx(2120.0)
    assert record["retries"] == 1
    assert record["success"] is True


def test_timeout_failure_records_timeout_telemetry_without_leaks(tmp_path, monkeypatch):
    import httpx

    log_file = tmp_path / "timeout_telemetry.jsonl"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "secret_timeout_api_key")
    monkeypatch.setattr(settings, "GEMINI_REQUEST_TIMEOUT_MS", 1500)
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", True)
    monkeypatch.setattr(settings, "OBSERVABILITY_LOG_PATH", str(log_file))

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = httpx.ReadTimeout(
        "Read timed out for prompt='SENSITIVE_PROMPT_TEXT'"
    )

    with pytest.raises(RuntimeError, match="timed out after 1500ms"):
        generate_text(
            prompt="SENSITIVE_PROMPT_TEXT",
            model="gemini-3.8-flash",
            feature="rag_answer",
            client=mock_client,
            max_retries=3,
            allow_fallback=False,
        )

    # Timeout fails fast per model without stacking full timeout retries
    assert mock_client.models.generate_content.call_count == 1
    raw = log_file.read_text(encoding="utf-8")
    assert "SENSITIVE_PROMPT_TEXT" not in raw
    assert "secret_timeout_api_key" not in raw
    record = json.loads(raw.strip())
    assert record["success"] is False
    assert record["error_category"] == "timeout"
    assert record["prompt_tokens"] is None
    assert record["output_tokens"] is None
    assert record["total_tokens"] is None
    assert record["thoughts_tokens"] is None
    assert record["attempt_latency_ms"] is not None
    assert len(record["attempt_latencies_ms"]) == 1
    assert record["model_used"] == "gemini-3.8-flash"

    # Raised exception also carries safe failure telemetry without prompt/answer/key leakage
    try:
        generate_text(
            prompt="SENSITIVE_PROMPT_TEXT",
            model="gemini-3.8-flash",
            feature="rag_answer",
            client=mock_client,
            max_retries=1,
            allow_fallback=False,
        )
    except RuntimeError as raised_err:
        tel = getattr(raised_err, "telemetry_result", None)
        assert tel is not None
        assert tel.success is False
        assert tel.error_category == "timeout"
        assert tel.model_used == "gemini-3.8-flash"
        assert tel.prompt_tokens is None
        assert tel.output_tokens is None
        assert tel.total_tokens is None
        assert tel.thoughts_tokens is None
        assert tel.text == ""
        assert tel.attempt_latency_ms is not None
        assert len(tel.attempt_latencies_ms) == 1
        assert "SENSITIVE_PROMPT_TEXT" not in tel.model_dump_json()
        assert "secret_timeout_api_key" not in tel.model_dump_json()


def test_timeout_triggers_fallback_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test_key_fb")
    monkeypatch.setattr(settings, "OBSERVABILITY_ENABLED", False)

    calls = []

    def side_effect(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "gemini-slow-primary":
            raise TimeoutError("Deadline exceeded")
        return _make_gemini_response("Fallback ok")

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = side_effect

    res = generate_text(
        prompt="Test fallback on timeout",
        model="gemini-slow-primary",
        client=mock_client,
        allow_fallback=True,
        fallback_models=["gemini-fast-fallback"],
    )

    assert calls == ["gemini-slow-primary", "gemini-fast-fallback"]
    assert res.fallback_used is True
    assert res.model_used == "gemini-fast-fallback"
    assert len(res.attempt_latencies_ms) == 2


def test_timeout_setting_parsing_policies(monkeypatch):
    from app.core.config import Settings, parse_positive_int_env

    # Missing value -> default 120000
    monkeypatch.delenv("GEMINI_REQUEST_TIMEOUT_MS", raising=False)
    assert Settings().GEMINI_REQUEST_TIMEOUT_MS == 120000

    # Empty or whitespace-only -> default 120000
    for blank in ("", "   ", "\t\n"):
        monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_MS", blank)
        assert Settings().GEMINI_REQUEST_TIMEOUT_MS == 120000

    # Valid positive integer (including surrounding whitespace)
    monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_MS", " 45000 ")
    assert Settings().GEMINI_REQUEST_TIMEOUT_MS == 45000

    # Invalid non-numeric or non-positive -> explicit ValueError
    for bad in ("abc", "12.5", "0", "-100"):
        monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_MS", bad)
        with pytest.raises(ValueError, match="GEMINI_REQUEST_TIMEOUT_MS"):
            Settings()
        with pytest.raises(ValueError, match="GEMINI_REQUEST_TIMEOUT_MS"):
            parse_positive_int_env(bad, 120000, "GEMINI_REQUEST_TIMEOUT_MS")

