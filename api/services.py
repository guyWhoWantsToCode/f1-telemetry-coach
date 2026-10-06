"""Glue between the API and the existing analysis modules.

All telemetry logic stays in lap_compare.py and corner_analysis.py; this module only
loads files, calls them, and shapes the results as JSON-friendly dicts.
"""

from dataclasses import asdict, replace

from api.storage import DataStore, NotFoundError
from corner_analysis import CornerError, Thresholds, analyze, load_aligned
from lap_compare import CompareError, check_laps, compare_laps, load_lap, save_comparison, summarize

COMPARISON_SEPARATOR = "__vs__"  # how lap_compare.save_comparison names its files


class UnprocessableError(ValueError):
    """The request is valid but the laps cannot be compared / analysed."""


def format_lap_time(ms):
    if ms is None:
        return None
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest / 1000:06.3f}"


def lap_metadata(lap):
    return {
        "id": lap.path.stem,
        "filename": lap.path.name,
        "session_uid": lap.session,
        "lap_number": lap.lap_number,
        "lap_time_ms": lap.lap_time_ms,
        "lap_time": format_lap_time(lap.lap_time_ms),
        "valid": not lap.invalid,
        "samples": len(lap.distance),
        "start_distance_m": lap.start,
        "end_distance_m": lap.end,
    }


def list_laps(store):
    laps, skipped = [], []
    for path in store.lap_paths():
        try:
            laps.append(lap_metadata(load_lap(path)))
        except CompareError as e:
            skipped.append({"id": path.stem, "error": str(e)})
    laps.sort(key=lambda m: (m["session_uid"] or "", m["lap_number"]))
    return {"laps": laps, "skipped": skipped}


def lap_detail(store, lap_id):
    path = store.lap_path(lap_id)
    try:
        lap = load_lap(path)
    except CompareError as e:
        raise UnprocessableError(str(e)) from e
    return {**lap_metadata(lap), "samples_data": store.read_columns(path)}


def _summary(rows, ref, cmp_):
    s = summarize(rows)
    total = None
    if ref.lap_time_ms is not None and cmp_.lap_time_ms is not None:
        total = cmp_.lap_time_ms - ref.lap_time_ms  # official lap times, from the filenames
    point = lambda hit: None if hit is None else {"distance_m": hit[0], "delta_ms": hit[1]}
    return {
        "reference_lap_time_ms": ref.lap_time_ms,
        "comparison_lap_time_ms": cmp_.lap_time_ms,
        "total_difference_ms": total,  # positive = comparison slower; None if a time is unknown
        "final_delta_ms": s["final_delta_ms"],
        "final_distance_m": s["final_distance_m"],
        "largest_loss": point(s["loss"]),
        "largest_gain": point(s["gain"]),
        "points": len(rows),
        "start_distance_m": rows[0]["distance_m"],
        "end_distance_m": rows[-1]["distance_m"],
    }


def run_comparison(store, reference_id, comparison_id, allow_invalid=False):
    """Compare two recorded laps with lap_compare and save the aligned CSV."""
    if reference_id == comparison_id:
        raise UnprocessableError("reference and comparison must be different laps")
    ref_path, cmp_path = store.lap_path(reference_id), store.lap_path(comparison_id)
    try:
        ref, cmp_ = load_lap(ref_path), load_lap(cmp_path)
        warnings = check_laps(ref, cmp_, allow_invalid)
        rows = compare_laps(ref, cmp_)
    except CompareError as e:
        raise UnprocessableError(str(e)) from e
    path = save_comparison(rows, ref, cmp_, store.comparisons_dir)
    return {
        "id": path.stem,
        "reference": lap_metadata(ref),
        "comparison": lap_metadata(cmp_),
        "warnings": warnings,
        "summary": _summary(rows, ref, cmp_),
    }


def _laps_of(store, comparison_id):
    """The two lap files behind a saved comparison, if they still exist (else None)."""
    ref_id, sep, cmp_id = comparison_id.partition(COMPARISON_SEPARATOR)
    if not sep:
        return None, None
    laps = []
    for lap_id in (ref_id, cmp_id):
        try:
            laps.append(load_lap(store.lap_path(lap_id)))
        except (NotFoundError, CompareError, ValueError):
            laps.append(None)
    return laps[0], laps[1]


def comparison_detail(store, comparison_id):
    path = store.comparison_path(comparison_id)
    data = store.read_columns(path)
    if not data.get("distance_m"):
        raise UnprocessableError(f"comparison {comparison_id} has no rows")
    rows = [{"distance_m": d, "delta_ms": t} for d, t in zip(data["distance_m"], data["delta_ms"])]
    ref, cmp_ = _laps_of(store, comparison_id)
    out = {"id": comparison_id, "reference": ref and lap_metadata(ref),
           "comparison": cmp_ and lap_metadata(cmp_), "data": data}
    if ref and cmp_:
        out["summary"] = _summary(rows, ref, cmp_)
    else:  # lap files are gone: summarize from the aligned data alone
        s = summarize(rows)
        out["summary"] = {"final_delta_ms": s["final_delta_ms"], "final_distance_m": s["final_distance_m"],
                          "points": len(rows)}
    return out


def _event_json(ev):
    d = asdict(ev)  # dataclass fields incl. nested events
    d.update(
        comparable=ev.comparable,
        brake_start_diff_m=ev.brake_start_diff_m, min_speed_diff_kmh=ev.min_speed_diff_kmh,
        pickup_diff_m=ev.pickup_diff_m, full_throttle_diff_m=ev.full_throttle_diff_m,
    )
    return d


def comparison_events(store, comparison_id, min_drop=None, merge_rise=None, brake_on=None):
    """Run corner_analysis on a saved comparison. Optional args override thresholds."""
    path = store.comparison_path(comparison_id)
    overrides = {k: v for k, v in (("min_drop_kmh", min_drop), ("merge_rise_kmh", merge_rise),
                                   ("brake_on", brake_on)) if v is not None}
    th = replace(Thresholds(), **overrides)
    try:
        results = analyze(load_aligned(path), th)
    except CornerError as e:
        raise UnprocessableError(str(e)) from e
    return {"comparison_id": comparison_id, "thresholds": asdict(th),
            "count": len(results), "events": [_event_json(r) for r in results]}
