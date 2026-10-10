# 00 Contracts

Binding for every module. Several sessions build modules in parallel and a separate team builds the Risk Map; these contracts are what lets the pieces fit without anyone reading anyone else's code.

The contracts exist as code, already in the repo and already tested (`make contracts`):

| File | Fixes |
|---|---|
| `src/divas_air/schema.py` | unified point schema, causes, `validate()`, `assert_no_leakage()` |
| `src/divas_air/registry.py` + `contracts/features.csv` | every feature name, group, monotone constraint, default threshold, evidence template |
| `src/divas_air/contract.py` + `contracts/*.schema.json` | Trust API output contract |
| `src/divas_air/params.py` | every tunable constant |
| `src/divas_air/config.py` | paths, CRS, area boxes, `WINDOW_S`, `STRIDE_S` |

When this document and the code disagree, the code wins: tell the human so the document gets fixed.

## 1. Pipeline

```
raw sources ─► 1 ingest ─► points ─► 3 features ─► 4 scoring + models ─► 5 fleet + pipeline ─► verdicts
2 generator ─► points (labeled) ─┘                                           │
                                                   6 engine + API + replay ◄─┤
                                                   8 evaluation report     ◄─┘
```

Real and synthetic tracks share one schema, so every stage after ingest is identical for both.

## 2. Unified point schema

One row is one position report. Defined in `schema.py`; `schema.validate(df)` is the gate every source must pass.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `track_id` | str | no | `<source>:<asset_id>:<segment>`; a silence longer than `TRACK_GAP_SPLIT_S` starts a new segment |
| `asset_id` | str | no | icao24 hex, lowercase, or vehicle id |
| `source` | str | no | `schema.SOURCES` for stored sources; the API uses `live` and tests use `test`. Never validate or branch on it |
| `domain` | str | no | `aircraft` or `vehicle` |
| `seq` | int64 | no | arrival order within the track, unique. Rows are not sorted by time: out-of-order arrival is a temporal anomaly |
| `t` | float64 | no | position time, UNIX seconds UTC |
| `lat`, `lon` | float64 | no | WGS84 degrees |
| `asset_class` | str | no | envelope category, after type overrides; untyped aircraft are `other` |
| `type_overridden` | bool | no | true where `type_overrides.csv` changed the type |
| `alt_baro_m`, `alt_geom_m` | float64 | yes | meters |
| `gs_mps` | float64 | yes | reported ground speed |
| `track_deg` | float64 | yes | reported course over ground, [0, 360) |
| `heading_deg` | float64 | yes | reported true heading, [0, 360) |
| `vrate_mps` | float64 | yes | positive up |
| `on_ground` | boolean | yes | |
| `nacp`, `nic`, `sil` | float64 | yes | forward-filled per aircraft within a track |
| `callsign`, `typecode`, `typecode_raw` | str | yes | `typecode_raw` is the declared type before overrides |

Labeled sources (`synthetic`, `demo`) add:

| Column | Meaning |
|---|---|
| `label_cause` | per point, one of `schema.CAUSES`; `plausible` outside events |
| `label_onset_t` | onset of the event hitting this track; NaN if none |
| `label_event_id` | event affecting this point; null if none |
| `label_true_lat`, `label_true_lon` | position before corruption |
| `scene_id` | the split group: tracks that share a clock, a map and possibly an area event |
| `base_track_id` | the track before injection |

Conversions at ingest: knots x 0.514444, feet x 0.3048, ft/min x 0.00508, milliseconds / 1000.

## 3. Causes

`plausible`, `degraded`, `technical_error`, `gnss_anomaly`, `possible_interference`, `possible_spoofing`, `behavioral_anomaly`.

Integrity target: sound = `plausible`, `behavioral_anomaly`; unsound = the other five. `schema.integrity_label()` does the mapping. Each cause has one physical definition, given in `specs/02_generator.md` section 3; the generator, the models and the evidence text all follow it.

## 4. Windows

The unit of inference is a `WINDOW_S` = 30 s window of one track, re-evaluated every `STRIDE_S` = 5 s.

