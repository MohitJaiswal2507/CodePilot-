"""
CodePilot Local Runtime - HTTP Server.

A lightweight, dedicated local daemon that executes code inside Docker
on the user's local machine, communicating securely with CodePilot web client.
"""

import sys
import platform
import logging
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from fastapi import FastAPI, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from runtime.config import VERSION, HOST, DEFAULT_PORT
from runtime.auth import (
    is_allowed_origin,
    validate_host_header,
    pairing_manager,
    verify_local_runtime_auth,
)
from runtime.docker_engine import (
    check_docker_available,
    get_installed_images,
    pull_docker_image,
    execute_docker_code,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("codepilot.local_runtime")

runtime_app = FastAPI(
    title="CodePilot Local Runtime",
    description="Local Docker execution microservice for CodePilot developers.",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

MAX_BODY_BYTES = 256 * 1024  # 256 KB


# ==============================================================================
# Security Middlewares: Private Network Access (PNA), CORS, Host & Body Bounds
# ==============================================================================

@runtime_app.middleware("http")
async def security_and_pna_middleware(request: Request, call_next):
    """
    Handles Private Network Access (PNA), trusted origins, Host header, and body size limits.
    Crucial for allowing https://codepilot-frontend.vercel.app to query http://127.0.0.1:8088.
    """
    origin = request.headers.get("origin")
    host = request.headers.get("host")

    # Guard DNS rebinding
    if host and not validate_host_header(host):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid Host header."},
        )

    # Handle OPTIONS preflight requests for CORS & PNA
    if request.method == "OPTIONS":
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        if origin and is_allowed_origin(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CodePilot-Client, Accept"
            response.headers["Access-Control-Max-Age"] = "86400"
        if request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    # Guard body size limits
    cl_header = request.headers.get("content-length")
    if cl_header:
        try:
            if int(cl_header.strip()) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Payload exceeds 256 KB limit."},
                )
        except ValueError:
            pass

    response = await call_next(request)

    # Attach CORS & PNA headers to response
    if origin and is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"

    return response


# ==============================================================================
# Request & Response Schemas
# ==============================================================================

class PairConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairing_code: str = Field(..., min_length=4, max_length=16)


class LocalExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=1, max_length=51200)
    language: str = Field(..., description="python, java, or cpp")
    stdin: Optional[str] = Field(default=None, max_length=65536)
    custom_timeout: Optional[int] = Field(default=None, ge=1, le=30)
    custom_compile_timeout: Optional[int] = Field(default=None, ge=1, le=30)


class PullImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(..., min_length=1, max_length=100)


# ==============================================================================
# Public Discovery & Health Endpoints
# ==============================================================================

@runtime_app.get("/health")
def runtime_health():
    """Unauthenticated quick health check for browser discovery."""
    docker_ok, docker_ver = check_docker_available()
    pairing_status = pairing_manager.get_current_pairing_status()
    return {
        "status": "ok",
        "service": "CodePilot Local Runtime",
        "version": VERSION,
        "docker_available": docker_ok,
        "docker_version": docker_ver if docker_ok else None,
        "paired": pairing_manager.is_paired,
        "pairing_active": pairing_status["active"],
        "os": sys.platform,
    }


@runtime_app.get("/version")
def runtime_version():
    """Return runtime build and version information."""
    return {
        "version": VERSION,
        "build": "desktop-x64",
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "supported_languages": ["python", "java", "cpp"],
    }


@runtime_app.get("/status")
def runtime_status():
    """Detailed runtime status including Docker and image availability."""
    docker_ok, docker_ver = check_docker_available()
    images_info = get_installed_images() if docker_ok else {"images": {}, "all_ready": False, "missing": []}
    return {
        "runtime_version": VERSION,
        "os": platform.system(),
        "arch": platform.machine(),
        "docker": {
            "available": docker_ok,
            "version": docker_ver if docker_ok else None,
        },
        "languages": images_info,
        "paired": pairing_manager.is_paired,
    }


# ==============================================================================
# Pairing Handshake Endpoints
# ==============================================================================

@runtime_app.post("/pair/request")
def request_pairing():
    """Initiates pairing by generating a secure 6-digit code with 5-minute expiry."""
    result = pairing_manager.generate_pairing_code()
    return result


@runtime_app.post("/pair/confirm")
def confirm_pairing(req: PairConfirmRequest):
    """Validates pairing code and issues a persistent local session token."""
    token = pairing_manager.verify_pairing_code(req.pairing_code)
    if not token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired pairing code. Please generate a new code."},
        )
    return {
        "status": "paired",
        "session_token": token,
        "message": "Successfully paired CodePilot Local Runtime with browser.",
    }


@runtime_app.post("/disconnect")
def disconnect_runtime(dependencies=[Depends(verify_local_runtime_auth)]):
    """Revokes active paired session."""
    pairing_manager.revoke_all_sessions()
    return {"status": "disconnected", "message": "All active browser pairings revoked."}


# ==============================================================================
# Docker Management Endpoints (Image Setup)
# ==============================================================================

@runtime_app.get("/docker/images")
def list_docker_images():
    """Check required language images availability."""
    return get_installed_images()


@runtime_app.post("/docker/pull")
def pull_image(req: PullImageRequest):
    """Pull required language image on demand."""
    success, message = pull_docker_image(req.image)
    if not success:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": message},
        )
    return {"status": "pulled", "image": req.image, "message": message}


# ==============================================================================
# Authenticated Execution Endpoint
# ==============================================================================

@runtime_app.post(
    "/execute",
    dependencies=[Depends(verify_local_runtime_auth)],
)
def execute_code(req: LocalExecuteRequest):
    """Execute code locally in an isolated Docker container with authentication."""
    logger.info("Executing local code: language=%s code_len=%d", req.language, len(req.code))
    result = execute_docker_code(
        code=req.code,
        language=req.language,
        stdin=req.stdin,
        custom_timeout=req.custom_timeout,
        custom_compile_timeout=req.custom_compile_timeout,
    )
    return result


def start_runtime(port: int = DEFAULT_PORT):
    """Launch the local runtime server with Uvicorn."""
    import uvicorn
    logger.info("Starting CodePilot Local Runtime on %s:%d", HOST, port)
    uvicorn.run(runtime_app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    start_runtime()
