import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# Load .env file from backend root or parent
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

_backend_dir = Path(__file__).resolve().parent.parent.parent
_raw_chroma = os.getenv("CHROMA_PERSIST_DIR", "chroma_data")
_resolved_chroma = str((_backend_dir / _raw_chroma).resolve()) if not os.path.isabs(_raw_chroma) else _raw_chroma

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
    MODEL_CACHE_TTL_SECONDS: int = int(os.getenv("MODEL_CACHE_TTL_SECONDS", "3600"))
    CHROMA_PERSIST_DIR: str = _resolved_chroma
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "15"))
    DEFAULT_CHUNK_SIZE: int = int(os.getenv("DEFAULT_CHUNK_SIZE", "600"))
    DEFAULT_CHUNK_OVERLAP: int = int(os.getenv("DEFAULT_CHUNK_OVERLAP", "100"))
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))

    # Neon Auth Configuration
    NEON_AUTH_URL: str = os.getenv("NEON_AUTH_URL", "https://ep-silent-sound-bdj25ci7.neonauth.us-east-2.aws.neon.tech/neondb/auth")
    NEON_JWKS_URL: str = os.getenv("NEON_JWKS_URL", "")
    NEON_AUTH_ISSUER: str = os.getenv("NEON_AUTH_ISSUER", "")
    NEON_AUTH_AUDIENCE: str = os.getenv("NEON_AUTH_AUDIENCE", "")
    ALLOW_DEV_FALLBACK_AUTH: bool = os.getenv("ALLOW_DEV_FALLBACK_AUTH", "true").lower() in ("true", "1", "yes")

    @property
    def resolved_jwks_url(self) -> str:
        if self.NEON_JWKS_URL:
            return self.NEON_JWKS_URL.strip()
        base = self.NEON_AUTH_URL.strip().rstrip("/")
        if not base.endswith("/.well-known/jwks.json"):
            return f"{base}/.well-known/jwks.json"
        return base

settings = Settings()
