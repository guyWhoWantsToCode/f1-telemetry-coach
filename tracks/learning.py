"""Learning typical driving-event locations on one circuit from many laps.

Pure functions over plain dicts (the JSON shape stored in the track profile); no file access.

A *learned event* keeps the observed lap-distance values of one recurring driving event
(its minimum-speed point and, where braking, its braking point) and summarises them with a
median and a robust spread, so one odd lap cannot move it:

  * an observation joins the nearest learned event within `match_radius_m`;
  * once an event is established (>= `min_established` observations) an observation that
    is too far from its median (`outlier_*`) is rejected and only counted;
  * an observation too far from every learned event starts a new low-confidence candidate
    (a spin or an extra lift becomes its own candidate and never drags a real event);
  * rarely seen candidates are pruned once there is enough history.

Learned data is never merged into the static circuit metadata.
"""

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class LearningConfig:
    match_radius_m: float = 60.0  # observation joins a learned event this close to its median
    min_established: int = 3  # observations before outlier rejection starts
    outlier_floor_m: float = 25.0  # never reject closer than this to the median
    outlier_mad_k: float = 4.0  # ... or within this many robust standard deviations
    max_observations: int = 50  # most recent values kept per event
    maturity_n: int = 4  # observations for full confidence
    spread_scale_m: float = 15.0  # a spread of this many metres halves the consistency score
    prune_after_laps: int = 10  # start pruning rarely seen candidates after this many laps
    prune_min_presence: float = 0.15
    max_lap_time_ratio: float = 1.15  # laps slower than PB * this are not learned from


@dataclass(frozen=True)
class ObservedEvent:
    min_speed_m: float
    brake_start_m: float = None


def robust_stats(values):
    """(median, spread). Spread is the median absolute deviation scaled to a standard deviation."""
    median = statistics.median(values)
    mad = statistics.median(abs(v - median) for v in values)
    return median, 1.4826 * mad


def _summary(values):
    if not values:
        return None
    median, spread = robust_stats(values)
    return {"median": round(median, 1), "spread": round(spread, 1), "n": len(values)}


def _new_event(event_id):
    return {"id": event_id, "observations": {"min_speed_m": [], "brake_start_m": []},
            "outliers_rejected": 0}


def _refresh(event, laps_learned, cfg):
    """Recompute the derived statistics and confidence of one learned event."""
    obs = event["observations"]
    event["min_speed_m"] = _summary(obs["min_speed_m"])
    event["brake_start_m"] = _summary(obs["brake_start_m"])
    n = len(obs["min_speed_m"])
    spread = event["min_speed_m"]["spread"] if n else 0.0
    presence = min(1.0, n / max(laps_learned, 1))
    consistency = 1.0 / (1.0 + spread / cfg.spread_scale_m)
    maturity = min(1.0, n / cfg.maturity_n)
    event["observations_count"] = n
    event["confidence"] = round(presence * consistency * maturity, 2)


def update_learned_events(events, laps_learned, observed, cfg=LearningConfig()):
    """Fold one lap's detected events into the learned events.

    `events` is the stored list (not modified); `laps_learned` is how many laps were learned
    from before this one. Returns (new_events, report) where the report lists, per observation,
    what happened: "joined", "outlier", or "new".
    """
    events = [dict(e, observations={k: list(v) for k, v in e["observations"].items()}) for e in events]
    next_id = max((e["id"] for e in events), default=0) + 1
    used, report = set(), []

    for obs in sorted(observed, key=lambda o: o.min_speed_m):
        candidates = [e for e in events if e["id"] not in used and e["min_speed_m"]
                      and abs(e["min_speed_m"]["median"] - obs.min_speed_m) <= cfg.match_radius_m]
        if not candidates:
            event = _new_event(next_id)
            next_id += 1
            events.append(event)
            outcome = "new"
        else:
            event = min(candidates, key=lambda e: abs(e["min_speed_m"]["median"] - obs.min_speed_m))
            n = len(event["observations"]["min_speed_m"])
            median, spread = robust_stats(event["observations"]["min_speed_m"])
            limit = max(cfg.outlier_floor_m, cfg.outlier_mad_k * spread)
            if n >= cfg.min_established and abs(obs.min_speed_m - median) > limit:
                event["outliers_rejected"] += 1
                used.add(event["id"])
                report.append((obs, "outlier", event["id"]))
                continue
            outcome = "joined"
        used.add(event["id"])
        o = event["observations"]
        o["min_speed_m"] = (o["min_speed_m"] + [obs.min_speed_m])[-cfg.max_observations:]
        if obs.brake_start_m is not None:
            o["brake_start_m"] = (o["brake_start_m"] + [obs.brake_start_m])[-cfg.max_observations:]
        event["min_speed_m"] = _summary(o["min_speed_m"])  # keeps matching for the rest of this lap
        report.append((obs, outcome, event["id"]))

    total = laps_learned + 1
    for event in events:
        _refresh(event, total, cfg)
    if total >= cfg.prune_after_laps:
        events = [e for e in events if e["observations_count"] / total >= cfg.prune_min_presence]
    events.sort(key=lambda e: e["min_speed_m"]["median"])
    return events, report
