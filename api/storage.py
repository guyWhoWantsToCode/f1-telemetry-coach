"""File-system access for recorded laps and saved comparisons (no HTTP concerns here)."""

import csv
import re
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Ids are file stems. Only plain filename characters are accepted, so an id can never
# point outside the data folders (no slashes, no "..").
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


class InvalidIdError(ValueError):
    """The id is not a plain file stem."""


class NotFoundError(LookupError):
    """No file exists for the id."""


class DataStore:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
        self.laps_dir = self.data_dir / "laps"
        self.comparisons_dir = self.data_dir / "comparisons"

    @staticmethod
    def _check_id(item_id):
        if not _ID_RE.match(item_id) or ".." in item_id:
            raise InvalidIdError(f"invalid id: {item_id!r}")

    def _path(self, directory, item_id):
        self._check_id(item_id)
        path = directory / f"{item_id}.csv"
        if not path.is_file():
            raise NotFoundError(f"not found: {item_id}")
        return path

    def lap_path(self, lap_id):
        return self._path(self.laps_dir, lap_id)

    def comparison_path(self, comparison_id):
        return self._path(self.comparisons_dir, comparison_id)

    def lap_paths(self):
        return sorted(self.laps_dir.glob("*.csv")) if self.laps_dir.is_dir() else []

    @staticmethod
    def read_columns(path):
        """A CSV as {column: [numbers]} (ints where every value is an integer)."""
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            columns = {name: [] for name in reader.fieldnames or []}
            for row in reader:
                for name in columns:
                    columns[name].append(float(row[name]))
        for name, values in columns.items():
            if all(v.is_integer() for v in values):  # keep gear, drs, invalid... as integers
                columns[name] = [int(v) for v in values]
        return columns
