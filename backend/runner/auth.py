"""
Authentication & Replay Protection for CodePilot Runner Microservice.

Validates that incoming requests to the Runner originate from the authorized
CodePilot Gateway via HMAC-SHA256 signatures, timestamp checks, bounded replay cache,
and constant-time verification.
"""

import os
import re
import time
import hmac
import hashlib
import logging
import threading
from enum import Enum
from typing import Dict
from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)

MAX_TIMESTAMP_SKEW_SECONDS = 30
REPLAY_CACHE_TTL_SECONDS = 60
DEFAULT_MAX_REPLAY_CAPACITY = 10_000
_HEX_SIGNATURE_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ReplayCheckResult(Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    CAPACITY_EXHAUSTED = "capacity_exhausted"


class SignatureReplayCache:
    """
    Thread-safe, bounded sliding-window cache preventing replay of observed HMAC signatures.
    Strictly caps memory usage and never evicts unexpired signatures to make room.
    """

    def __init__(
        self,
        ttl_seconds: int = REPLAY_CACHE_TTL_SECONDS,
        max_capacity: int = DEFAULT_MAX_REPLAY_CAPACITY,
    ) -> None:
        self._lock = threading.Lock()
        self._seen: Dict[str, float] = {}
        self._ttl_seconds = ttl_seconds
        self._max_capacity = max(1, int(max_capacity))

    @property
    def capacity(self) -> int:
        return self._max_capacity

    def size(self) -> int:
        with self._lock:
            return len(self._seen)

    def record_signature(self, signature: str) -> ReplayCheckResult:
        """
        Atomically prune expired entries, check for duplicate signatures,
        verify remaining capacity, and record the accepted signature.
        """
        now = time.monotonic()
        with self._lock:
            # 1. Prune expired entries before checking capacity
            cutoff = now - self._ttl_seconds
            expired = [sig for sig, added in self._seen.items() if added < cutoff]
            for sig in expired:
                del self._seen[sig]

            # 2. Check for duplicate/replayed request
            if signature in self._seen:
                return ReplayCheckResult.DUPLICATE

            # 3. Check capacity limit (never evict unexpired entries)
            if len(self._seen) >= self._max_capacity:
                return ReplayCheckResult.CAPACITY_EXHAUSTED

            # 4. Atomically insert accepted signature
            self._seen[signature] = now
            return ReplayCheckResult.ACCEPTED

    def reset(self) -> None:
        """Clear cache (primarily for test isolation)."""
        with self._lock:
            self._seen.clear()


replay_cache = SignatureReplayCache()


async def verify_runner_auth(request: Request) -> None:
    """
    FastAPI dependency enforcing strict HMAC-SHA256 authentication order:
    1. Validate timestamp presence and format.
    2. Enforce ±30s clock skew window.
    3. Validate signature format (64-character hex).
    4. Read raw request body.
    5. Calculate HMAC-SHA256 over timestamp + '.' + body.
    6. Constant-time compare using hmac.compare_digest.
    7. Reject invalid signatures immediately.
    8. Atomically record valid signature in bounded replay cache.
    9. Reject duplicates (HTTP 401) or capacity exhaustion (HTTP 503).
    """
    secret = os.getenv("SANDBOX_RUNNER_SECRET", "").strip()
    if not secret:
        logger.critical("Runner invocation rejected: SANDBOX_RUNNER_SECRET is not configured on the runner.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SANDBOX_RUNNER_SECRET is not configured on the runner host.",
        )

    # 1. Read and validate timestamp header
    timestamp_hdr = request.headers.get("X-CodePilot-Timestamp")
    signature_hdr = request.headers.get("X-CodePilot-Signature")

    if not timestamp_hdr or not signature_hdr:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required runner authentication headers (X-CodePilot-Timestamp, X-CodePilot-Signature).",
        )

    try:
        req_ts = int(timestamp_hdr)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runner timestamp format; must be an integer UNIX epoch.",
        )

    # 2. Reject timestamps outside existing ±30-second window
    now = int(time.time())
    if abs(now - req_ts) > MAX_TIMESTAMP_SKEW_SECONDS:
        logger.warning(
            "Runner request rejected: timestamp skew too large (now=%d, req=%d, skew=%d)",
            now,
            req_ts,
            abs(now - req_ts),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Runner request timestamp expired or clock skewed (> {MAX_TIMESTAMP_SKEW_SECONDS}s).",
        )

    # 3. Validate signature header format and expected length (64 hex characters for SHA-256)
    clean_sig = signature_hdr.strip()
    if len(clean_sig) != 64 or not _HEX_SIGNATURE_RE.match(clean_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runner signature format: expected 64-character hexadecimal SHA-256 digest.",
        )

    # 4. Read the exact raw request body bytes
    body_bytes = await request.body()

    # 5. Calculate HMAC-SHA256 using existing canonical format: timestamp + "." + raw_body_bytes
    expected_mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp_hdr}.".encode("utf-8") + body_bytes,
        hashlib.sha256,
    ).hexdigest()

    # 6. Compare using hmac.compare_digest
    # 7. Reject invalid signatures immediately (invalid requests NEVER enter replay cache)
    if not hmac.compare_digest(expected_mac, clean_sig):
        logger.warning("Runner request rejected: HMAC signature mismatch.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runner authentication signature.",
        )

    # 8. Only after successful HMAC verification, atomically check and record in bounded replay cache
    # 9. Reject already-used signatures (HTTP 401) or capacity exhaustion (HTTP 503)
    replay_status = replay_cache.record_signature(clean_sig)
    if replay_status == ReplayCheckResult.DUPLICATE:
        logger.warning("Runner request rejected: duplicate signature replay attack detected.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Replay attack detected: this signed request signature was already processed.",
        )
    elif replay_status == ReplayCheckResult.CAPACITY_EXHAUSTED:
        logger.error("Runner request rejected: replay cache at capacity (%d entries).", replay_cache.capacity)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runner replay protection cache at capacity. Please try again shortly.",
        )
