"""
CodePilot AI - Isolated Docker Sandbox Runner Microservice.

A lightweight, dedicated execution service designed to run on a host machine with
access to the Docker daemon (e.g. developer workstation or private VM).
Exposes only /health and HMAC-protected /execute.
"""

import os
import logging
from fastapi import FastAPI, Depends, Request, status
from fastapi.responses import JSONResponse

from app.schemas.execution import ExecutionResult
from app.services.sandbox_service import execute_docker_code, check_docker_available
from runner.auth import verify_runner_auth
from runner.schemas import RunnerExecutionRequest, RunnerHealthResponse

MAX_REQUEST_BODY_BYTES = 256 * 1024  # 256 KB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("codepilot.runner")

runner_app = FastAPI(
    title="CodePilot Sandbox Runner Microservice",
    description="Dedicated, isolated Docker execution runner for CodePilot AI workbench.",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@runner_app.middleware("http")
async def request_body_limit_middleware(request: Request, call_next):
    """
    Enforces a strict 256 KB maximum request body limit:
    1. Early rejection if Content-Length header > 256 KB (HTTP 413) or malformed/negative (HTTP 400).
    2. Streaming byte count limit if Content-Length is missing or chunked (HTTP 413).
    3. Caches request._body to avoid re-reading the stream in downstream dependencies.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)

    # 1. Early Content-Length header inspection
    cl_header = request.headers.get("content-length")
    if cl_header is not None:
        try:
            cl = int(cl_header.strip())
            if cl < 0:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length header: negative length is not permitted."},
                )
            if cl > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": f"Request payload exceeds maximum permitted size of {MAX_REQUEST_BODY_BYTES // 1024} KB."},
                )
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Invalid Content-Length header: must be a valid integer."},
            )

    # 2. Actual bounded stream reading (guards chunked, missing CL, or spoofed CL)
    body_buf = bytearray()
    async for chunk in request.stream():
        body_buf.extend(chunk)
        if len(body_buf) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": f"Request payload exceeds maximum permitted size of {MAX_REQUEST_BODY_BYTES // 1024} KB."},
            )

    # Cache exact bytes for downstream dependency and Pydantic parsing
    request._body = bytes(body_buf)
    return await call_next(request)


@runner_app.get(
    "/health",
    response_model=RunnerHealthResponse,
    status_code=status.HTTP_200_OK,
)
def runner_health():
    """
    Public health check returning Docker daemon availability and engine version.
    Does not expose sensitive system paths or daemon URIs.
    """
    docker_ok, docker_version = check_docker_available()
    return RunnerHealthResponse(
        status="ok" if docker_ok else "degraded",
        docker_available=docker_ok,
        docker_version=docker_version if docker_ok else "unreachable",
    )


@runner_app.post(
    "/execute",
    response_model=ExecutionResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_runner_auth)],
)
def execute_sandbox_code(request: RunnerExecutionRequest):
    """
    Execute user-submitted code in a hardened, isolated Docker container.
    Guaranteed by caller to be authenticated via HMAC-SHA256 signature and fresh timestamp.
    """
    logger.info(
        "Runner received execution request: language=%s code_len=%d stdin_len=%d",
        request.language,
        len(request.code),
        len(request.stdin or ""),
    )

    result = execute_docker_code(
        code=request.code,
        language=request.language,
        stdin=request.stdin,
        custom_timeout=request.custom_timeout,
        custom_compile_timeout=request.custom_compile_timeout,
    )

    logger.info(
        "Runner finished execution: language=%s status=%s duration_ms=%.2f",
        request.language,
        result.status,
        result.duration_ms,
    )

    if result.status == "validation_error":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=result.model_dump(),
        )

    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("RUNNER_PORT", "8088"))
    logger.info("Starting CodePilot Sandbox Runner on 127.0.0.1:%d", port)
    uvicorn.run(runner_app, host="127.0.0.1", port=port)
