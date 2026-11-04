from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    timestamp: str

@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return backend health status and basic service metadata."""
    return HealthResponse(
        status="healthy",
        service="CodePilot AI Backend",
        version="0.1.0",
        environment="development",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

