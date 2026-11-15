"""
Request and Response Schemas for CodePilot Runner Microservice.
"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.execution import SupportedLanguage


class RunnerExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        min_length=1,
        max_length=51200,  # 50 KB
        description="Source code to execute inside the sandbox (max 50 KB)",
    )
    language: SupportedLanguage = Field(
        ...,
        description="Target execution runtime: 'python', 'java', or 'cpp'",
    )
    stdin: Optional[str] = Field(
        default=None,
        max_length=65536,  # 64 KB
        description="Optional standard input data (max 64 KB)",
    )
    custom_timeout: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Optional execution timeout override in seconds",
    )
    custom_compile_timeout: Optional[int] = Field(
        default=None,
        ge=1,
        le=30,
        description="Optional compilation timeout override in seconds",
    )


class RunnerHealthResponse(BaseModel):
    status: str
    docker_available: bool
    docker_version: str
