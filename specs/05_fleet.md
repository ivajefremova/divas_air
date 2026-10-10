# 05 Fleet layer, risk halos and the batch pipeline

**Goal:** tell area interference (many tracks degraded together) from a technical error (one track alone), produce the GNSS risk halos, and chain everything into verdict tables.

**Depends on:** 00, 3, 4. **Owns:** `src/divas_air/fleet/`, `src/divas_air/halos.py`, `src/divas_air/pipeline.py`, `tests/unit/test_fleet*.py`, `test_halos*.py`, `test_pipeline*.py`.

Validated reference: on the Baltic day (2026-10-05) the majority rule with at least 10 aircraft per hexagon gave 82 red hexagons of 109, matching GPSJam, and on the France control none of 172 was above 2 %. The existing reproduction script is listed in `docs/DATA_INVENTORY.md`. Reuse its logic; do not reinvent the rule.

## Outputs

- `data/processed/fleet/<source>_<profile>_cells.parquet`
- `data/processed/fleet/baseline_apron.parquet`
- `map/layers/halos_static.geojson`
- `data/processed/verdicts/<source>.parquet`

## Interface

```python
# divas_air/fleet/__init__.py
def cells_from_points(points: pd.DataFrame, profile: FleetProfile) -> pd.DataFrame: ...
    # regional profile, reading level: cell, bin_start, n_tracks, n_degraded, share, level ("green"|"yellow"|"red"), flagged
def cells_from_windows(windows: pd.DataFrame, profile: FleetProfile,
                       baseline: pd.DataFrame | None = None) -> pd.DataFrame: ...
    # apron profile: cell, t_end, n_tracks, n_degraded, share, baseline, p_value, flagged
def fleet_features(windows: pd.DataFrame, profile: FleetProfile,
                   baseline: pd.DataFrame | None = None) -> pd.DataFrame: ...
    # keys + registry.FLEET_COLUMNS, one row per input row
def apron_baseline(windows: pd.DataFrame, profile: FleetProfile) -> pd.DataFrame: ...   # cell, baseline; from clean scenes
def area_alerts(cells: pd.DataFrame, profile: FleetProfile) -> pd.DataFrame: ...
    # area_alert_id, t_end, cells (list), share, geometry_wkt (WGS84); ids stable over time

# divas_air/halos.py
def static_halos(layers: MapLayers) -> dict: ...                       # GeoJSON FeatureCollection, RiskZoneProps properties
def live_halos(alerts: pd.DataFrame, t: float, members: dict[str, list[str]]) -> list[dict]: ...
def forecast_paths(verdict_rows: pd.DataFrame, halos: list[dict], t: float) -> list[dict]: ...

# divas_air/pipeline.py
def run(source: str) -> Path: ...   # features -> pass 1 -> fleet -> pass 2 + cause -> assemble -> verdicts parquet
```

`windows` for the apron functions has the keys, `aux_lat`, `aux_lon` and a boolean `degraded`. `cells_from_points` uses a boolean `degraded` column if `points` has one, else it calls `is_degraded_reading`. The regional table contains qualifying cell-bins only. `baseline` is a table with columns `cell` and `baseline`; cells missing from it, and every cell when `baseline=None`, use `baseline_floor`. Cell ids are H3 strings (h3 version 4 API).

CLI: `python -m divas_air.fleet --source <name> --profile <apron|regional>`, `python -m divas_air.fleet --static-halos`, `python -m divas_air.pipeline --source <name|all>`. `make fleet` runs the regional profile on `baltic` and `control` and writes the static halos.

## Requirements

### Regional profile (the GPSJam reproduction)

1. Cell = H3 cell of each fix at `REGIONAL.h3_res`; bin = UTC day.
2. An aircraft is degraded in a cell-bin if the majority of its readings there satisfy `is_degraded_reading`. Majority, not any. Count aircraft (`asset_id`), not track segments, as the reference did. The `n_tracks` and `n_degraded` columns hold those aircraft counts.
3. Only cell-bins with at least `min_tracks` aircraft count. `share` = degraded tracks / tracks. `level`: red above `cell_share_min` (10 %), yellow above `warn_share` (2 %), else green. `flagged` = red.

### Apron profile (online, causal)

