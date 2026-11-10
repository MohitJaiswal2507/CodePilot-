"""
Unified Gemini LLM Gateway for CodePilot AI.

Centralizes `google-genai` client invocation, retry/backoff, fallback handling,
token/model_version extraction, latency measurement, and privacy-safe telemetry
across AI Tutor (RAG + query rewriting) and AI Code Reviewer (LangGraph).
"""

import re
import time
import random
import logging
from typing import Optional, List, Any, Callable
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.core.config import settings
from app.services.observability import LLMTelemetryEvent, record_llm_telemetry

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


class LLMGenerationResult(BaseModel):
    """Internal structured result returned by the shared Gemini gateway."""

    text: str
    model_used: str
    model_version: Optional[str] = None
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    thoughts_tokens: Optional[int] = None
    latency_ms: float = 0.0
    retries: int = 0
    fallback_used: bool = False


# -----------------------------------------------------------------------------
# Error Classification & Retry Helpers
# -----------------------------------------------------------------------------

def is_quota_exhausted_error(err: Optional[Exception]) -> bool:
    """Identify whether an error represents exhausted quota (daily / plan limit) vs transient rate limit."""
    if not err:
        return False
    err_str = str(err).lower()
    quota_indicators = [
        "quota exceeded",
        "quota_exceeded",
        "per day",
        "daily",
        "free_tier_requests",
        "exceeded your current quota",
        "plan and billing",
    ]
    return any(phrase in err_str for phrase in quota_indicators)


def is_transient_rate_limit_error(err: Optional[Exception]) -> bool:
    """Identify if an error is a retryable transient rate limit (429)."""
    if not err:
        return False
    err_str = str(err).lower()
    is_429 = any(phrase in err_str for phrase in ["429", "resource_exhausted", "too many requests", "rate limit"])
    return is_429 and not is_quota_exhausted_error(err)


