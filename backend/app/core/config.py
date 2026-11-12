import math
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env file from backend root or parent
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

_backend_dir = Path(__file__).resolve().parent.parent.parent
_raw_chroma = os.getenv("CHROMA_PERSIST_DIR", "chroma_data")
_resolved_chroma = str((_backend_dir / _raw_chroma).resolve()) if not os.path.isabs(_raw_chroma) else _raw_chroma


def parse_positive_int_env(
    raw_value: Optional[str],
    default: int,
    env_name: str,
) -> int:
    """
    Parse a positive integer environment setting.
    Missing or whitespace-only values fall back to `default`;
    non-integer or non-positive values raise ValueError explicitly.
    """
    if raw_value is None or not str(raw_value).strip():
        return default
    cleaned = str(raw_value).strip()
    try:
        parsed = int(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"Invalid integer value {raw_value!r} for {env_name}; expected a positive integer >= 1."
        ) from exc
    if parsed < 1:
        raise ValueError(
            f"Invalid value {parsed} for {env_name}; expected a positive integer >= 1."
        )
    return parsed


def parse_float_env(
    raw_value: Optional[str],
    default: float,
    env_name: str,
    *,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    """
    Parse a bounded finite float environment setting.
    Missing or whitespace-only values fall back to `default`;
    non-numeric, non-finite, or out-of-bounds values raise ValueError explicitly.
    """
    if raw_value is None or not str(raw_value).strip():
        return default
    cleaned = str(raw_value).strip()
    try:
        parsed = float(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"Invalid float value {raw_value!r} for {env_name}; expected a numeric value."
        ) from exc
    if not math.isfinite(parsed):
        raise ValueError(
            f"Invalid non-finite float value {raw_value!r} for {env_name}."
        )
    if min_value is not None and parsed < min_value:
        raise ValueError(
            f"Invalid value {parsed} for {env_name}; expected >= {min_value}."
        )
    if max_value is not None and parsed > max_value:
        raise ValueError(
            f"Invalid value {parsed} for {env_name}; expected <= {max_value}."
        )
    return parsed

class Settings(BaseModel):
    PROJECT_NAME: str = "CodePilot AI Backend"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    ALLOWED_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    # Database Configuration (Neon PostgreSQL)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    @property
    def normalized_database_url(self) -> str:
        url = self.DATABASE_URL.strip()
        if not url:
            return f"sqlite:///{(_backend_dir / 'codepilot_dev.db').resolve()}"
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    # AI & RAG Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    GEMINI_REWRITE_MODEL: str = os.getenv("GEMINI_REWRITE_MODEL", "gemini-3.5-flash-lite")
    GEMINI_ADVANCED_MODEL: str = os.getenv("GEMINI_ADVANCED_MODEL", "gemini-2.5-pro")
    GEMINI_REQUEST_TIMEOUT_MS: int = Field(
        default_factory=lambda: parse_positive_int_env(
            os.getenv("GEMINI_REQUEST_TIMEOUT_MS"),
            120000,
            "GEMINI_REQUEST_TIMEOUT_MS",
        )
    )
    MODEL_CACHE_TTL_SECONDS: int = int(os.getenv("MODEL_CACHE_TTL_SECONDS", "3600"))
    OBSERVABILITY_ENABLED: bool = os.getenv("OBSERVABILITY_ENABLED", "true").lower() in ("true", "1", "yes")
    OBSERVABILITY_LOG_PATH: str = os.getenv("OBSERVABILITY_LOG_PATH", "")
    CHROMA_PERSIST_DIR: str = _resolved_chroma
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "15"))
    DEFAULT_CHUNK_SIZE: int = int(os.getenv("DEFAULT_CHUNK_SIZE", "600"))
    DEFAULT_CHUNK_OVERLAP: int = int(os.getenv("DEFAULT_CHUNK_OVERLAP", "100"))
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))
    SECONDARY_SIMILARITY_THRESHOLD: float = Field(
        default_factory=lambda: parse_float_env(
            os.getenv("SECONDARY_SIMILARITY_THRESHOLD"),
            0.35,
            "SECONDARY_SIMILARITY_THRESHOLD",
            min_value=0.0,
            max_value=1.0,
        )
    )
    RETRIEVAL_SCORE_GAP: float = Field(
        default_factory=lambda: parse_float_env(
            os.getenv("RETRIEVAL_SCORE_GAP"),
            0.25,
            "RETRIEVAL_SCORE_GAP",
            max_value=1.0,
        )
    )

    # Neon Auth Configuration
    NEON_AUTH_URL: str = os.getenv("NEON_AUTH_URL", "https://ep-silent-sound-bdj25ci7.neonauth.us-east-2.aws.neon.tech/neondb/auth")
    NEON_JWKS_URL: str = os.getenv("NEON_JWKS_URL", "")
    NEON_AUTH_ISSUER: str = os.getenv("NEON_AUTH_ISSUER", "")
    NEON_AUTH_AUDIENCE: str = os.getenv("NEON_AUTH_AUDIENCE", "")
    ALLOW_DEV_FALLBACK_AUTH: bool = os.getenv("ALLOW_DEV_FALLBACK_AUTH", "true").lower() in ("true", "1", "yes")

    # Docker Sandbox Execution Engine (Phase 1)
    SANDBOX_ENABLED: bool = os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes")
    SANDBOX_DOCKER_PYTHON_IMAGE: str = os.getenv("SANDBOX_DOCKER_PYTHON_IMAGE", "python:3.12-slim")
    SANDBOX_DOCKER_PYTHON_DIGEST: str = os.getenv(
        "SANDBOX_DOCKER_PYTHON_DIGEST",
        "sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b",
    )
    SANDBOX_DOCKER_JAVA_IMAGE: str = os.getenv("SANDBOX_DOCKER_JAVA_IMAGE", "eclipse-temurin:21-jdk")
    SANDBOX_DOCKER_JAVA_DIGEST: str = os.getenv(
        "SANDBOX_DOCKER_JAVA_DIGEST",
        "sha256:ebfbb18d11ff163ee83b21258acf12248af48d22a0fdfdc68fa1a1516c05976a",
    )
    SANDBOX_DOCKER_CPP_IMAGE: str = os.getenv("SANDBOX_DOCKER_CPP_IMAGE", "gcc:14")
    SANDBOX_DOCKER_CPP_DIGEST: str = os.getenv(
        "SANDBOX_DOCKER_CPP_DIGEST",
        "sha256:a257536c9b7a0ee193c1880f2d691358d2c9760ef0ede3ee741aa243789743c7",
    )
    SANDBOX_DOCKER_PULL_POLICY: str = os.getenv("SANDBOX_DOCKER_PULL_POLICY", "never")
    SANDBOX_PYTHON_MEMORY_MB: int = int(os.getenv("SANDBOX_PYTHON_MEMORY_MB", "128"))
    SANDBOX_JAVA_MEMORY_MB: int = int(os.getenv("SANDBOX_JAVA_MEMORY_MB", "512"))
    SANDBOX_CPP_MEMORY_MB: int = int(os.getenv("SANDBOX_CPP_MEMORY_MB", "512"))
    SANDBOX_CPUS: float = float(os.getenv("SANDBOX_CPUS", "0.5"))
    SANDBOX_PIDS_LIMIT: int = int(os.getenv("SANDBOX_PIDS_LIMIT", "64"))
    SANDBOX_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "5"))
    SANDBOX_MAX_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_MAX_TIMEOUT_SECONDS", "30"))
    SANDBOX_COMPILE_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_COMPILE_TIMEOUT_SECONDS", "10"))
    SANDBOX_MAX_COMPILE_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_MAX_COMPILE_TIMEOUT_SECONDS", "30"))
    SANDBOX_STOP_TIMEOUT_SECONDS: int = int(os.getenv("SANDBOX_STOP_TIMEOUT_SECONDS", "1"))
    SANDBOX_MAX_SOURCE_SIZE_BYTES: int = int(os.getenv("SANDBOX_MAX_SOURCE_SIZE_BYTES", str(50 * 1024)))  # 50 KB
    SANDBOX_MAX_STDIN_SIZE_BYTES: int = int(os.getenv("SANDBOX_MAX_STDIN_SIZE_BYTES", str(64 * 1024)))  # 64 KB
    SANDBOX_MAX_OUTPUT_SIZE_BYTES: int = int(os.getenv("SANDBOX_MAX_OUTPUT_SIZE_BYTES", str(64 * 1024)))  # 64 KB
    SANDBOX_MAX_CONCURRENT_EXECUTIONS: int = int(os.getenv("SANDBOX_MAX_CONCURRENT_EXECUTIONS", "4"))
    SANDBOX_MAX_USER_CONCURRENT_EXECUTIONS: int = int(os.getenv("SANDBOX_MAX_USER_CONCURRENT_EXECUTIONS", "2"))
    SANDBOX_RATE_LIMIT_REQUESTS: int = int(os.getenv("SANDBOX_RATE_LIMIT_REQUESTS", "15"))
    SANDBOX_RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("SANDBOX_RATE_LIMIT_WINDOW_SECONDS", "60"))

    @property
    def resolved_jwks_url(self) -> str:
        if self.NEON_JWKS_URL:
            return self.NEON_JWKS_URL.strip()
        base = self.NEON_AUTH_URL.strip().rstrip("/")
        if not base.endswith("/.well-known/jwks.json"):
            return f"{base}/.well-known/jwks.json"
        return base

settings = Settings()
