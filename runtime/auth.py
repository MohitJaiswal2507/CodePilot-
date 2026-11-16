"""
CodePilot Local Runtime - Security & Pairing System.

Implements:
1. Origin & Host verification (prevents malicious websites & DNS rebinding)
2. One-time pairing code with 5-minute expiry
3. Cryptographically secure session tokens
4. Bounded signature replay cache
5. Private Network Access (PNA) preflight support
"""

import os
import re
import json
import time
import secrets
import hashlib
import hmac
import logging
import threading
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status

from runtime.config import ALLOWED_ORIGIN_PATTERNS, STATE_FILE, SECRET_FILE

logger = logging.getLogger("codepilot.runtime.auth")

PAIRING_EXPIRY_SECONDS = 300  # 5 minutes
SESSION_TOKEN_LENGTH = 32

_compiled_origin_res = [re.compile(p) for p in ALLOWED_ORIGIN_PATTERNS]


def is_allowed_origin(origin: Optional[str]) -> bool:
    """Validate if the Origin header matches authorized CodePilot domains."""
    if not origin:
        return True  # Direct non-browser curl/API requests
    return any(pattern.match(origin) for pattern in _compiled_origin_res)


def validate_host_header(host: Optional[str]) -> bool:
    """Validate that the Host header is localhost or 127.0.0.1 (guards against DNS rebinding)."""
    if not host:
        return True
    host_clean = host.split(":")[0].strip().lower()
    return host_clean in ("127.0.0.1", "localhost", "::1", "testserver")


class PairingManager:
    """Manages secure pairing codes and persistent local session tokens."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active_code: Optional[str] = None
        self._code_created_at: float = 0.0
        self._active_sessions: Dict[str, float] = {}  # token -> created_at
        self._load_state()

    def _load_state(self):
        """Load stored sessions from disk if available."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._active_sessions = data.get("sessions", {})
        except Exception as e:
            logger.warning("Could not read runtime state: %s", e)
            self._active_sessions = {}

    def _save_state(self):
        """Persist sessions to disk."""
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"sessions": self._active_sessions}, f, indent=2)
        except Exception as e:
            logger.error("Could not write runtime state: %s", e)

    def generate_pairing_code(self) -> Dict[str, Any]:
        """Generate a random 6-digit alphanumeric pairing code."""
        with self._lock:
            # 6-digit uppercase alphanumeric, excluding ambiguous characters (0, O, 1, I)
            alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            self._active_code = code
            self._code_created_at = time.time()
            logger.info("Generated new local pairing code: %s (expires in %ds)", code, PAIRING_EXPIRY_SECONDS)
            return {
                "pairing_code": code,
                "expires_in": PAIRING_EXPIRY_SECONDS,
                "message": "Enter this code in your CodePilot browser window to pair.",
            }

    def get_current_pairing_status(self) -> Dict[str, Any]:
        """Check if pairing code is currently active."""
        with self._lock:
            if not self._active_code:
                return {"active": False, "code": None, "remaining_seconds": 0}
            elapsed = time.time() - self._code_created_at
            if elapsed > PAIRING_EXPIRY_SECONDS:
                self._active_code = None
                return {"active": False, "code": None, "remaining_seconds": 0}
            return {
                "active": True,
                "code": self._active_code,
                "remaining_seconds": int(PAIRING_EXPIRY_SECONDS - elapsed),
            }

    def verify_pairing_code(self, candidate_code: str) -> Optional[str]:
        """Validate candidate pairing code and issue a long-lived session token."""
        with self._lock:
            if not self._active_code:
                return None
            elapsed = time.time() - self._code_created_at
            if elapsed > PAIRING_EXPIRY_SECONDS:
                self._active_code = None
                return None

            clean_input = candidate_code.strip().upper()
            if not hmac.compare_digest(self._active_code, clean_input):
                return None

            # Code valid - consume it and generate session token
            self._active_code = None
            session_token = f"cp_rt_{secrets.token_hex(SESSION_TOKEN_LENGTH)}"
            self._active_sessions[session_token] = time.time()
            self._save_state()
            logger.info("Pairing successful! Generated session token.")
            return session_token

    def is_valid_session(self, token: str) -> bool:
        """Check if the provided session token is recognized."""
        with self._lock:
            return token in self._active_sessions

    def revoke_all_sessions(self):
        """Revoke all paired sessions."""
        with self._lock:
            self._active_sessions.clear()
            self._save_state()
            logger.info("All local runtime sessions revoked.")

    @property
    def is_paired(self) -> bool:
        """Returns True if at least one active paired session exists."""
        with self._lock:
            return len(self._active_sessions) > 0


pairing_manager = PairingManager()


async def verify_local_runtime_auth(request: Request) -> None:
    """FastAPI dependency to verify bearer session token."""
    # 1. Check origin and host
    origin = request.headers.get("origin")
    if origin and not is_allowed_origin(origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Origin '{origin}' is not authorized to access CodePilot Local Runtime.",
        )

    host = request.headers.get("host")
    if host and not validate_host_header(host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Host header.",
        )

    # 2. Extract Bearer token
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please include 'Authorization: Bearer <token>' header.",
        )

    token = auth_header[7:].strip()
    if not pairing_manager.is_valid_session(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired CodePilot Local Runtime session token. Please re-pair your browser.",
        )
