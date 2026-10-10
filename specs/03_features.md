# 03 Features

**Goal:** one row per window with the 48 non-fleet features of the registry, computed the same way for real and synthetic tracks, online and in batch.

**Depends on:** 00, 1 (for real sources), and `divas_air.geo.MapLayers` from module 2 (for spatial and contextual features). **Owns:** `src/divas_air/features/`, `src/divas_air/degradation.py`, `tests/unit/test_features*.py`.

You can build and unit-test the kinetic, temporal and signal groups on `tests/helpers.make_track` before module 1 or module 2 has produced anything. Do those first; add spatial and contextual once `divas_air.geo` exists. Do not write a second layer loader.

## Inputs

- Points in the unified schema.
- `data/reference/envelopes.csv`, `aircraft_types.csv`, `zone_access.csv`.
- Map layers via `MapLayers` (zones, routes, buildings, airport boundary, runways).

## Outputs

- `data/processed/features/<source>.parquet`: keys (`track_id`, `t_end`), `t_start`, `registry.FEATURE_COLUMNS`, `registry.AUX_COLUMNS`, and `schema.WINDOW_LABEL_COLUMNS` on labeled sources. Nothing else.
- `data/reference/dimension_thresholds.csv`: columns `name`, `domain`, `tau`, `scale`, `n`, `fitted_on`.

## Interface

```python
# divas_air/features/__init__.py
def compute_features(points: pd.DataFrame, layers: "MapLayers | None" = None) -> pd.DataFrame:
    """Per-window features for every track in `points`. layers=None: spatial and
    contextual features and the aux_zone_* columns are NaN/None; everything else is computed."""

# divas_air/degradation.py
def is_degraded_reading(points: pd.DataFrame) -> pd.Series: ...   # bool per fix
```

`MapLayers` is specified in `02_generator.md`.

CLI: `python -m divas_air.features --source <name|all>` writes feature tables. `python -m divas_air.features --calibrate` reads the existing feature tables and fits the thresholds (requirement 8). `make features` runs both; `make train` reruns the calibration once the splits exist.

## Requirements

### Windows and causality

1. Window grid, emission rule and window labels exactly as `00_contracts.md` section 4.
2. A row at `t_end` depends only on fixes with `t <= t_end` of that track, at most `params.BUFFER_S` back, plus the dwell timer. Truncating the input at any time must not change any earlier row.
3. Count `tmp_nonmono_count` in `seq` order first; then sort each track by `t` (stable) for everything else.

### Feature definitions

The registry (`contracts/features.csv`) gives each feature's name, unit and one-line definition. Its `applies_to` column is descriptive (where the feature is expected to be populated): compute every feature wherever its inputs are present, so a vehicle that reports NACp gets the `sig_nacp_*` features. The details the one-liners leave open:

4. **Pairs.** For fix `i`, its pair is the latest fix `j` of the same track with `t_j <= t_i - RATE_BASE_S`. A pair belongs to the window that contains `i`. From each pair: `dt`, geodesic distance and bearing (`pyproj.Geod`), implied speed = distance / `dt`, reported speed = mean of `gs_mps` over fixes `j..i`.
   - `kin_speed_resid_*`: |implied - reported| per pair. `aux_speed_implied_mps` and `aux_speed_reported_mps` are the values at the pair with the largest residual.
   - `kin_accel_ratio_max`: |`gs_i - gs_j`| / `dt` / class max acceleration. `kin_accel_imp_ratio_max`: change of implied speed between a pair and the pair ending at `j`.
   - Turn rates use wrapped angle differences, only where the reported speed at both ends exceeds `COURSE_MIN_MPS`; implied course only where the pair's distance exceeds `COURSE_MIN_DISP_M`.
   - `kin_turn_radius_ratio_max`: class min radius / (speed / turn rate in rad/s), only where turn rate exceeds 1 deg/s.
   - `kin_speed_ratio_max` is the larger of implied and reported speed over the class limit, evaluated at every fix (reported speed alone where a fix has no pair). It uses the ground limit when the fix is on the ground or the asset is a vehicle, else the air limit; `aux_class_max_speed_mps` records which.
