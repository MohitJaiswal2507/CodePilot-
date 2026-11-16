"""
CodePilot Local Runtime Configuration.
"""

import os
import sys
from pathlib import Path

# Runtime Version
VERSION = "1.0.0"

# Network Binding (Strict localhost only)
HOST = "127.0.0.1"
DEFAULT_PORT = 8088

# Storage directories for runtime state & secrets
if sys.platform == "win32":
    LOCAL_APP_DATA = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    DATA_DIR = Path(LOCAL_APP_DATA) / "CodePilot" / "runtime"
else:
    DATA_DIR = Path.home() / ".codepilot" / "runtime"

DATA_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = DATA_DIR / "state.json"
SECRET_FILE = DATA_DIR / "runner_secret.key"

# Trusted origins for CORS and Private Network Access
ALLOWED_ORIGIN_PATTERNS = [
    r"^https:\/\/codepilot-frontend(-[a-zA-Z0-9_-]+)?\.vercel\.app$",
    r"^https:\/\/codepilot-frontend\.vercel\.app$",
    r"^http:\/\/localhost(:\d+)?$",
    r"^http:\/\/127\.0\.0\.1(:\d+)?$",
]

# Supported language images
REQUIRED_IMAGES = {
    "python": "python:3.12-slim",
    "java": "eclipse-temurin:21-jdk",
    "cpp": "gcc:14",
}