4. A window is `degraded` if pass-1 `integrity_raw` is below `UNTRUSTED_EXIT` or `sig_degraded_majority == 1`. The pipeline computes this column.
5. Evaluate at every grid time `t_end`. The tracks present are those with a window in the trailing `bin_s` seconds. A track's cell is the H3 cell (`APRON.h3_res`, about 175 m) of its latest position, and the track counts as degraded if its latest window is degraded. That window flag is already a majority judgment over 30 s of readings, so an area alert can appear within a few steps of the onset instead of a minute later.
6. A cell is `flagged` at `t_end` when all three hold: at least `min_tracks` tracks; degraded share above `cell_share_min` (most of them); and a one-sided binomial test of the degraded count against the cell's baseline rate gives p below `alpha`. The baseline is the cell's degraded rate over clean scenes, floored at `baseline_floor`; cells near tall buildings are chronically noisy and must not raise area alerts on their own.
7. `apron_baseline(windows, profile)` returns the per-cell degraded rate (`cell`, `baseline`). `baseline_apron.parquet` is that function applied to clean train scenes only (`splits.json`); module 4's training writes it (see `04_models.md` requirement 8), and `pipeline.run` and the engine read it.

### Leave-one-out features

8. For each window of track `i` at `t_end`, over its cell and the `k_ring` neighbors, counting every track except `i`: `flt_n_others`, `flt_deg_count_loo`, `flt_deg_rate_loo` (0 when there are no others), `flt_cell_flagged_loo` (the flag of its own cell recomputed without `i`), `flt_nbr_flagged_frac` (share of ring-1 neighbor cells flagged without `i`).
9. A track's own degradation must never appear in its own fleet features. That is what lets the model say "one track alone is a technical error; many together is possible interference".
10. Two passes: pass-1 integrity feeds requirement 4; the fleet features feed pass-2 integrity and the cause model. For training scenes the pass-1 scores are out-of-fold (see `04_models.md` requirement 8). After this module works, retrain module 4 so `model_card.json` says `"fleet": true`.

### Area alerts and halos

11. An area alert is a connected component of flagged cells at one `t_end`. It keeps its `area_alert_id` while it overlaps the previous step's component, so the map shows one alert that grows, not a new one every 5 s. In the pipeline and the engine an alert is held for `bin_s` after its last flagged step, so it does not blink when one member recovers for a window. Member tracks get `area_alert_id` in their verdicts; the alert queue then shows one entry instead of many.
12. Live halo: the union of an alert's cells, buffered by `HALO_SIGMA_M`, `level` = degraded share, with the member `track_ids` and the `area_gnss_unreliable` action.
13. Static halos: for each building, rings at distances where the elevation angle `atan(height / distance)` crosses 45, 30 and 15 degrees (distance = height, 1.73 x height, 3.73 x height). `expected_error_m` and `level` per ring come from the Decimeter error model's error-versus-obstruction relation, relative to open sky. Dissolve overlapping rings of the same level. Write `map/layers/halos_static.geojson` once.
14. Forecast: extrapolate each track at constant velocity for `FORECAST_HORIZONS_S`; if the path enters a live or static halo it is not already in, emit a `forecast` LineString feature with `enters_risk_zone_id` and `eta_s`, and set `early_warning` on the verdict.

### Pipeline

15. `pipeline.run(source)` writes the flat verdict table of `00_contracts.md` section 6 for a whole source. It calls the same functions the online engine calls, and uses the apron profile for every source: on airborne traffic a 175 m cell rarely holds three tracks, so the fleet features are mostly zero there, which is correct. `--source all` runs every source with a feature table.

Priorities: regional profile and apron flags with leave-one-out features are P0; the pipeline is P0; area alerts and live halos P0 (the demo shows them); static halos P1; forecast P2.

## Acceptance (`tests/acceptance/test_05_fleet.py`)

On helper data:
- a single degraded track among clean ones: its own fleet features stay at zero and its cell is not flagged;
- five tracks degraded together in one cell: the cell is flagged, each track sees the others, and one area alert covers them with a stable id over time;
- the regional majority rule: a track with a minority of degraded readings does not count as degraded.

On real data:
- Baltic: at least 70 % of the qualifying cells are red (the reference is 82 of 109, about 75 %);
- control: no qualifying cell above 2 %;
- `verdicts/synthetic.parquet` exists with the flat columns. On test scenes at least half the windows of interference events are attributed to `possible_interference` or carry an `area_alert_id`, and fewer than 30 % of single-track `technical_error` windows are;
- `model_card.json` says `"fleet": true` (module 4 retrained with fleet features).

Report in `docs/STATUS.md`: Baltic red cells / qualifying cells, control cells above 2 %, and how those compare with 82 / 109 and 0 / 172.
