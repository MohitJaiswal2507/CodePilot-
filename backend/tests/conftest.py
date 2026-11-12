import atexit
import os
from pathlib import Path
import tempfile
import pytest

_TEMP_DB_DIR: tempfile.TemporaryDirectory[str] | None = None

_explicit_db_url = os.environ.get("DATABASE_URL")
if _explicit_db_url is not None and _explicit_db_url.strip():
    if not _explicit_db_url.strip().lower().startswith("sqlite"):
        _scheme = _explicit_db_url.strip().split("://", 1)[0]
        raise RuntimeError(
            f"Refusing to run pytest with non-SQLite DATABASE_URL ({_scheme}://...). "
            "Unset DATABASE_URL or provide a sqlite:// URL."
        )
else:
    _TEMP_DB_DIR = tempfile.TemporaryDirectory(prefix="codepilot_pytest_db_")
    _temp_db_path = (Path(_TEMP_DB_DIR.name) / "test.db").as_posix()
    os.environ["DATABASE_URL"] = f"sqlite:///{_temp_db_path}"

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401 - register all SQLAlchemy models on Base.metadata


def _cleanup_temp_db_dir() -> None:
    if _TEMP_DB_DIR is not None:
        try:
            engine.dispose()
        except Exception:
            pass
        _TEMP_DB_DIR.cleanup()


if _TEMP_DB_DIR is not None:
    atexit.register(_cleanup_temp_db_dir)


@pytest.fixture(scope="session", autouse=True)
def initialize_test_database():
    """Initialize SQLite test schema explicitly without relying on app.main import side effects."""
    if not settings.normalized_database_url.startswith("sqlite"):
        raise RuntimeError(
            "Refusing to run automatic test schema creation against a non-SQLite database."
        )
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")