- `t_end` lies on the absolute grid `k * STRIDE_S`, so windows of different tracks align for the fleet layer.
- A window covers fixes with `t_end - WINDOW_S < t <= t_end`.
- Emit one row per track for every grid time from the first grid time at or after the track's first fix to the first grid time at or after its last fix. Windows with no fix in them are emitted (the gap is the signal).
- Every per-window table is keyed by `schema.WINDOW_KEYS` = (`track_id`, `t_end`).

Window labels on labeled sources (`schema.WINDOW_LABEL_COLUMNS`):

- `label_frac`: share of the window's fixes whose `label_cause` is not `plausible`. For an empty window use the label of the track's fixes nearest in time on both sides if they agree, else 0.
- `label_cause`: the most frequent non-plausible cause if `label_frac >= LABEL_POS_FRAC`, else `plausible`.
- `label_transition`: true if `0 < label_frac < LABEL_POS_FRAC`. Excluded from training and classification metrics; kept for time-to-detect.
- `label_onset_t`, `label_event_id`, `scene_id`, `base_track_id`: carried from the points.

## 5. Output contract

Defined in `contract.py`. `Verdict` is one verdict per track per window. Semantics, all implemented in module 4:

- `integrity_raw` = 100 x (1 - calibrated P(unsound)). `integrity` is smoothed and drives `trust_state`.
- `normality` = min of the spatial and contextual dimension scores.
- `trust_state`: `untrusted` entered below 40, left above 55; `caution` entered below 70, left above 75; else `trusted`.
- `quadrant` = `contract.quadrant_of(trust_state, normality_state)`.
- `cause_probs`: calibrated probabilities of all seven causes. `cause` is the reported cause and never contradicts the state: `trusted` reports `plausible` or `behavioral_anomaly`; `untrusted` reports the most likely unsound cause; `caution` reports the argmax.
- `confidence` is separate from the score: low with few fixes, long gaps, or two causes within `CAUSE_MARGIN`.
- `severity.score` = max(1 - integrity/100, 1 - normality/100) x zone criticality.
- `evidence`: at most three template sentences with raw values.
- `action`: looked up from quadrant and severity; fixed text.

`RiskZones` is a GeoJSON FeatureCollection of `static`, `live` and `forecast` features. The replay bundle (`ReplayManifest`, `ReplayFrame`) is the offline demo's data.

Examples: `contracts/examples/`. Stub server for the map team: `make stub`.

## 6. Canonical artifact paths

Modules and acceptance tests read exactly these. Parquet via pyarrow.

