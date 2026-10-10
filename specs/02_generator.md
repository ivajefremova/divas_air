# 02 Synthetic generator

**Goal:** labeled tracks for every cause, realistic enough that a model trained on them behaves on real traffic. Also the scripted demo scene.

**Depends on:** 00, map layers, GNSS error model. Not on module 1 for ground scenes; approach scenes need `points/fco.parquet`. **Owns:** `src/divas_air/synth/`, `src/divas_air/geo/` (the map-layer loader, which module 3 also uses: build it first), `tests/unit/test_synth*.py`, `tests/unit/test_geo*.py`.

There is no ground coverage at FCO in the public data, so the apron is entirely synthetic. The risk is circularity: a model that learns the generator's quirks instead of the physics. Every requirement below that sounds fussy is there to prevent a quirk.

## Inputs

- Route graph, zones, buildings from `map/layers/` (names in `docs/DATA_INVENTORY.md`).
- `data/reference/envelopes.csv`: generator limits are the class limits themselves, not limits x 1.5.
- GNSS error model derived from the Decimeter dataset (path in the inventory). It is phone-grade, so use it for relative behavior (open sky vs obstructed), not absolute accuracy.
- `points/fco.parquet` for approach scenes.

## Outputs

- `data/processed/points/synthetic.parquet` and `data/processed/synth/events.parquet`
- `data/processed/points/demo.parquet` and `data/processed/synth/demo_events.parquet`

Events table columns: `event_id`, `scene_id`, `cause`, `t_onset`, `t_end`, `track_ids` (list), `region_wkt` (WGS84, null for single-track events), `params_json`.

## Interface

```python
# divas_air/synth/__init__.py
def generate_scene(seed: int, *, duration_s: float = 600.0, n_vehicles: int = 20, n_aircraft: int = 6,
                   events: list[dict] | None = None, layers=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One ground scene: (labeled points, events). events=None draws events at random; [] gives a clean scene."""

def inject(points: pd.DataFrame, cause: str, *, onset_t: float, duration_s: float,
           track_ids: list[str] | None = None, region=None, params: dict | None = None,
           seed: int = 0, event_id: str | None = None, layers=None) -> pd.DataFrame:
    """Pure: returns a new frame with the anomaly applied and labels set. Never mutates its input."""
```

```python
# divas_air/geo/__init__.py  (build this first; module 3 depends on it)
class MapLayers:
    @classmethod
    def load(cls, airport: str = "LIRF") -> "MapLayers": ...
    zones: gpd.GeoDataFrame      # CRS_METRIC; zone_id, zone_name, zone_type, criticality in [0, 1], speed_limit_mps
    buildings: gpd.GeoDataFrame  # CRS_METRIC; height_m
    boundary                     # shapely polygon, CRS_METRIC
    runways: pd.DataFrame        # one row per runway end: threshold lat/lon, elevation_m, bearing_deg
    routes: dict                 # "vehicle" and "aircraft" -> networkx graph, node positions in CRS_METRIC
    def route_distance_m(self, x, y, domain: str) -> np.ndarray: ...   # to the nearest authorized route for that domain
    def to_metric(self, lon, lat) -> tuple[np.ndarray, np.ndarray]: ...
    def to_wgs84(self, x, y) -> tuple[np.ndarray, np.ndarray]: ...
```

`MapLayers.load` normalizes whatever the layers call things into the names above: criticality labels through `params.CRITICALITY`, speed limits to m/s, zone types onto the names used in `zone_access.csv`. The inventory has the real names. `generate_scene(layers=None)` loads the default layers itself.

`inject` accepts any frame in the unified schema, labeled or not. If label columns are absent it adds them (`label_true_*` = the input position, `scene_id` and `base_track_id` from `params` or the track id). It keeps every `track_id` unchanged. `track_ids` selects tracks; `region` (a shapely geometry in WGS84) selects every track inside it, which is how area events are made. The red-team button (upgrade 3) calls this same function on the live replay.

CLI:
- `python -m divas_air.synth --seed 42 [--scenes 200] [--approach-hours 40]`
- `python -m divas_air.synth.demo` (fixed seed, fixed script)

## 1. Base motion (ground scenes)

1. Vehicles drive origin-to-destination paths on the vehicle route graph; taxiing aircraft go stand to holding point or back on the aircraft graph. Speeds follow zone limits and class limits, with acceleration and turn rate inside the envelope, and stops at stands.
2. Class mix covers all six vehicle classes and at least narrowbody and widebody aircraft.
3. Sampling: each vehicle reports every 1 or 2 s (drawn per asset, so the models cannot key on one rate); aircraft with intervals drawn from the empirical interval distribution of `fco` (median about 2.7 s), so synthetic and real aircraft look alike in time. If `points/fco.parquet` does not exist yet, use a fixed fallback (log-normal, median 2.7 s) and switch to the empirical one when it does. Add realistic timestamp jitter.
4. Reported fields: `gs_mps` and `track_deg` from the true velocity plus small sensor noise, independent of the position noise; `heading_deg` equal to course when moving forward; `on_ground=True`; `nacp`, `nic` from the simulated accuracy (standard NACp bounds: under 3 m is 11, under 10 m is 10, under 30 m is 9, under 93 m is 8, under 185 m is 7); `sil=3`.

## 2. Nominal noise

