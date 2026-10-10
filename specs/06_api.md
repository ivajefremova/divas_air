# 06 Engine, Trust API and replay bundle

**Goal:** the online form of the pipeline, the three API routes, and the offline replay bundle the map plays on stage.

**Depends on:** 00, 4, 5. **Owns:** `src/divas_air/engine.py`, `src/divas_air/api/`, `tests/unit/test_engine*.py`, `test_api*.py`.

The demo is the product for three minutes. It runs offline from local files, from one button, and a failure here is the one failure everyone sees. Favor boring and robust.

## Outputs

`data/processed/demo/replay/manifest.json` and `frames.jsonl` (`contract.ReplayManifest`, one `contract.ReplayFrame` per line).

## Interface

```python
# divas_air/engine.py
class TrustEngine:
    def __init__(self, layers: MapLayers | None, bundle: ModelBundle,
                 profile: FleetProfile = params.APRON): ...          # layers=None: no map features
    @classmethod
    def from_disk(cls) -> "TrustEngine": ...                       # default layers, models, baseline, static halos
    def ingest(self, points: pd.DataFrame) -> None: ...            # unified schema; keeps BUFFER_S per track
    def step(self, now: float) -> list[contract.Verdict]: ...      # one verdict per active track at grid time `now`
    def risk_zones(self, now: float) -> contract.RiskZones: ...    # static + live + forecast
    def history(self, track_id: str, seconds: float = params.HISTORY_S) -> list[contract.Verdict]: ...

# divas_air/api/app.py
app: FastAPI
```

CLI: `uvicorn divas_air.api.app:app`; `python -m divas_air.api.replay [--source demo]`.

## Requirements

### Engine

1. `step(now)` runs features, pass 1, fleet, pass 2, cause and verdict assembly for every active track (one with a fix in the last `TRACK_GAP_SPLIT_S`), by calling the module 3, 4 and 5 functions. No score is implemented twice.
2. Parity: feeding a track through `ingest` and `step` in time order gives the same integrity, normality, states and cause as `pipeline.run` on the same points. State kept per track: the point buffer, the dwell timer, the smoothed score and the two state machines.
3. A track with a single fix still gets a verdict: low confidence, cause from the rules, no crash. A track with no fix for `TRACK_GAP_SPLIT_S` is dropped.
4. `step` for 200 active tracks takes under one second on a laptop. If it does not, cache per-track features and recompute only tracks with new fixes.
5. Models and layers load from disk at construction. Nothing touches the network.

### API

6. Routes, shapes from `contract.py`:
   - `POST /tracks` (`TracksIn` -> `IngestAck`): converts each point to the unified schema and ingests it. Aircraft class comes from `asset_class`, else from `typecode` via `asset_class_for`, else `other`, with overrides applied. A vehicle must state its `asset_class`: an unknown vehicle must not inherit another class's access rights. `source="live"`; `track_id` is `live:<asset_id>:<segment>`; `seq` is assigned by the server. A point with an unknown `asset_class`, or a vehicle without one, is rejected individually with a reason; the rest of the batch is accepted.
   - `GET /verdicts` (`VerdictsOut`): the latest verdict per active track. `?track_id=` filters; `?history_s=` returns that track's verdicts over the last N seconds for the verdict card's five-minute chart.
   - `GET /risk-zones` (`RiskZones`).
   - `GET /health`: `{"status": "ok", "stub": false, "schema_version": ..., "models": ..., "tracks": n}`.
7. The engine clock is data time: `now` is the latest fix time seen, rounded down to the stride grid. `POST /tracks` steps the engine through every grid time between the previous clock and the new one, so a batch covering 90 s yields 18 verdicts per track in the history. This makes replay and live identical.
8. CORS open for all origins. Responses are built as contract models.

### Replay bundle

9. `python -m divas_air.api.replay` reads `points/demo.parquet` and `synth/demo_events.parquet`, steps a fresh engine from the first to the last grid time every `REPLAY_STEP_S`, and writes one frame per step: the verdicts and the risk zones at that time.
10. `manifest.json` lists the three events with `event_id` `ev_phantom`, `ev_real`, `ev_sector`, kinds `phantom_incursion`, `real_incursion`, `sector_interference`, their times and member tracks, and a short operator-facing title each.
11. The three scripted events must read correctly in the bundle. This is the demo's acceptance test:
    - `ev_phantom`: the tractor's verdict becomes `data_fault` with action `verify_radio` within 15 s of onset, severity critical or high;
    - `ev_real`: the truck's verdict becomes `real_event` with action `act_now` within 15 s of onset, with integrity staying trusted;
    - `ev_sector`: within 60 s of onset at least three member tracks share one `area_alert_id` and a `live` risk zone carries it;
    - outside the events (from 5 s before each onset to 60 s after each end), no verdict in the bundle is `untrusted` with severity critical, and at least 90 % of verdicts are `trusted`.
12. If an event does not read correctly, fix the cause (features, thresholds, generator magnitudes via the proper module), not the bundle. Never hand-edit frames.
13. The bundle is deterministic and committed, so the map team and the stage laptop have it without running anything.

### Upgrade 3: red-team route (only after everything above passes)

14. `POST /redteam` with `{"kind": "spoof_sar_runway" | "jam_sector", "t": ...}` calls `synth.inject` on the engine's incoming replay stream. The map reacts on the next step. Keep it behind an environment flag `DIVAS_REDTEAM=1`.

## Acceptance (`tests/acceptance/test_06_api.py`)

- `GET /health`, `POST /tracks` with the contract example, `GET /verdicts`, `GET /risk-zones` all return contract-valid bodies.
- Any track returns the output contract: a single fix, a vehicle with only the required fields and its class, an untyped aircraft. A vehicle without a class and an unknown class are rejected point by point.
- The replay bundle exists, validates line by line, and satisfies requirement 11.
- Engine and batch pipeline agree on the demo scene (`verdicts/demo.parquet` from `pipeline.run("demo")`): `integrity_raw` within 1 point and the same `trust_state` on at least 98 % of windows.
- `step` meets the latency bound.

Report in `docs/STATUS.md`: step latency at 200 tracks, and for each demo event the seconds from onset to the expected verdict.
