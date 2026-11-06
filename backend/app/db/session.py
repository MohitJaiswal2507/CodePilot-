import logging
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger(__name__)

db_url = settings.normalized_database_url

connect_args = {}
if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    db_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    # For PostgreSQL / Neon: pool_size and max_overflow improve concurrency
    **({"pool_size": 10, "max_overflow": 20} if not db_url.startswith("sqlite") else {})
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a SQLAlchemy database session and ensures it closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

