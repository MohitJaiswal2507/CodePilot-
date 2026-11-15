import os
import logging
from typing import Generator, Optional
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from app.core.config import settings

logger = logging.getLogger(__name__)


def is_serverless_environment() -> bool:
    """
    Determine if running in a serverless environment (e.g. Vercel, AWS Lambda)
    or if NullPool is explicitly requested for PostgreSQL connections.
    """
    return (
        settings.is_serverless
        or os.getenv("DB_POOL_TYPE", "").lower() == "nullpool"
    )


def create_db_engine(database_url: Optional[str] = None) -> Engine:
    """
    Create a SQLAlchemy engine configured appropriately for the target environment.
    - Serverless / Production PostgreSQL: uses NullPool to prevent connection exhaustion.
    - Local / Non-serverless PostgreSQL: uses QueuePool with pool_size=10, max_overflow=20.
    - SQLite: disables check_same_thread for thread-safety in dev/test.
    """
    url = (database_url or settings.normalized_database_url).strip()
    connect_args = {}
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        connect_args["check_same_thread"] = False

    engine_kwargs = {
        "connect_args": connect_args,
        "pool_pre_ping": True,
    }

    if not is_sqlite:
        if is_serverless_environment():
            logger.info("Configuring SQLAlchemy with NullPool for serverless PostgreSQL connection.")
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs["pool_size"] = 10
            engine_kwargs["max_overflow"] = 20

    return create_engine(url, **engine_kwargs)


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a SQLAlchemy database session and ensures it closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
