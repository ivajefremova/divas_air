# Data Inventory

Written by `/bootstrap` on 2026-10-10; route graph added on a second pass the same day. Activate `.venv` first (`source .venv/bin/activate`): there is no system `python`, so `make` fails without it. Verified by inspection, not assumption.
All paths are relative to the repo root.

---

## 1. Track files

All track files are in `data/processed/`. They are the output of `scripts/filter_adsblol.py`, which reads raw adsblol ADS-B trace JSON files and converts units. Raw files are in `data/raw/` (not in git).

### Column mapping to unified schema

| Raw column | Unified column | Notes |
|---|---|---|
| `icao24` | `asset_id` | lowercase hex, e.g. `4b1a2c` |
| `ts` | `t` | UNIX seconds UTC (float64); already in seconds |
| `lat` | `lat` | WGS84 degrees |
| `lon` | `lon` | WGS84 degrees |
| `on_ground` | `on_ground` | bool |
| `alt_m` | `alt_baro_m` | meters; converted from feet by filter script (`× 0.3048`) |
| `speed_mps` | `gs_mps` | m/s; converted from knots by filter script (`× 0.514444`) |
| `track_deg` | `track_deg` | degrees [0, 360); no conversion |
| `vrate_mps` | `vrate_mps` | m/s; converted from ft/min by filter script (`× 0.00508`) |
| `nic` | `nic` | float64, ~75 % null; forward-filled per aircraft in ingest |
| `nac_p` | `nacp` | float64, ~75 % null; forward-filled per aircraft in ingest |
| `sil` | `sil` | float64, ~75 % null; forward-filled per aircraft in ingest |
| `callsign` | `callsign` | str, nullable |
| `type` | `typecode_raw` | ICAO type code string, nullable |

**Added by ingest (not in raw files):** `track_id`, `source`, `domain`, `seq`, `asset_class`, `type_overridden`, `typecode`.

**Absent from data:** `alt_geom_m` (only barometric altitude available), `heading_deg` (only track over ground, not true heading).

### FCO files (Rome Fiumicino)

Source tag: `fco`. 8 days of approach-box traffic (~11.89–12.61 lon, 41.53–42.07 lat).

| File | Date | Rows | Aircraft |
|---|---|---|---|
| `data/processed/adsblol_fco_2026-09-29.parquet` | 2026-09-29 | 143,343 | 686 |
| `data/processed/adsblol_fco_2026-09-30.parquet` | 2026-09-30 | 142,185 | ~660 |
| `data/processed/adsblol_fco_2026-10-01.parquet` | 2026-10-01 | 142,876 | ~660 |
| `data/processed/adsblol_fco_2026-10-02.parquet` | 2026-10-02 | 145,624 | ~660 |
| `data/processed/adsblol_fco_2026-10-03.parquet` | 2026-10-03 | 128,333 | ~620 |
| `data/processed/adsblol_fco_2026-10-04.parquet` | 2026-10-04 | 129,723 | ~630 |
| `data/processed/adsblol_fco_2026-10-05.parquet` | 2026-10-05 | 143,662 | ~650 |
| `data/processed/adsblol_fco_2026-10-06.parquet` | 2026-10-06 | 132,600 | 659 |

Null rates (representative from 2026-09-29 and 2026-10-06):
- `alt_m` / `alt_baro_m`: ~4 %
- `speed_mps` / `gs_mps`: ~1–2 %
- `track_deg`: ~2 %
- `vrate_mps`: ~4 %
- `nac_p` / `nacp`: ~75 % (sparse broadcast; forward-fill in ingest)
- `nic`: ~75 %
- `sil`: ~75 %

**Holdout:** Per `params.REAL_HOLDOUT_DAYS = 2`, the last two days (`2026-10-05`, `2026-10-06`) are never used for training, calibration or tuning.

### Baltic interference day

Source tag: `baltic`.

| File | Date | Rows | Aircraft | Notes |
|---|---|---|---|---|
| `data/processed/adsblol_jam_2026-10-05.parquet` | 2026-10-05 | 285,211 | 628 | ~Baltic Sea, active jamming day |
| `data/processed/adsblol_control_2026-10-05.parquet` | 2026-10-05 | 1,190,201 | 3,506 | Wider Europe, same day |

Null rates on the jam file are elevated (signature of interference): `alt_m` ~28 %, `speed_mps` ~22 %, `nac_p` / `sil` ~83 %. The control file shows normal rates (~5 % / ~75 %).

### GPSJam reproduction output

| File | Description |
|---|---|
| `data/processed/gpsjam_repro_jam_2026-10-05.parquet` | H3-res-4 per-cell degradation stats, jam day |
| `data/processed/gpsjam_repro_control_2026-10-05.parquet` | Same, control day |
| `data/processed/gpsjam_repro_jam_2026-10-05.png` | Map plot |
| `data/processed/gpsjam_repro_control_2026-10-05.png` | Map plot |

