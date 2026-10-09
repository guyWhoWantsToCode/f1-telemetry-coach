"""Read-only access to static circuit metadata (track_metadata/).

Static facts about real circuits. Never written by the application and never changed by how
a lap was driven. See track_metadata/README.md for the schema.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_METADATA_DIR = Path(__file__).resolve().parent.parent / "track_metadata"


class MetadataError(ValueError):
    """A metadata file is malformed."""


@dataclass(frozen=True)
class CatalogEntry:
    track_id: int
    name: str  # the game's label (F1 25 spec appendix)
    circuit_name: str = None  # friendly circuit name, where known

    @property
    def display_name(self):
        return self.circuit_name or self.name


@dataclass(frozen=True)
class Corner:
    number: int
    name: str = None
    range_m: tuple = None  # (start, end) lap distance, None until sourced
    representative_m: float = None


@dataclass(frozen=True)
class Complex:
    """Several physical corners that give one braking/lift sequence (e.g. T3-T6)."""
    corners: tuple
    name: str = None
    range_m: tuple = None
    representative_m: float = None

    @property
    def label(self):
        return f"T{self.corners[0]}-T{self.corners[-1]}"


@dataclass(frozen=True)
class TrackMetadata:
    track_id: int
    name: str
    expected_length_m: int = None
    corners: tuple = ()
    complexes: tuple = ()
    calibration: dict = field(default_factory=dict)

    @property
    def calibration_status(self):
        return self.calibration.get("status", "unknown")

    @property
    def has_corner_distances(self):
        return any(c.range_m is not None for c in self.corners)


def _range(value, where):
    if value is None:
        return None
    try:
        start, end = float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        raise MetadataError(f"{where}: range_m must be [start, end]") from None
    if not (0 <= start < end):
        raise MetadataError(f"{where}: range_m must satisfy 0 <= start < end, got {value}")
    return (start, end)


def _optional_number(value, where):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MetadataError(f"{where}: must be a number or null")
    return float(value)


def parse_track_metadata(raw, source="track metadata"):
    """Validate and build a TrackMetadata from parsed JSON. Raises MetadataError."""
    if not isinstance(raw, dict):
        raise MetadataError(f"{source}: expected a JSON object")
    try:
        track_id, name = int(raw["track_id"]), str(raw["name"])
    except (KeyError, TypeError, ValueError):
        raise MetadataError(f"{source}: needs track_id and name") from None

    corners, seen = [], set()
    for i, c in enumerate(raw.get("corners") or []):
        where = f"{source} corner #{i + 1}"
        try:
            number = int(c["number"])
        except (KeyError, TypeError, ValueError):
            raise MetadataError(f"{where}: needs a corner number") from None
        if number in seen:
            raise MetadataError(f"{where}: duplicate corner number {number}")
        seen.add(number)
        corners.append(Corner(number, c.get("name"), _range(c.get("range_m"), where),
                              _optional_number(c.get("representative_m"), where)))
    by_number = {c.number: c for c in corners}

    complexes = []
    for i, cx in enumerate(raw.get("complexes") or []):
        where = f"{source} complex #{i + 1}"
        members = tuple(sorted(int(n) for n in cx.get("corners") or []))
        if len(members) < 2:
            raise MetadataError(f"{where}: a complex needs at least two corners")
        missing = [n for n in members if n not in by_number]
        if missing:
            raise MetadataError(f"{where}: unknown corners {missing}")
        rng = _range(cx.get("range_m"), where)
        if rng is None and all(by_number[n].range_m for n in members):
            rng = (min(by_number[n].range_m[0] for n in members), max(by_number[n].range_m[1] for n in members))
        complexes.append(Complex(members, cx.get("name"), rng, _optional_number(cx.get("representative_m"), where)))

    return TrackMetadata(
        track_id=track_id, name=name,
        expected_length_m=raw.get("expected_length_m"),
        corners=tuple(sorted(corners, key=lambda c: c.number)),
        complexes=tuple(complexes),
        calibration=raw.get("calibration") or {},
    )


class MetadataRepository:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else DEFAULT_METADATA_DIR
        self.errors = {}  # track_id (or file name) -> message for files that could not be used
        self._catalog = None

    def catalog(self):
        """All known tracks, by track ID."""
        if self._catalog is None:
            self._catalog = {}
            path = self.directory / "catalog.json"
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for t in raw.get("tracks", []):
                    entry = CatalogEntry(int(t["track_id"]), str(t["name"]), t.get("circuit_name"))
                    self._catalog[entry.track_id] = entry
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                self.errors["catalog.json"] = f"cannot read catalog: {e}"
        return self._catalog

    def get_track(self, track_id):
        """Corner metadata for a circuit, or None if it has no (valid) metadata file."""
        path = self.directory / "tracks" / f"{int(track_id)}.json"
        try:
            meta = parse_track_metadata(json.loads(path.read_text(encoding="utf-8")), path.name)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:  # ValueError covers JSON errors and MetadataError
            self.errors[path.name] = str(e)
            return None
        if meta.track_id != int(track_id):
            self.errors[path.name] = f"{path.name}: track_id {meta.track_id} does not match the file name"
            return None
        return meta

    def track_ids_with_metadata(self):
        tracks = self.directory / "tracks"
        return sorted(int(p.stem) for p in tracks.glob("*.json") if p.stem.isdigit()) if tracks.is_dir() else []

    def display_name(self, track_id):
        """Friendly name; unknown IDs keep their number: 'Unknown track (99)'."""
        entry = self.catalog().get(int(track_id))
        if entry:
            return entry.display_name
        meta = self.get_track(track_id)
        return meta.name if meta else f"Unknown track ({int(track_id)})"

    def is_known(self, track_id):
        return int(track_id) in self.catalog() or self.get_track(track_id) is not None
