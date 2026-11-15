"""
Vercel Serverless Function Entry Point for CodePilot AI.

Exposes the ASGI FastAPI application for the Vercel Python Runtime.
Ensures correct sys.path configuration so that the application modules
in 'app' are discoverable in serverless execution environments.
"""

import sys
from pathlib import Path

# Ensure the backend root directory is on sys.path
_backend_root = str(Path(__file__).resolve().parent.parent)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from app.main import app  # noqa: E402, F401