Columns: `hex` (H3 cell id), `bad` (# aircraft majority-degraded in cell), `total` (# aircraft in cell), `percent_bad`.

Counts at `min_total = 10` aircraft per cell:
- Jam day: 109 cells; 82 red (>10 %), 23 yellow (2–10 %)
- Control day: 172 cells; 0 red, 0 yellow

---

## 2. Reference tables

### `data/reference/envelopes.csv`

14 rows × 10 columns. One row per `schema.ASSET_CLASSES` entry, in the same order.

Columns: `category`, `domain`, `max_ground_speed_mps`, `max_air_speed_mps`, `max_accel_mps2`, `max_turn_rate_dps`, `min_turn_radius_m`, `max_vrate_mps`, `kinematic_checks` (bool), `source_or_assumption`.

Helicopter row has `kinematic_checks = False` (hover and sideways flight are normal).

### `data/reference/aircraft_types.csv`

161 rows × 3 columns. Columns: `typecode` (ICAO type code), `aircraft_seen` (count at FCO), `size_class` (maps to `schema.ASSET_CLASSES`). Built by `scripts/build_aircraft_types.py`. Does not cover vehicles (those are assigned by domain, not typecode).

### `data/reference/type_overrides.csv`

4 rows × 3 columns. Columns: `icao24`, `typecode`, `reason`. Manual corrections for aircraft whose database typecode is wrong (all four are light aircraft misidentified; overridden to A320 based on callsign and flight profile evidence).

### `data/reference/gpsjam_2026-10-05.png`

Reference image of the official GPSJam map for 2026-10-05, used to visually validate the reproduction.

### `data/reference/zone_access.csv`

Created by bootstrap. See section 4 below.

---

## 3. Map layers

All files in `map/layers/`, all EPSG:4326, all from OpenStreetMap for Rome Fiumicino (LIRF).

No explicit airport boundary polygon exists; module 2 should derive it from `config.AIRPORT_BOX = (41.77, 12.20, 41.86, 12.30)` or from the union of the runway and apron geometries.

The route graph is `map/fco_routes.graphml` (added after the first bootstrap pass; see below).

Criticality values are not stored in the layer properties; they come from `params.CRITICALITY` and the zone type.

### `map/layers/aprons.geojson`

- Geometry: Polygon
- Features: 20
- Relevant property: `aeroway = apron` (all features)
- Zone type used in access table: `apron`
- No name or speed limit properties are populated (all null)
- Only ref populated: `"Area Manutenzione"` (one feature)

### `map/layers/buildings.geojson`

- Geometry: Polygon
- Features: 5,836
- Relevant properties: `building` (type), `height` (meters, string, 30 distinct values; not always present), `building:height` (3 distinct values), `aeroway` in `{hangar, terminal}` (subset)
- Zone type used in access table: `building`

### `map/layers/holding_points.geojson`

- Geometry: Point
- Features: 65
- Relevant properties: `aeroway = holding_position`, `holding_position:type` in `{runway, intermediate}`, `ref` (taxiway/runway identifiers)
- Zone type used in access table: `holding_point`

### `map/layers/runways.geojson`

- Geometry: LineString
- Features: 4 (3 distinct runway designators: `07/25`, `16L/34R`, `16R/34L`; two features for `16L/34R`)
- Relevant properties: `aeroway = runway`, `ref`, `length` in `{3300, 3900}` metres, `surface = paved`
- Zone type used in access table: `runway`
- Thresholds are not stored; module 2 must derive them from the LineString endpoints.

### `map/layers/service_roads.geojson`

- Geometry: LineString
- Features: 1,081
- Relevant properties: `highway = service`, `maxspeed` (string, km/h — **must convert to m/s**: ÷ 3.6). Null on 1,042 of 1,081 features; set values: `30` ×33, `40` ×3, `50` ×2, `20` ×1
- Zone type used in access table: `service_road`

### `map/layers/stands.geojson`

- Geometry: Point
- Features: 78
- Relevant properties: `aeroway = parking_position`, `ref` (stand numbers 101–210+)
- Zone type used in access table: `stand`
- No parking polygon layer exists separately; stands are points.

### `map/layers/taxiway_lines.geojson`

- Geometry: LineString
- Features: 200
- Relevant properties: `aeroway = taxiway`, `ref` (FCO taxiway designators A–AK+)
- No `maxspeed` property is populated (all null)
- Zone type used in access table: `taxiway`

### `map/fco_routes.graphml`

- Format: GraphML, read with `networkx.read_graphml` → undirected `MultiGraph`, 873 nodes, 1,248 edges, one connected component.
- Built from OSM `taxiway_lines` + `service_roads`, merged, snapped at 3 m, noded (graph attribute `source`); primal approach.
- Node attributes: `x_utm`, `y_utm` (EPSG:32633 = `config.CRS_METRIC`, meters; `x`, `y` are duplicates of them), `lon`, `lat` (EPSG:4326).
- Edge attributes: `layer` in `{taxiway: 630, service_road: 618}`; `aeroway = taxiway` on taxiway edges, `highway = service` on service-road edges; `geometry` (WKT LineString in EPSG:32633); `length_m` (meters, median 56, max 1,381); `ref`; `maxspeed_kmh` (km/h, only `30.0` on 168 edges, null elsewhere); `access` (`private` ×489, `no` ×2); `oneway` (`yes` ×173, `no` ×40, rest null); `surface`, `name`, `tunnel`, `bridge`.
- **Aircraft vs vehicle routes:** one merged graph. Split by edge `layer`: aircraft graph = `layer == "taxiway"` edges; vehicle graph = `layer == "service_road"` edges (vehicles crossing taxiways where the two layers share a node is allowed by the shared nodes). No runway edges are in the graph.
- Edges are undirected even where `oneway = yes`; module 2 should ignore direction (simplest) or build a `DiGraph` from these flags.
- The service roads with `maxspeed` 20, 40 or 50 in `service_roads.geojson` do not appear with those values in the graph (only 30 survives the merge); take zone speed limits from the layer, not from the graph.

---

## Degraded reading rule

From `scripts/gpsjam_repro.py` (the script that reproduced the GPSJam metric):

> A fix is **degraded** if `nac_p < 8`.

Eligibility filter: an aircraft is only included if it reported `nac_p >= 8` at least once (it must have reported good accuracy at some point — excludes transponders that never broadcast NACp).

NACp is forward-filled per aircraft before the check (`df["nac_p"] = df.groupby("icao24").nac_p.ffill()`).

The majority rule used for the Baltic cell metric: an aircraft is "bad" in a cell if `fraction of its readings with nac_p < 8 > 0.5` (more than half its readings are degraded). This is the rule to implement in `divas_air.degradation.is_degraded_reading`.

H3 resolution: **4** (matches `params.REGIONAL.h3_res = 4`).

---

## 4. Existing scripts

| Script | Purpose |
|---|---|
| `scripts/filter_adsblol.py` | Reads raw adsblol ADS-B trace JSON (gzipped or plain), filters to a lat/lon box, converts units (feet→m, knots→m/s, ft/min→m/s), writes parquet. Produces `data/processed/adsblol_*.parquet`. |
| `scripts/gpsjam_repro.py` | Reproduces the GPSJam cell-degradation metric. See degraded reading rule above. Produces `data/processed/gpsjam_repro_*.parquet` and `.png`. |
| `scripts/build_aircraft_types.py` | Maps ICAO type codes to size classes using a hard-coded dict; counts FCO occurrences; writes `data/reference/aircraft_types.csv`. |
| `scripts/check_envelopes.py` | Computes lagged kinematic rates (5 s base) on FCO data and reports p99.9 vs LIMIT_MARGIN×envelope for each class. Smoke-test for envelope tuning. |
| `scripts/check_tracks.py` | Prints quick stats for a parquet file: row count, aircraft count, timestamp spacing, FCO ground points, NACp coverage. |
| `scripts/make_contract_examples.py` | Regenerates `contracts/*.schema.json` and `contracts/examples/*.json` after approved changes to `contract.py`. |
| `scripts/stub_api.py` | Stub Trust API (FastAPI) serving fixed contract examples from `contracts/examples/`. Used by the map team before module 6 exists. |
| `scripts/unpack_release.py` | Unpacks multi-part `.tar.a?` split archives of adsblol day releases into day folders. |

---

## 5. Gaps

The following items are needed by specs but were not found in `data/` or `map/layers/`:

1. **`alt_geom_m`** (geometric/GPS altitude) — absent from all source files. Only barometric altitude (`alt_m` / `alt_baro_m`) is available. Module 1 can leave `alt_geom_m` always-null; altitude-divergence features will rely on barometric alone.

2. **`heading_deg`** (true heading) — absent from all source files. Only `track_deg` (course over ground) is available. Module 1 should set `heading_deg = NaN`; heading-vs-track residual features will be NaN for these sources.

3. **Airport boundary polygon** — no dedicated layer. Use `config.AIRPORT_BOX` or derive from geometry unions.

4. **Route graph** — resolved: `map/fco_routes.graphml` (section 3). It has no runway edges and no edge direction; speed limits in it are incomplete.

5. **Zone criticality in layer properties** — not present. Criticality is assigned by type: runway = high (1.0), taxiway = medium (0.5), holding point = medium (0.5), apron = low (0.2), stand = low, service road = low, building = low. These defaults are from `params.CRITICALITY`; ADR has not confirmed them.

6. **Parking zone polygon layer** — stands exist as Points only. No parking polygon layer.

7. **Vehicle track data** — the processed parquet files contain only aircraft. Vehicle ground truth would need a separate source (not provided).

---

*Zone access assumptions are noted in `data/reference/zone_access.csv` and must be confirmed by ADR.*
