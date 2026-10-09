# Static circuit metadata

Facts about the real circuits. This is **not** learned from driving and is never written by the
application: the learned data lives in `data/tracks/` and is a separate concept.

## Files

- `catalog.json` – every F1 25 track ID with the game's label, from the official UDP spec
  (Track IDs appendix). Adding a circuit name here is how a track gets a friendly display name.
- `tracks/<track_id>.json` – one file per circuit that has corner metadata. Adding a new circuit
  to the application means adding a file here; no Python changes are needed.

## `tracks/<track_id>.json`

```json
{
  "schema_version": 1,
  "track_id": 15,
  "name": "Circuit of the Americas",
  "expected_length_m": 5513,
  "corners": [
    { "number": 1, "name": null, "range_m": [start, end], "representative_m": apex }
  ],
  "complexes": [
    { "corners": [3, 4, 5, 6], "name": null, "range_m": [start, end], "representative_m": null }
  ],
  "calibration": { "status": "...", "notes": "...", "needed": [] }
}
```

- `range_m` and `representative_m` may be `null` until they are sourced. Corners without
  `range_m` cannot be matched to detected events, so events on that circuit stay "Event N".
- A **complex** is a sequence of physical corners that produces one braking/lift event
  (for example T3-T6 or the Suzuka Esses). Its `corners` must exist in `corners`. If `range_m` is
  omitted it is taken from the first and last member when they all have ranges.
- Distances are metres of lap distance, as in the recorded laps (`lap_distance_m`).

## Rules

- Never copy corner distances from a recorded lap. They must come from circuit geometry, or from
  laps that have been checked against it.
- The application only reads these files.

## Current status

| Circuit | Track ID | Corner numbers | Corner distances | Complexes |
|---|---|---|---|---|
| Circuit of the Americas | 15 | T1-T20 | **not yet sourced** | none entered |
| every other F1 25 circuit | see `catalog.json` | no file yet | no | no |
