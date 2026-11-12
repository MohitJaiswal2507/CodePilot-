from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    database: str
    timestamp: str

@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)) -> HealthResponse:
    """Return backend health status, environment, and lightweight DB readiness."""
    db_status = "ok"
    overall_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check database readiness probe failed", exc_info=True)
        db_status = "unavailable"
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        service="CodePilot AI Backend",
        version="0.1.0",
        environment=settings.ENVIRONMENT,
        database=db_status,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