5. **Other groups.**
   - `kin_pos_jitter_m`: fit x(t) and y(t) (local meters) with a degree-2 polynomial over the window's fixes; RMS of the residual distance. Needs at least 5 fixes, else NaN.
   - `tmp_gap_max_s`: the largest of the inter-fix intervals in the window, the interval from the last fix before the window to the first in it, and `t_end` minus the last fix.
   - `tmp_dt_dev_ratio`, `sig_nacp_drop`, `sig_nic_drop`, `sig_alt_div_*`: baselines are medians over the `BASELINE_S` before the window start. NaN until the track has 30 s of history.
   - `tmp_frozen_*`: runs of fixes with identical lat and lon while `gs_mps > MOVING_MPS`.
   - `sig_degraded_frac`: mean of `is_degraded_reading` over the window. Implement `is_degraded_reading` from the rule recorded in the inventory under "Degraded reading rule"; it is the same rule that reproduced GPSJam. `sig_degraded_majority` = 1 if the share exceeds 0.5.
   - Spatial and contextual features use ground fixes only (`domain == "vehicle"` or `on_ground`), except the approach and phase features, which use airborne fixes, and `spa_zone_crit_max`, which is defined for all: for ground fixes the max criticality of zones occupied or within `ZONE_BUFFER_M`; for airborne fixes `CRITICALITY_AIRBORNE_FINAL` inside `APPROACH_FINAL_KM` of a runway threshold and aligned with it, else `CRITICALITY_AIRBORNE_OTHER`. `aux_zone_*` describe the zone that set it.
   - `ctx_type_violation_crit_max` and `ctx_dwell_ratio` read `zone_access.csv`. Dwell is the time since the asset last moved more than `DWELL_MOVE_M`: per-track state, computed in one causal pass.
   - Approach features apply to airborne, non-helicopter fixes within `APPROACH_FINAL_KM` of a threshold whose bearing is within 30 degrees of the reported course. Use the runway whose extended centerline is nearest.
   - `ctx_identity_mismatch` uses `typecode_raw`, not the overridden type: that is how the four known misidentified airliners get flagged.
6. **Helicopters** and any class with `kinematic_checks=false`: NaN for all `registry.ENVELOPE_RATIO_COLUMNS`.
7. **Aux columns** as listed in `registry.AUX_COLUMNS`; `aux_lat`, `aux_lon`, `aux_alt_m`, `aux_gs_mps`, `aux_track_deg`, `aux_airborne` come from the last fix at or before `t_end`.

### Thresholds

8. `--calibrate` fits tau for every feature with `tau_source == "calibrated"`, separately for `aircraft` and `vehicle`: tau = max(registry default, 99.9th percentile over clean windows). Clean windows are: for aircraft, `fco` windows from non-held-out days; for vehicles, synthetic windows with `label_frac == 0` from train scenes if `artifacts/models/splits.json` exists, else all clean synthetic windows (refit after module 4 writes the splits). Scale stays at the registry value. Envelope and fixed features are written with their registry values. With no clean window to fit on (ground features for aircraft, for example), tau is the registry default, never NaN. Record `n` and `fitted_on`.

### Priorities and performance

9. Build P0 features first (28 of the 48), get the acceptance tests green, then P1, then P2. An unbuilt feature is an all-NaN column and a line in `docs/STATUS.md`.
10. Vectorize per track. Seven days of `fco` in under ten minutes on a laptop.

## Acceptance (`tests/acceptance/test_03_features.py`)

On helper tracks (no data needed):
- output columns are exactly the keys, `t_start`, features and aux; no forbidden column is a feature;
- `t_end` lies on the stride grid and consecutive rows of a track are `STRIDE_S` apart;
- a clean constant-velocity track has near-zero residuals and no envelope ratio above 1;
- the 5 s rule: two fixes 0.2 s apart and 5 m off do not create an over-limit;
- a 300 m jump raises `kin_speed_resid_max` far above its default tau;
- a frozen position raises `tmp_frozen_run_s`; a 20 s gap raises `tmp_gap_max_s`; an out-of-order fix raises `tmp_nonmono_count`;
- helicopters get NaN envelope ratios;
- causality: rows computed on a truncated track equal the same rows computed on the full track;
- window labels follow the `LABEL_POS_FRAC` rule.

On real data:
- `features/fco.parquet` exists with every P0 feature populated where it applies;
- over-limit share: under 0.1 % of clean `fco` windows have any envelope ratio above `LIMIT_MARGIN`. Point-to-point rates gave 0.2 %; the target is about 0.

Report in `docs/STATUS.md`: the over-limit share, runtime, and the list of features still NaN.
