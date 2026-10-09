"""FastAPI application factory.

Start it from the project root:
    uvicorn api.main:app --reload
Interactive docs are served at http://127.0.0.1:8000/docs
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.recording import RecordingService
from api.routes import API_VERSION, router
from api.track_routes import router as track_router
from api.storage import DataStore
from tracks.service import TrackService
from udp_listener import HOST as UDP_HOST, PORT as UDP_PORT

# Origins of a local Vite dev server (5173) and preview server (4173).
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:4173", "http://127.0.0.1:4173",
]


def cors_origins():
    """Defaults, or a comma-separated override in F1_CORS_ORIGINS."""
    env = os.environ.get("F1_CORS_ORIGINS")
    return [o.strip() for o in env.split(",") if o.strip()] if env else DEFAULT_CORS_ORIGINS


def create_app(data_dir=None, udp_port=None, metadata_dir=None):
    """Build the app. data_dir defaults to <project>/data (or the F1_DATA_DIR variable).

    udp_port overrides the telemetry port (the existing 20777); tests pass 0.
    metadata_dir overrides the static circuit metadata folder (track_metadata/, or F1_METADATA_DIR).
    """
    store = DataStore(data_dir or os.environ.get("F1_DATA_DIR"))
    tracks = TrackService(store.data_dir, metadata_dir or os.environ.get("F1_METADATA_DIR"))
    recording = RecordingService(store.laps_dir, host=UDP_HOST, tracks=tracks, positions_dir=store.positions_dir,
                                 port=UDP_PORT if udp_port is None else udp_port)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            recording.stop()  # release the UDP port when the server shuts down

    app = FastAPI(title="F1 Telemetry Coach API", version=API_VERSION, lifespan=lifespan)
    app.state.store = store
    app.state.recording = recording
    app.state.tracks = tracks
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(track_router)
    return app


app = create_app()
