"""FastAPI application factory.

Start it from the project root:
    uvicorn api.main:app --reload
Interactive docs are served at http://127.0.0.1:8000/docs
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import API_VERSION, router
from api.storage import DataStore

# Origins of a local Vite dev server (5173) and preview server (4173).
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:4173", "http://127.0.0.1:4173",
]


def cors_origins():
    """Defaults, or a comma-separated override in F1_CORS_ORIGINS."""
    env = os.environ.get("F1_CORS_ORIGINS")
    return [o.strip() for o in env.split(",") if o.strip()] if env else DEFAULT_CORS_ORIGINS


def create_app(data_dir=None):
    """Build the app. data_dir defaults to <project>/data (or the F1_DATA_DIR variable)."""
    app = FastAPI(title="F1 Telemetry Coach API", version=API_VERSION)
    app.state.store = DataStore(data_dir or os.environ.get("F1_DATA_DIR"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
