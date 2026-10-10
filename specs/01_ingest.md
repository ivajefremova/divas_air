# 01 Ingest

**Goal:** turn every raw track source into the unified point schema, with type overrides applied, so that everything downstream is source-agnostic.

**Depends on:** 00. **Owns:** `src/divas_air/ingest/`, `tests/unit/test_ingest*.py`.

## Inputs

- Raw or pre-filtered adsb.lol tracks for `fco`, `baltic`, `control`. Exact paths, formats, columns and units are in `docs/DATA_INVENTORY.md`. Do not assume the layout: adsb.lol history is usually readsb trace JSON (rows of time offset, lat, lon, baro altitude in feet or the string `"ground"`, ground speed in knots, track, flags, vertical rate in ft/min, an aircraft-detail object carrying `nac_p`, `nic`, `sil`, `alt_geom`, `flight`, `true_heading`), but the collection scripts may already have flattened it.
- `data/reference/aircraft_types.csv` (`typecode`, `aircraft_seen`, `size_class`), `type_overrides.csv` (`icao24`, `typecode`, `reason`), `envelopes.csv`.
- Optional: `adr_mock` (ADR's mock scenarios, if provided) and `lira` (upgrade 4).

## Output

`data/processed/points/<source>.parquet`, one file per source, passing `schema.validate()`.

## Interface

```python
# divas_air/ingest/__init__.py
def ingest_source(source: str) -> Path: ...        # raw -> canonical parquet; returns its path
def load_points(source: str) -> pd.DataFrame: ...  # reads the canonical parquet, validated
def asset_class_for(typecode: str | None) -> str: ...   # aircraft_types.csv lookup; unknown or None -> "other"
def apply_type_overrides(df: pd.DataFrame) -> pd.DataFrame: ...  # sets typecode, asset_class, type_overridden
```

CLI: `python -m divas_air.ingest --source <fco|baltic|control|adr_mock|lira|all>`. `all` ingests every source whose raw data exists and prints one summary line per source: rows, tracks, time span, typed share, null share of `gs_mps`, `nacp`, `alt_geom_m`.

## Requirements

1. **Units.** Convert to SI here and nowhere else (factors in `00_contracts.md` section 2). Baro altitude `"ground"` becomes `on_ground=True` with `alt_baro_m` NaN; a numeric baro altitude sets `on_ground=False`; `on_ground` is missing only when the source gives neither.
2. **Identity.** `asset_id` is the lowercase icao24. `typecode_raw` is the declared type. `typecode` and `asset_class` are set after overrides: for each `icao24` in `type_overrides.csv`, `typecode` becomes the override, `type_overridden=True`. `asset_class = asset_class_for(typecode)`.
3. **Order.** Keep arrival order in `seq`. Do not sort by time and do not drop duplicate or out-of-order fixes: the temporal features count them.
4. **Segments.** Within an asset, a silence longer than `params.TRACK_GAP_SPLIT_S` starts a new segment. `track_id = f"{source}:{asset_id}:{segment}"`.
5. **Integrity fields.** Forward-fill `nacp`, `nic`, `sil` within a track (they arrive less often than positions). Never back-fill.
6. **Area filter.** `fco` keeps fixes inside `config.APPROACH_BOX`. `baltic` and `control` keep their full regions. Filter first, then cut segments (requirement 4), so an aircraft that leaves the box and returns becomes two tracks.
7. **Angles** are wrapped to [0, 360). 360 becomes 0.
8. **Nothing is "cleaned".** Do not filter implausible speeds, jumps or gaps. Drop a row only if `t`, `lat` or `lon` is missing or unparseable, and count the drops in the summary.
9. **Idempotent and deterministic.** Running twice gives byte-identical parquet.
10. **`adr_mock`**, if present: map its columns to the schema, including vehicles (`domain="vehicle"`, class from the mock's asset type mapped onto the vehicle rows of `envelopes.csv`). It is evaluation-only; never mix it into training.

## Acceptance (`tests/acceptance/test_01_ingest.py`)

- `validate()` passes on `fco`, `baltic`, `control`.
- Every aircraft in `type_overrides.csv` that appears in `fco` has the override type, `type_overridden=True` and class `narrowbody`; at least one of the four appears.
- At least 95 % of `fco` aircraft have a class other than `other` (97.4 % are typed).
- Unit check: the median `gs_mps` of `fco` fixes below 600 m is between 55 and 100 m/s. In knots it would be far above.
- `track_id` segments never contain a silence longer than `TRACK_GAP_SPLIT_S`.
- `nacp` is present on most `fco` fixes.
- `asset_class_for` returns `other` for unknown and missing types.

Report in `docs/STATUS.md`: rows, tracks and days per source; typed share; null shares; rows dropped and why.
