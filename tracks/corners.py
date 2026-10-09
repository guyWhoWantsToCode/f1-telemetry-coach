"""Maps generic driving events to real corners, using static circuit metadata.

This sits between the track-agnostic event detector (corner_analysis.py, which knows nothing
about circuits) and the circuit metadata. A mapping is decided only from the event's lap
distance and the corner distance ranges, never from the event's position in the list, so an
extra lift, lock-up, spin or unmatched event cannot shift the labels of any other event.

Outcomes (CornerMatch.status):
    single     one corner               label "T11"
    complex    a declared complex       label "T3-T6"
    uncertain  the event touches several corners / the evidence is too weak (no label)
    unknown    nothing in the metadata corresponds (or the track has no corner distances)
"""

from dataclasses import dataclass

SINGLE = "single"
COMPLEX = "complex"
UNCERTAIN = "uncertain"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class MappingConfig:
    containment_tolerance_m: float = 10.0  # slack around a corner range for the minimum-speed point
    other_overlap_ratio: float = 0.5  # covering this much of another corner makes the event ambiguous
    min_dominance: float = 0.7  # share of the event's corner overlap that belongs to the chosen corner
    min_confidence: float = 0.6  # below this no label is given
    ambiguous_match_factor: float = 0.5  # confidence multiplier when the generic event match is ambiguous


@dataclass(frozen=True)
class CornerMatch:
    status: str
    label: str = None
    corners: tuple = ()
    confidence: float = 0.0
    candidates: tuple = ()  # labels that were considered when the result is uncertain
    reason: str = ""


@dataclass(frozen=True)
class _Unit:
    label: str
    corners: tuple
    lo: float
    hi: float
    is_complex: bool


def _units(meta):
    """Complexes first, then corners that are not part of one. Only units with a distance range."""
    units, in_complex = [], set()
    for cx in meta.complexes:
        if cx.range_m is not None:
            units.append(_Unit(cx.label, cx.corners, cx.range_m[0], cx.range_m[1], True))
            in_complex.update(cx.corners)
    for c in meta.corners:
        if c.range_m is not None and c.number not in in_complex:
            units.append(_Unit(f"T{c.number}", (c.number,), c.range_m[0], c.range_m[1], False))
    return units


def _overlap(a_lo, a_hi, b_lo, b_hi):
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def map_point(meta, distance_m, config=MappingConfig()):
    """The corner/complex whose range contains a single distance (e.g. a learned event), or UNKNOWN."""
    if meta is None:
        return CornerMatch(UNKNOWN, reason="no circuit metadata for this track")
    units = _units(meta)
    if not units:
        return CornerMatch(UNKNOWN, reason="circuit metadata has no corner distances")
    inside = [u for u in units if u.lo - config.containment_tolerance_m <= distance_m <= u.hi + config.containment_tolerance_m]
    if not inside:
        return CornerMatch(UNKNOWN, reason="not within any known corner range")
    if len(inside) > 1:
        return CornerMatch(UNCERTAIN, candidates=tuple(u.label for u in inside), reason="inside several corner ranges")
    u = inside[0]
    return CornerMatch(COMPLEX if u.is_complex else SINGLE, u.label, u.corners, 1.0)


def map_event(meta, start_m, end_m, min_speed_m, generic_ambiguous=False, config=MappingConfig()):
    """Map one detected event (distance range plus its minimum-speed point) to a corner."""
    if meta is None:
        return CornerMatch(UNKNOWN, reason="no circuit metadata for this track")
    units = _units(meta)
    if not units:
        return CornerMatch(UNKNOWN, reason="circuit metadata has no corner distances")

    tol = config.containment_tolerance_m
    inside = [u for u in units if u.lo - tol <= min_speed_m <= u.hi + tol]
    if not inside:
        return CornerMatch(UNKNOWN, reason="minimum-speed point is not within any known corner range")

    event_len = max(end_m - start_m, 1e-9)
    overlaps = {u.label: _overlap(start_m, end_m, u.lo, u.hi) for u in units}

    if len(inside) > 1:
        return CornerMatch(UNCERTAIN, candidates=tuple(u.label for u in inside),
                           reason="minimum-speed point is inside several corner ranges")
    chosen = inside[0]

    # Does the event substantially cover another corner as well? Then it cannot be told apart.
    spans = [u for u in units if u is not chosen
             and overlaps[u.label] / max(min(event_len, u.hi - u.lo), 1e-9) >= config.other_overlap_ratio]
    if spans:
        return CornerMatch(UNCERTAIN, candidates=tuple(u.label for u in [chosen, *spans]),
                           reason="the event spans more than one corner")

    total = sum(overlaps.values())
    dominance = overlaps[chosen.label] / total if total > 0 else 0.5
    ratio = overlaps[chosen.label] / max(min(event_len, chosen.hi - chosen.lo), 1e-9)
    confidence = 0.5 * dominance + 0.5 * min(1.0, ratio)
    if confidence < config.min_confidence or dominance < config.min_dominance:
        return CornerMatch(UNCERTAIN, candidates=(chosen.label,), confidence=round(confidence, 2),
                           reason="too little overlap with the corner")
    if generic_ambiguous:  # the label stays, but the generic event match itself was ambiguous
        confidence *= config.ambiguous_match_factor
    return CornerMatch(COMPLEX if chosen.is_complex else SINGLE, chosen.label, chosen.corners,
                       round(confidence, 2))


def map_comparison_events(meta, results, config=MappingConfig()):
    """CornerMatch for each EventComparison from corner_analysis.analyze(), in the same order.

    The reference lap's event is used for the range when there is one, else the comparison lap's.
    """
    matches = []
    for row in results:
        event = row.ref or row.cmp
        matches.append(map_event(meta, event.start_m, event.end_m, event.min_speed_m,
                                 generic_ambiguous=(row.status == "ambiguous"), config=config))
    return matches