| Path | Written by | Content | In git |
|---|---|---|---|
| `data/processed/points/<source>.parquet` | 1, 2 | points, unified schema | no |
| `data/processed/synth/events.parquet`, `demo_events.parquet` | 2 | injected events | yes |
| `data/reference/zone_access.csv` | bootstrap | zone type x class: allowed, max dwell | yes |
| `data/reference/dimension_thresholds.csv` | 3 | fitted tau per feature and domain | yes |
| `data/processed/features/<source>.parquet` | 3 | one row per window | no |
| `artifacts/models/` | 4 | `integrity_p1.txt`, `integrity_p2.txt`, `cause.txt`, `calibration.json`, `splits.json`, `model_card.json` | yes |
| `data/processed/fleet/<source>_<profile>_cells.parquet` | 5 | cell table | no |
| `data/processed/fleet/baseline_apron.parquet` | 4 (training, with module 5's function) | per-cell baseline degraded rate | yes |
| `map/layers/halos_static.geojson` | 5 | static GNSS risk halos | yes |
| `data/processed/verdicts/<source>.parquet` | 5 | flat verdict table | no |
| `data/processed/demo/replay/manifest.json`, `frames.jsonl` | 6 | offline replay bundle | yes |
| `reports/metrics.json`, `reports/REPORT.md`, `reports/figures/*.png` | 8 | evaluation | yes |

Flat verdict table columns: the keys, `integrity_raw`, `integrity`, `normality`, `d_kinetic`, `d_temporal`, `d_spatial`, `d_contextual`, `trust_state`, `normality_state`, `quadrant`, `confidence`, `confidence_level`, `cause`, `p_<cause>` for the seven causes, `severity_score`, `severity_level`, `zone_criticality`, `action_code`, `action_text`, `area_alert_id`, `evidence_json`, the `aux_*` columns, and the window label columns on labeled sources.

## 7. Public interfaces

Other modules and the acceptance tests call only these.

| Module | Interface |
|---|---|
| 1 | `divas_air.ingest.ingest_source(source) -> Path`, `load_points(source) -> DataFrame`, `asset_class_for(typecode) -> str`, `apply_type_overrides(df) -> DataFrame`; CLI `python -m divas_air.ingest --source <name\|all>` |
| 2 | `divas_air.geo.MapLayers.load() -> MapLayers`, `divas_air.synth.generate_scene(seed, *, duration_s, n_vehicles, n_aircraft, events=None, layers=None) -> (points, events)`, `inject(points, cause, *, onset_t, duration_s, track_ids=None, region=None, params=None, seed=0, event_id=None, layers=None) -> points`; CLI `python -m divas_air.synth`, `python -m divas_air.synth.demo` |
| 3 | `divas_air.features.compute_features(points, layers=None) -> DataFrame`, `divas_air.degradation.is_degraded_reading(points) -> Series[bool]`; CLI `python -m divas_air.features --source <name\|all> [--calibrate]` |
| 4 | `divas_air.scoring.violations(features)`, `dimension_scores(features)`, `normality_score(dims)`, `divas_air.scoring.baseline.naive_score(points)`, `divas_air.models.load_bundle() -> ModelBundle` (`p_unsound`, `cause_probs`, `contributions`, `inputs`), `divas_air.verdict.smooth_and_state(...)`, `normality_state(...)`, `confidence(...)`, `severity(...)`, `reported_cause(...)`, `assemble(...)`, `to_contract(row)`; CLI `python -m divas_air.models.train` |
| 5 | `divas_air.fleet.cells_from_windows(windows, profile)`, `cells_from_points(points, profile)`, `fleet_features(windows, profile)`, `area_alerts(cells, profile)`, `apron_baseline(windows, profile)`, `divas_air.halos.static_halos`, `live_halos`, `forecast_paths`, `divas_air.pipeline.run(source) -> Path`; CLI `python -m divas_air.fleet`, `python -m divas_air.pipeline --source <name\|all>` |
| 6 | `divas_air.engine.TrustEngine` (`from_disk`, `ingest`, `step`, `risk_zones`, `history`), `divas_air.api.app:app`; CLI `python -m divas_air.api.replay` |
| 8 | CLI `python -m divas_air.eval.report` |

Exact signatures are in each module's spec.

## 8. Decisions made beyond Project Specification v2

Each is a judgment call taken while writing these specs. The human can veto any of them; say so if the data argues against one.

1. **Geodesic distances between fixes**, UTM 33N only against map layers. UTM 33N is about 0.5 % off at Baltic longitudes; the geodesic is exact and free.
2. **Window aggregates are max and mean** (plus RMS for jitter). With about 11 fixes per window the 95th percentile equals the max.
3. **Thresholds of features with `tau_source = calibrated` are fitted** on clean training data (99.9th percentile, floored at the default in `features.csv`). Envelope features keep tau = class limit x 1.5; `fixed` ones keep the registry value.
4. **Asymmetric smoothing**: a falling score takes effect fast (alpha 0.7), a recovering one slowly (alpha 0.3). Detection stays within one or two windows and the map does not flicker.
5. **Semi-synthetic approach scenes**: anomalies are injected into real `fco` approach tracks from non-held-out days, so the models see real ADS-B sampling and noise. The last two real days are never touched by training.
6. **The split group is the scene**, not the track: fleet features couple the tracks of a scene.
7. **The reported cause is constrained by the state** so a verdict card never reads "trusted, possible spoofing". `cause_probs` stays unconstrained.
8. **The apron fleet layer is evaluated on the 5 s grid from each track's latest window**, with a 60 s presence span and a 60 s hold on alerts, not fixed minute bins. It is causal and an area alert appears within seconds.
9. **Evidence uses LightGBM's built-in TreeSHAP** (`pred_contrib=True`), not the `shap` package.
10. **Feature priorities**: 33 of 53 features are P0. P1 and P2 features may ship as NaN columns first, so the pipeline runs end to end early.
