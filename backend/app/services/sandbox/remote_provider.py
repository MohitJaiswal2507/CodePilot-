"""
Remote HTTP Sandbox Execution Provider.

Delegates code execution from serverless gateways (e.g. Vercel Preview) to an isolated,
self-hosted CodePilot Docker runner microservice over HTTPS using HMAC-SHA256 signed requests,
timestamp verification, and replay protection.
"""

import json
import time
import hmac
import hashlib
import logging
import urllib.request
import urllib.error
from typing import Optional, Tuple

from app.core.config import settings
from app.schemas.execution import ExecutionResult, SupportedLanguage
from app.services.sandbox.base import BaseSandboxProvider

logger = logging.getLogger(__name__)


def generate_hmac_signature(secret: str, timestamp: str, body_bytes: bytes) -> str:
    """Compute HMAC-SHA256 signature over timestamp and raw request body."""
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body_bytes,
        hashlib.sha256,
    )
    return mac.hexdigest()


class RemoteHttpSandboxProvider(BaseSandboxProvider):
    """
    HTTP client provider that forwards sandbox execution requests to a remote
    CodePilot Runner microservice over a secure private tunnel or dedicated network.
    """

    def check_available(self) -> Tuple[bool, str]:
        """Query the remote runner's /health endpoint."""
        runner_url = settings.SANDBOX_RUNNER_URL
        if not runner_url:
            return False, "SANDBOX_RUNNER_URL is not configured."

        health_url = f"{runner_url}/health"
        try:
            req = urllib.request.Request(
                health_url,
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    docker_ok = data.get("docker_available", False)
                    version = data.get("docker_version", "unknown")
                    if docker_ok:
                        return True, f"Remote runner healthy (Docker: {version})"
                    return False, f"Remote runner degraded: {version}"
                return False, f"Remote runner returned HTTP {response.status}"
        except Exception as exc:
            return False, f"Failed to reach remote runner at {health_url}: {str(exc)}"

    def execute(
        self,
        code: str,
        language: SupportedLanguage,
        stdin: Optional[str] = None,
        custom_timeout: Optional[int] = None,
        custom_compile_timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Send an HMAC-signed execution request to the remote runner microservice.
        """
        wall_start = time.perf_counter()

        if not settings.SANDBOX_ENABLED:
            return ExecutionResult(
                status="infrastructure_error",
                stderr="Code execution sandbox is disabled by server configuration.",
                exit_code=1,
                duration_ms=0.0,
            )

        runner_url = settings.SANDBOX_RUNNER_URL
        runner_secret = settings.SANDBOX_RUNNER_SECRET

        if not runner_url:
            logger.error("RemoteHttpSandboxProvider invoked but SANDBOX_RUNNER_URL is not set.")
            return ExecutionResult(
                status="infrastructure_error",
                stderr="Remote sandbox runner URL is not configured.",
                exit_code=1,
                duration_ms=0.0,
            )

        if not runner_secret:
            logger.error("RemoteHttpSandboxProvider invoked but SANDBOX_RUNNER_SECRET is not set.")
            return ExecutionResult(
                status="infrastructure_error",
                stderr="Remote sandbox runner secret is not configured.",
                exit_code=1,
                duration_ms=0.0,
            )

        # 1. Pre-validate input constraints locally to avoid wasted remote calls
        code_raw = code or ""
        if not code_raw.strip():
            return ExecutionResult(
                status="validation_error",
                stderr="Source code cannot be empty.",
                exit_code=1,
                duration_ms=0.0,
            )

        clean_lang = str(language).lower().strip()
        if clean_lang not in ("python", "java", "cpp"):
            return ExecutionResult(
                status="validation_error",
                stderr=f"Unsupported language '{language}'. Supported languages: python, java, cpp.",
                exit_code=1,
                duration_ms=0.0,
            )

        code_bytes = code_raw.encode("utf-8")
        max_source_bytes = settings.SANDBOX_MAX_SOURCE_SIZE_BYTES
        if len(code_bytes) > max_source_bytes:
            return ExecutionResult(
                status="validation_error",
                stderr=(
                    f"Source code exceeds maximum permitted size of {max_source_bytes // 1024} KB "
                    f"(got {len(code_bytes)} bytes)."
                ),
                exit_code=1,
                duration_ms=0.0,
            )

        stdin_bytes = (stdin or "").encode("utf-8")
        max_stdin_bytes = settings.SANDBOX_MAX_STDIN_SIZE_BYTES
        if len(stdin_bytes) > max_stdin_bytes:
            return ExecutionResult(
                status="validation_error",
                stderr=(
                    f"Standard input exceeds maximum permitted size of {max_stdin_bytes // 1024} KB "
                    f"(got {len(stdin_bytes)} bytes)."
                ),
                exit_code=1,
                duration_ms=0.0,
            )

        # 2. Build payload (strictly zero backend environment variables or user credentials)
        payload = {
            "code": code,
            "language": clean_lang,
            "stdin": stdin,
            "custom_timeout": custom_timeout,
            "custom_compile_timeout": custom_compile_timeout,
        }
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        # 3. Formulate HMAC-SHA256 signature with UTC timestamp
        timestamp = str(int(time.time()))
        signature = generate_hmac_signature(runner_secret, timestamp, body_bytes)

        execute_endpoint = f"{runner_url}/execute"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-CodePilot-Timestamp": timestamp,
            "X-CodePilot-Signature": signature,
        }

        timeout_seconds = settings.SANDBOX_RUNNER_TIMEOUT_SECONDS

        try:
            req = urllib.request.Request(
                execute_endpoint,
                data=body_bytes,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                resp_bytes = response.read()
                wall_ms = (time.perf_counter() - wall_start) * 1000.0
                resp_data = json.loads(resp_bytes.decode("utf-8"))
                result = ExecutionResult(**resp_data)
                if result.duration_ms <= 0:
                    result.duration_ms = wall_ms
                return result

        except urllib.error.HTTPError as http_err:
            wall_ms = (time.perf_counter() - wall_start) * 1000.0
            error_body = http_err.read().decode("utf-8", errors="replace")
            logger.warning(
                "Remote sandbox runner HTTP error: status=%d body=%s",
                http_err.code,
                error_body[:300],
            )

            if http_err.code in (401, 403):
                return ExecutionResult(
                    status="infrastructure_error",
                    stderr="Remote sandbox runner authentication failed. Please verify runner secret.",
                    exit_code=1,
                    duration_ms=wall_ms,
                )

            if http_err.code == 422:
                try:
                    parsed = json.loads(error_body)
                    if isinstance(parsed, dict) and parsed.get("status") == "validation_error":
                        return ExecutionResult(**parsed)
                    detail = parsed.get("detail", "Validation failed for execution request.") if isinstance(parsed, dict) else error_body
                    return ExecutionResult(
                        status="validation_error",
                        stderr=str(detail),
                        exit_code=1,
                        duration_ms=wall_ms,
                    )
                except Exception:
                    return ExecutionResult(
                        status="validation_error",
                        stderr="Validation failed for execution request.",
                        exit_code=1,
                        duration_ms=wall_ms,
                    )

            # Try parsing structured ExecutionResult if runner returned 503 with infrastructure_error
            try:
                parsed = json.loads(error_body)
                if isinstance(parsed, dict) and "status" in parsed:
                    return ExecutionResult(**parsed)
            except Exception:
                pass

            return ExecutionResult(
                status="infrastructure_error",
                stderr=f"Remote sandbox runner returned HTTP {http_err.code}.",
                exit_code=http_err.code,
                duration_ms=wall_ms,
            )

        except (urllib.error.URLError, TimeoutError, OSError) as net_err:
            wall_ms = (time.perf_counter() - wall_start) * 1000.0
            logger.error("Failed to connect to remote sandbox runner: %s", net_err)
            return ExecutionResult(
                status="infrastructure_error",
                stderr="Code execution sandbox runner is currently offline or unreachable.",
                exit_code=1,
                duration_ms=wall_ms,
            )
        except Exception as exc:
            wall_ms = (time.perf_counter() - wall_start) * 1000.0
            logger.exception("Unexpected error communicating with remote sandbox runner: %s", exc)
            return ExecutionResult(
                status="infrastructure_error",
                stderr="Unexpected error communicating with the code execution runner.",
                exit_code=1,
                duration_ms=wall_ms,
            )
