# Divas Security web map

The operator screen for Divas Air: a live-looking map of Fiumicino that shows, for every aircraft and vehicle, how much to trust its position. It plays the pipeline's replay bundle (module 6) and never recomputes anything: every score, cause, confidence and action on screen comes from Matteo's model.

## Run it

```bash
python scripts/serve_map.py          # then open http://localhost:8080/app/web/
```

- The first click anywhere enables the warning sound (browsers require a click before playing audio).
- Phone, same Wi-Fi: `python scripts/build_site.py`, then `python -m http.server 8090 --bind 0.0.0.0 -d site`, and open `http://<your-mac-ip>:8090` on the phone.
- Public link (GitHub Pages) and QR code: `scripts/build_site.py` builds `site/`, `scripts/make_qr.py` writes `qr.png`. Publishing is a manual step; nothing is online until someone runs it.

## The demo story

1. **Demo** (top left) lists the pipeline's events: Full demo scene, Phantom runway incursion, Real runway incursion, Sector GNSS interference.
2. Each demo starts calm. About 4 s later a **banner** drops in at the top, with a sound and a dashed line to the vehicle.
3. **Click the banner** to go straight to the issue:
   - single vehicle: the map jumps to it and opens its dashboard;
   - jamming: the map jumps to the **first vehicle in the priority queue**, opens its dashboard and the **Impacted vehicles** card.
4. **Vehicle dashboard:** confidence and likely cause (pink boxes); Integrity, Normality and the four scores (kinetic, temporal, spatial, contextual); integrity over the last 5 minutes; what to do. **Check impact** opens the impacted-vehicles card.
5. **Impacted vehicles** is a priority queue, built only from pipeline fields: severity level, zone criticality (runway > taxiway > apron/road), moving before stopped, aircraft before vehicles, lower integrity first. Recovered vehicles drop to the bottom. Click a vehicle to open its dashboard; with a dashboard already open, it opens as a **compare window** instead, so several can be compared side by side.
6. **Every window can be dragged** (desktop) by its background and stays where it is dropped.

## Map views (bottom left)

| View | Shows |
|---|---|
| Photo | Satellite or orthophoto, all traffic, alerts |
| Schematic | Runways (navy), taxiways (green), service roads (brown), stands, holding points (red). Click anywhere for the place name and coordinates. No alerts here |
| Cameras | Simulated camera positions; click one to see what it covers (pink) and its dashboard. Only vehicles flagged as anomalies are shown |

## Reading the map

- **Colour = can we trust the position.** Type colour (or blue for aircraft) when trusted, amber for reduced accuracy, a red dashed outline for an unreliable position.
- **Pink ring:** the vehicle the current alert is about.
- **"Enters interference area in N s":** the pipeline's forecast for a vehicle heading into live interference.
- Trusted tracks are smoothed for display; flagged tracks are drawn exactly as reported, because the jump is the information.

## Data

| Source | Path | Notes |
|---|---|---|
| Replay bundle (real) | `data/processed/demo/replay/` | Written by the pipeline (module 6); always used when present |
| Simulated scenarios | `data/processed/demo/replay_fake/` | Fallback only; `scripts/make_fake_replay.py` |
| Map layers | `app/web/data/*.geojson` | Slim copies of `map/layers/` and `map/fco_routes.graphml`; `scripts/build_web_layers.py` |
| Cameras (simulated) | `app/web/data/cameras.geojson`, `camera_coverage.geojson` | `scripts/fake_cameras.py`; no real camera positions are known |
| Camera footage | `app/web/media/camera.mp4` | Optional; shown in every camera dashboard when present |
| Orthophoto tiles | `map/tiles/{z}/{x}/{y}.jpg` (or `DIVAS_TILES_DIR`) | Not in git; the online satellite image is used when missing |

## Files

- `index.html`: page structure.
- `style.css`: one deep-blue theme and fixed layout zones (the windows never overlap until you move them).
- `app.js`: loading, playback, map layers, banner, dashboards, priority queue, cameras, movable windows.
- `config.js`: data paths (the published site gets its own copy from `build_site.py`).
