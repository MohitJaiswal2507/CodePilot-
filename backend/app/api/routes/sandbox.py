"""
Authenticated Docker Sandbox Execution API Route.

Exposes POST /api/v1/sandbox/execute, delegating isolated execution strictly to
`sandbox_service.execute_code` while enforcing authentication, concurrency quotas,
rate limiting, server-controlled limits, and sanitized error responses.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.auth import AuthenticatedUser, get_current_user
from app.schemas.execution import ExecutionRequest, ExecutionResult
from app.services.sandbox_limiter import SandboxRateLimitError, sandbox_limiter
from app.services.sandbox_service import execute_code

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["Code Execution Sandbox"])


@router.post("/execute", response_model=ExecutionResult, status_code=status.HTTP_200_OK)
def execute_sandbox_code(
    payload: ExecutionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Execute user-submitted Python, Java, or C++ code inside an isolated Docker sandbox.
    Requires verified authentication; all container images, quotas, and timeouts are server-controlled.
    """
    owner_user_id = str(current_user.user_id).strip()
    if not owner_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is missing or invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    code_bytes_len = len(payload.code.encode("utf-8"))
    stdin_bytes_len = len(payload.stdin.encode("utf-8")) if payload.stdin is not None else 0

    try:
        with sandbox_limiter.acquire(owner_user_id):
            logger.info(
                "Sandbox execute started: user_id=%s language=%s code_bytes=%d stdin_bytes=%d",
                owner_user_id,
                payload.language,
                code_bytes_len,
                stdin_bytes_len,
            )
            result = execute_code(
                code=payload.code,
                language=payload.language,
                stdin=payload.stdin,
            )
    except SandboxRateLimitError as limit_err:
        logger.warning(
            "Sandbox limit rejected request: user_id=%s detail=%s",
            owner_user_id,
            limit_err.detail,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=limit_err.detail,
            headers={"Retry-After": str(limit_err.retry_after_seconds)},
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected failure executing sandbox code for user_id=%s language=%s",
            owner_user_id,
            payload.language,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Code execution failed due to an unexpected internal error.",
        )

    logger.info(
        "Sandbox execute finished: user_id=%s language=%s status=%s duration_ms=%.2f",
        owner_user_id,
        payload.language,
        result.status,
        result.duration_ms,
    )

    if result.status == "validation_error":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=result.model_dump(),
        )

    if result.status == "infrastructure_error":
        # Strip host paths, Docker daemon URIs, or image tags/digests before returning to clients
        sanitized = ExecutionResult(
            status="infrastructure_error",
            stdout="",
            stderr="Code execution sandbox service is temporarily unavailable.",
            compilation_error=None,
            exit_code=None,
            duration_ms=result.duration_ms,
            compile_duration_ms=None,
            truncated=False,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=sanitized.model_dump(),
        )

    return result