def extract_retry_delay_seconds(err: Exception) -> Optional[float]:
    """Extract Retry-After or retryDelay from exception if provided by provider."""
    err_str = str(err)
    match_delay = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s?['\"]", err_str)
    if match_delay:
        try:
            return float(match_delay.group(1))
        except ValueError:
            pass

    match_text = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
    if match_text:
        try:
            return float(match_text.group(1))
        except ValueError:
            pass

    return None


def classify_error_category(err: Optional[Exception]) -> str:
    """Map an exception to a safe operational error category without leaking payloads."""
    if not err:
        return "unknown_error"
    if is_quota_exhausted_error(err):
        return "quota_exhausted"
    err_str = str(err)
    if is_transient_rate_limit_error(err) or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
        return "rate_limit"
    if "404" in err_str or "NOT_FOUND" in err_str:
        return "model_not_found"
    if "503" in err_str or "UNAVAILABLE" in err_str:
        return "service_unavailable"
    if any(x in err_str for x in ["401", "403", "API_KEY_INVALID"]):
        return "auth_error"
    if "empty response" in err_str.lower():
        return "empty_response"
    return "api_error"


def _safe_int(value: Any) -> Optional[int]:
    """Return int only if value is a genuine int (excluding bool/Mock objects)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _safe_str(value: Any) -> Optional[str]:
    """Return non-empty string only if value is a genuine str."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_model_id(raw: Optional[str]) -> str:
    model_name = (raw or settings.GEMINI_MODEL or "gemini-3.5-flash-lite").strip()
    if model_name.startswith("models/"):
        model_name = model_name[len("models/"):]
    return model_name


# -----------------------------------------------------------------------------
# Unified Gemini Gateway
# -----------------------------------------------------------------------------

def generate_text(
    prompt: str,
    system_instruction: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
    response_mime_type: Optional[str] = None,
    feature: str = "general",
    client: Optional[genai.Client] = None,
    max_retries: int = 3,
    sleep_fn: Callable[[float], Any] = time.sleep,
    allow_fallback: bool = False,
    fallback_models: Optional[List[str]] = None,
) -> LLMGenerationResult:
    """
    Invoke Gemini API with exponential backoff, optional model fallback,
    usage metadata extraction, latency measurement, and structured telemetry.
    """
    api_key = settings.GEMINI_API_KEY.strip()
    if not api_key:
        record_llm_telemetry(
            LLMTelemetryEvent(
                feature=feature,
                model_used=_normalize_model_id(model),
                latency_ms=0.0,
                retries=0,
                fallback_used=False,
                success=False,
                error_category="missing_api_key",
            )
        )
        raise ValueError("GEMINI_API_KEY is not configured.")

    primary_model = _normalize_model_id(model)
    ai_client = client or genai.Client(api_key=api_key)

    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if system_instruction is not None:
        config_kwargs["system_instruction"] = system_instruction
    if response_mime_type is not None:
        config_kwargs["response_mime_type"] = response_mime_type
    config = types.GenerateContentConfig(**config_kwargs)

    models_to_try = [primary_model]
    if allow_fallback:
        for fallback in (fallback_models or DEFAULT_FALLBACK_MODELS):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

    last_error: Optional[Exception] = None
    last_attempted_model = primary_model
    retries_count = 0
    wall_start = time.perf_counter()

    for current_model in models_to_try:
        last_attempted_model = current_model
        fallback_used = current_model != primary_model

        for attempt in range(max_retries):
            try:
                response = ai_client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=config,
                )
                text = getattr(response, "text", None) if response else None
                if text:
                    latency_ms = round((time.perf_counter() - wall_start) * 1000.0, 2)
                    usage = getattr(response, "usage_metadata", None)
                    prompt_tokens = _safe_int(getattr(usage, "prompt_token_count", None)) if usage else None
                    output_tokens = _safe_int(getattr(usage, "candidates_token_count", None)) if usage else None
                    total_tokens = _safe_int(getattr(usage, "total_token_count", None)) if usage else None
                    thoughts_tokens = _safe_int(getattr(usage, "thoughts_token_count", None)) if usage else None
                    model_version = _safe_str(getattr(response, "model_version", None))

                    record_llm_telemetry(
                        LLMTelemetryEvent(
                            feature=feature,
                            model_used=current_model,
                            model_version=model_version,
                            prompt_tokens=prompt_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                            thoughts_tokens=thoughts_tokens,
                            latency_ms=latency_ms,
                            retries=retries_count,
                            fallback_used=fallback_used,
                            success=True,
                            error_category=None,
                        )
                    )

                    return LLMGenerationResult(
                        text=text,
                        model_used=current_model,
                        model_version=model_version,
                        prompt_tokens=prompt_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        thoughts_tokens=thoughts_tokens,
                        latency_ms=latency_ms,
                        retries=retries_count,
                        fallback_used=fallback_used,
                    )
                raise RuntimeError("Received an empty response from the AI model.")

            except Exception as exc:
                last_error = exc
                err_str = str(exc)
                logger.warning(
                    "Gemini API attempt %d/%d failed with model %s (%s)",
                    attempt + 1,
                    max_retries,
                    current_model,
                    classify_error_category(exc),
                )

                # 1. Quota exhausted: break immediately to fallback (if enabled)
                if is_quota_exhausted_error(exc):
                    logger.info("Daily quota exhausted for %s", current_model)
                    break

                # 2. Model 404: break immediately to fallback (if enabled)
                if "404" in err_str or "NOT_FOUND" in err_str:
                    logger.info("Model %s returned 404", current_model)
                    break

                # 3. Transient rate limit (429) or server unavailable (503): retry with backoff
                if is_transient_rate_limit_error(exc) or "503" in err_str or "UNAVAILABLE" in err_str:
                    if attempt < max_retries - 1:
                        retries_count += 1
                        delay = extract_retry_delay_seconds(exc)
                        if delay is not None and 0 < delay <= 15:
                            wait_time = delay
                        else:
                            wait_time = (1.0 * (2 ** attempt)) + random.uniform(0.1, 0.4)
                        logger.info("Transient rate limit/unavailable. Retrying in %.2fs...", wait_time)
                        sleep_fn(wait_time)
                        continue
                    break

                # 4. Authentication error: fail fast and emit failure telemetry
                if any(x in err_str for x in ["401", "403", "API_KEY_INVALID"]):
                    latency_ms = round((time.perf_counter() - wall_start) * 1000.0, 2)
                    record_llm_telemetry(
                        LLMTelemetryEvent(
                            feature=feature,
                            model_used=current_model,
                            latency_ms=latency_ms,
                            retries=retries_count,
                            fallback_used=fallback_used,
                            success=False,
                            error_category="auth_error",
                        )
                    )
                    raise RuntimeError(
                        "Gemini API authentication failed. Please verify that GEMINI_API_KEY in backend/.env is valid."
                    ) from exc

                if attempt == max_retries - 1:
                    break

    latency_ms = round((time.perf_counter() - wall_start) * 1000.0, 2)
    error_category = classify_error_category(last_error)
    record_llm_telemetry(
        LLMTelemetryEvent(
            feature=feature,
            model_used=last_attempted_model,
            latency_ms=latency_ms,
            retries=retries_count,
            fallback_used=(last_attempted_model != primary_model),
            success=False,
            error_category=error_category,
        )
    )

    err_str = str(last_error) if last_error else ""
    if is_quota_exhausted_error(last_error):
        raise RuntimeError(
            f"Gemini API daily quota exceeded for model '{primary_model}'. "
            "Please select a different available model or wait for your daily quota to reset in Google AI Studio."
        ) from last_error

    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
        raise RuntimeError(
            f"Gemini API rate limit reached for model '{primary_model}' after multiple attempts. Please wait a moment before trying again."
        ) from last_error

    if "404" in err_str or "NOT_FOUND" in err_str:
        raise RuntimeError(
            f"The configured AI model '{primary_model}' was not found. Please verify available models or GEMINI_MODEL in backend/.env."
        ) from last_error

    if "503" in err_str or "UNAVAILABLE" in err_str:
        raise RuntimeError(
            "The AI service is temporarily experiencing high traffic spikes. Please try again in a few moments."
        ) from last_error

    raise RuntimeError(
        f"Unable to generate response from model '{primary_model}' at this moment. Please try again."
    ) from last_error

