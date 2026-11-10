"""
Lightweight, thread-safe operational telemetry for CodePilot AI LLM calls.

SECURITY & PRIVACY CONTRACT:
- Records ONLY operational metadata (model, token counts, latency, retries, error category).
- NEVER logs prompts, PDF text, retrieved chunks, user source code, JWTs, API keys, or user IDs.
- File I/O failures are caught safely so observability never breaks user-facing requests.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("codepilot.observability")

_write_lock = threading.Lock()


class LLMTelemetryEvent(BaseModel):
    """Structured operational telemetry event emitted for LLM generation and parse outcomes."""

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str = Field(default="llm_call", description="'llm_call' or 'json_parse_fallback'")
    feature: str = Field(default="general", description="'rag_rewrite', 'rag_answer', 'code_review', or 'general'")
    model_used: str
    model_version: Optional[str] = None
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    thoughts_tokens: Optional[int] = None
    latency_ms: float = 0.0
    retries: int = 0
    fallback_used: bool = False
    success: bool = True
    error_category: Optional[str] = None
    parse_fallback: bool = False


def record_llm_telemetry(event: LLMTelemetryEvent) -> bool:
    """
    Emit an operational telemetry event to Python structured logging and, when configured,
    append it atomically to `settings.OBSERVABILITY_LOG_PATH` in JSONL format.

    Returns True if telemetry was emitted, False if disabled or if an I/O error occurred.
    """
    if not settings.OBSERVABILITY_ENABLED:
        return False

    try:
        payload_dict = event.model_dump()
        payload_json = json.dumps(payload_dict, separators=(",", ":"))
    except Exception:
        return False

    try:
        logger.info("llm_telemetry %s", payload_json)
    except Exception:
        pass

    log_path_raw = (settings.OBSERVABILITY_LOG_PATH or "").strip()
    if not log_path_raw:
        return True

    try:
        log_path = Path(log_path_raw)
        with _write_lock:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(payload_json + "\n")
        return True
    except Exception as exc:
        try:
            logger.debug("Failed writing observability JSONL record (%s)", type(exc).__name__)
        except Exception:
            pass
        return False

