from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field

# Valid execution status classifications
ExecutionStatus = Literal[
    "success",
    "compilation_error",
    "compilation_timeout",
    "runtime_error",
    "timeout",
    "output_limit_exceeded",
    "infrastructure_error",
    "validation_error",
]

# Supported programming languages for the sandbox engine
SupportedLanguage = Literal["python", "java", "cpp"]

class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        min_length=1,
        max_length=51200,  # 50 KB
        description="Source code to execute inside the sandbox (max 50 KB)",
    )
    language: SupportedLanguage = Field(
        ...,
        description="Target execution runtime: 'python' (3.12), 'java' (21), or 'cpp' (GCC 14)",
    )
    stdin: Optional[str] = Field(
        default=None,
        max_length=65536,  # 64 KB
        description="Optional standard input string to pipe to the executing program (max 64 KB)",
    )

class ExecutionResult(BaseModel):
    status: ExecutionStatus = Field(
        ...,
        description="Execution status classification",
    )
    stdout: str = Field(
        default="",
        description="Standard output produced by the program (truncated if exceeding limit)",
    )
    stderr: str = Field(
        default="",
        description="Standard error output produced by the program or runtime (truncated if exceeding limit)",
    )
    compilation_error: Optional[str] = Field(
        default=None,
        description="Diagnostic compiler error messages if compilation failed (Java/C++)",
    )
    exit_code: Optional[int] = Field(
        default=None,
        description="Process exit code (0 for success, non-zero for error/timeout)",
    )
    duration_ms: float = Field(
        default=0.0,
        description="Execution duration in milliseconds (excluding compilation time)",
    )
    compile_duration_ms: Optional[float] = Field(
        default=None,
        description="Compilation duration in milliseconds for compiled languages (Java/C++)",
    )
    truncated: bool = Field(
        default=False,
        description="Whether stdout or stderr was truncated due to output buffer limits (64 KB)",
    )

