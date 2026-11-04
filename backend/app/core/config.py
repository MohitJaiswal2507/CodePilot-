import os
from pydantic import BaseModel

class Settings(BaseModel):
    PROJECT_NAME: str = "CodePilot AI Backend"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    ALLOWED_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]

settings = Settings()