5. Position error is time-correlated, not white: a first-order Gauss-Markov process per axis, correlation time 20 to 60 s, plus a small white term. White noise at these sampling rates creates implied-speed noise that real receivers do not have, and the model would learn it.
6. Error scale comes from the error model: an open-sky sigma, multiplied by the model's obstructed-to-open ratio as a function of the highest building elevation angle `atan(height / distance)` at the fix. Fixes near tall buildings are noisier in clean data too. That is `plausible`, and it is what the static halos show.
7. Nominal noise applies to every point of every track at all times, including during `behavioral_anomaly` events.

## 3. Causes

One physical mechanism each. Draw magnitudes from wide ranges so there are easy and hard cases; record the draw in `params_json`.

| Cause | Mechanism | What changes | What stays normal |
|---|---|---|---|
| `plausible` | nominal motion and noise | | everything |
| `degraded` | multipath or poor geometry on one asset | noise scale x 3 to 10, NACp and NIC drop 1 to 3, occasional missed fixes | no bias, no jumps; other assets unaffected |
| `technical_error` | device or datalink fault | one or more of: frozen position while speed is reported; duplicated or out-of-order timestamps; a single jump of 50 to 2000 m, held or reverted; loss of fix for 10 to 60 s | NACp and NIC unchanged (the transponder thinks it is fine) |
| `gnss_anomaly` | receiver-level position fault on one asset | bias growing at 0.5 to 5 m/s with rising noise, NACp and NIC falling as it grows; for aircraft, GNSS altitude drifts from baro | reported speed and course (true motion); other assets |
| `possible_interference` | jamming over an area | every asset inside a disk of radius 150 to 600 m, for 60 to 240 s: NACp and NIC collapse, noise x 5 to 20, missed fixes and losses of fix; severity fades toward the edge | motion; assets outside the disk |
| `possible_spoofing` | a coherent false position | smooth offset growing at 0.5 to 3 m/s with nominal-looking noise and nominal NACp and NIC; for aircraft, GNSS altitude diverges from baro; reported speed and course follow the true motion, so implied and reported disagree slightly but persistently | integrity indicators; smoothness |
| `behavioral_anomaly` | the asset really does something it should not | the true path: leaves the authorized route, enters a zone its class may not enter (runway incursion), exceeds the zone speed limit, or dwells too long | all data quality: nominal noise, nominal NACp, consistent speed |

8. `behavioral_anomaly` changes `label_true_*` too, because the motion is real. Every other cause leaves `label_true_*` at the true path and moves only the reported position.
9. Labels are per point: `label_cause` is the cause while the event is active on that point, `plausible` otherwise. `label_onset_t` and `label_event_id` are set on the affected track's points from onset on.
10. `inject` never renames a track. The scene builder gives an injected copy a new `track_id` only if it keeps the clean original in the same scene; `base_track_id` always names the original.

## 4. Scenes and balance

11. A ground scene is 10 minutes with 15 to 40 assets and 0 to 3 events. About a third of the scenes are fully clean.
12. Approach scenes (P0, after ground scenes work): one hour of real `fco` traffic from non-held-out days is one scene. A track belongs to the scene of the hour in which it starts, whole, so no `base_track_id` spans two scenes. Leave most tracks untouched (`plausible`), inject `degraded`, `technical_error`, `gnss_anomaly`, `possible_spoofing` on single tracks and `possible_interference` on a sector. No `behavioral_anomaly` on approach. Never read the last `params.REAL_HOLDOUT_DAYS` days.
13. Every non-plausible cause accounts for at least 5 % of anomalous points, and plausible points are at least half of all points.
14. `scene_id` is unique per scene and never shared between a ground scene and an approach scene.
15. Deterministic: the same seed gives an identical frame.

## 5. Demo scene

16. `python -m divas_air.synth.demo` writes one 10-minute ground scene with about 25 vehicles and 6 taxiing aircraft and exactly three events, in this order, with clean gaps between them:
    - `ev_phantom`: `technical_error` on one baggage tractor near a runway; a jump places it on the runway for about 60 s, then it reverts.
    - `ev_real`: `behavioral_anomaly`; one fuel truck drives onto a runway and stays about 60 s. Its `t_onset` is the moment it enters the runway zone.
    - `ev_sector`: `possible_interference` over one apron sector with at least five assets inside, about 150 s. At least four of them stay inside one H3 cell at `params.APRON.h3_res` for the whole event (around one stand, say): the fleet layer flags per cell and needs three tracks in it. Check the cell ids with `h3` when scripting the scene.
17. Every demo asset reports from the first to the last second of the scene, so each replay frame has all of them. Start with at least 60 s with no event.
18. Event ids are exactly `ev_phantom`, `ev_real`, `ev_sector`. Module 6 and the map team key on them. Leave at least 90 s of clean time between one event's end and the next one's onset, and keep the phantom's and the truck's tracks otherwise clean.

## Acceptance (`tests/acceptance/test_02_generator.py`)

- `points/synthetic.parquet` and `points/demo.parquet` pass `validate(labeled=True)`.
- All seven causes present; balance as in requirement 13.
- Nominal noise: on plausible points the error (reported minus true) has a sensible scale and lag-1 autocorrelation above 0.5.
- Behavioral anomalies carry the same error scale as plausible points.
- Every `possible_interference` event affects at least three tracks.
- `inject` is pure, changes nothing before onset or on other tracks, and sets the labels.
- The demo scene has the three events with the right ids, causes and classes.
- `generate_scene` is deterministic.

Report in `docs/STATUS.md`: scenes, points and tracks per cause, and the measured noise scale.
