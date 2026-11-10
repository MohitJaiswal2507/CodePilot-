from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import health, tutor, conversations, reviewer, sandbox
from app.core.config import settings
from app.db.session import engine
from app.db.base import Base
import app.models # Register all models

# Ensure tables exist
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["System"])
app.include_router(tutor.router, prefix="/api", tags=["AI Learning Tutor"])
app.include_router(conversations.router, prefix="/api", tags=["Conversations"])
app.include_router(reviewer.router, prefix="/api", tags=["AI Code Reviewer"])
app.include_router(sandbox.router, prefix="/api/v1", tags=["Code Execution Sandbox"])

@app.get("/")
def root():
    return {
        "message": "Welcome to CodePilot AI API",
        "docs": "/docs",
        "health": "/api/health",
        "tutor": "/api/tutor",
        "conversations": "/api/conversations",
        "reviewer": "/api/reviewer",
        "sandbox": "/api/v1/sandbox",
    }
