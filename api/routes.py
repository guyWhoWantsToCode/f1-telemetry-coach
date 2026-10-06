"""HTTP routes. Thin: validate input, call services, translate errors to status codes."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api import services
from api.storage import InvalidIdError, NotFoundError

router = APIRouter(prefix="/api")

API_VERSION = "0.1.0"


class CompareRequest(BaseModel):
    reference_id: str
    comparison_id: str
    allow_invalid: bool = False


def _store(request):
    return request.app.state.store


def _call(fn, *args, **kwargs):
    """Run a service call, mapping its errors to HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except InvalidIdError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except services.UnprocessableError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/health")
def health(request: Request):
    store = _store(request)
    return {
        "status": "ok",
        "version": API_VERSION,
        "laps_dir_exists": store.laps_dir.is_dir(),
        "comparisons_dir_exists": store.comparisons_dir.is_dir(),
    }


@router.get("/laps")
def laps(request: Request):
    return services.list_laps(_store(request))


@router.get("/laps/{lap_id}")
def lap(lap_id: str, request: Request):
    return _call(services.lap_detail, _store(request), lap_id)


@router.post("/compare")
def compare(body: CompareRequest, request: Request):
    return _call(services.run_comparison, _store(request), body.reference_id,
                 body.comparison_id, body.allow_invalid)


@router.get("/comparisons/{comparison_id}")
def comparison(comparison_id: str, request: Request):
    return _call(services.comparison_detail, _store(request), comparison_id)


@router.get("/comparisons/{comparison_id}/events")
def comparison_events(
    comparison_id: str,
    request: Request,
    min_drop: Optional[float] = Query(None, gt=0, description="minimum speed drop in km/h for an event"),
    merge_rise: Optional[float] = Query(None, gt=0, description="rise below which minima merge"),
    brake_on: Optional[float] = Query(None, ge=0, le=1, description="brake input counted as braking"),
):
    return _call(services.comparison_events, _store(request), comparison_id,
                 min_drop, merge_rise, brake_on)
