"""Track endpoints: known circuits, per-circuit history and static corners, and manual lap
assignment for laps recorded before track identity existed."""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.storage import InvalidIdError, NotFoundError
from tracks.service import TrackConflictError, UnknownTrackError

router = APIRouter(prefix="/api")

_SESSION_UID_RE = re.compile(r"^[0-9a-f]{16}$")


class AssignTrackRequest(BaseModel):
    track_id: int


def _tracks(request):
    return request.app.state.tracks


def _active_track_id(request):
    return request.app.state.recording.status()["active_track_id"]


def _assign(call):
    try:
        return call()
    except InvalidIdError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (NotFoundError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=f"not found: {e}") from e
    except UnknownTrackError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except TrackConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/tracks")
def list_tracks(request: Request):
    """Circuits with a saved profile (for the track selector), plus the live circuit's ID."""
    return _tracks(request).list_tracks(_active_track_id(request))


@router.get("/tracks/{track_id}")
def track_detail(track_id: int, request: Request):
    detail = _tracks(request).track_detail(track_id, _active_track_id(request))
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no saved profile for track {track_id}")
    return detail


@router.get("/tracks/{track_id}/corners")
def track_corners(track_id: int, request: Request):
    """Static circuit metadata: corners, complexes and how complete it is. Not learned data."""
    corners = _tracks(request).corners(track_id)
    if not corners["known"]:
        raise HTTPException(status_code=404, detail=f"track {track_id} is not a known F1 25 circuit")
    return corners


@router.get("/tracks/{track_id}/map")
def track_map(track_id: int, request: Request):
    """The stored circuit trace: the driver's path (not a track centerline) built from valid laps.
    `available` is false, with a reason, when there is no usable position data."""
    tracks = _tracks(request)
    if tracks.profiles.get(track_id) is None:
        raise HTTPException(status_code=404, detail=f"no saved profile for track {track_id}")
    return tracks.get_map(track_id)


@router.get("/laps/{lap_id}/path")
def lap_path(lap_id: str, request: Request):
    """One lap's own recorded racing line (world X/Y/Z by lap distance), or why it has none."""
    store = request.app.state.store

    def call():
        store.lap_path(lap_id)  # validates the id and that the lap exists
        return _tracks(request).lap_path(lap_id)

    return _assign(call)


@router.get("/catalog/tracks")
def track_catalog(request: Request):
    """Every F1 25 circuit a lap can be assigned to."""
    return {"tracks": _tracks(request).catalog()}


@router.post("/laps/{lap_id}/track")
def assign_lap_track(lap_id: str, body: AssignTrackRequest, request: Request):
    """Manually assign a lap with no known circuit. Persisted beside the lap; the telemetry file
    is not modified. A circuit reported by the game itself cannot be overridden."""
    store = request.app.state.store

    def call():
        store.lap_path(lap_id)  # validates the id and that the lap exists
        return _tracks(request).assign_lap(lap_id, body.track_id)

    return _assign(call)


@router.post("/sessions/{session_uid}/track")
def assign_session_track(session_uid: str, body: AssignTrackRequest, request: Request):
    """Assign every untagged lap of one recorded session to a circuit."""
    if not _SESSION_UID_RE.match(session_uid):
        raise HTTPException(status_code=400, detail="session id must be 16 hexadecimal characters")
    return _assign(lambda: _tracks(request).assign_session(session_uid, body.track_id))
