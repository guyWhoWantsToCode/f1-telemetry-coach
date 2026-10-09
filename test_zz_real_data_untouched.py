"""Guard: the test suite must leave the real data folders exactly as they were.

The snapshot is taken when this module is imported (unittest imports every test module before
running any test) and compared by the last test to run (the module name sorts last). All tests
are expected to work in temporary directories; if one ever writes into the real data/ folders
this fails and names the files.
"""

import unittest
from pathlib import Path

REAL_DATA = Path(__file__).resolve().parent / "data"
GUARDED = ("laps", "comparisons", "tracks", "positions", "track_maps")


def snapshot():
    found = {}
    for name in GUARDED:
        folder = REAL_DATA / name
        if folder.is_dir():
            for path in folder.rglob("*"):
                if path.is_file():
                    st = path.stat()
                    found[str(path.relative_to(REAL_DATA))] = (st.st_size, st.st_mtime_ns)
    return found


BEFORE = snapshot()


class RealDataUntouchedTests(unittest.TestCase):
    def test_real_data_folders_are_unchanged(self):
        after = snapshot()
        added = sorted(set(after) - set(BEFORE))
        removed = sorted(set(BEFORE) - set(after))
        changed = sorted(k for k in set(BEFORE) & set(after) if BEFORE[k] != after[k])
        self.assertEqual((added, removed, changed), ([], [], []),
                         "the test suite modified the real data/ folders")


if __name__ == "__main__":
    unittest.main()
