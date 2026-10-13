# Divas Security

**A GNSS trust layer for airside operations at Rome Fiumicino (LIRF).**
Before you act on a position, Divas Air tells you whether to believe it.

Built in ~14.5 hours for the Aeroporti di Roma *Track Trust* challenge at **Safe Mobility Hack 2026** (Rome, Oct 10–12), where it won. Pitched as **Divas Security**.

For every tracked aircraft or ground vehicle, Divas Air scores whether its position data can be trusted, how confident that verdict is, why, and what the operator should do. It has two parts:

- **Trust API** (FastAPI): scores every track on a 30 s window every 5 s.
- **Risk Map**: the operator's screen. Tracks colored by trust, GNSS risk halos, a click-through verdict card per track, and an offline demo replay.

Onboarding a new airport takes two configuration files (geofences and vehicle types). Nothing is retrained per airport.

---

## Results

Held-out evaluation on 166 scenes never seen in training, against a naive baseline (fixed speed and position-jump thresholds only):

| Metric | Divas Air | Baseline |
|---|---|---|
| Integrity: recognizing trustworthy data (AUROC) | **0.99** | 0.83 |
| Alert precision | **0.96** | 0.13 |
| Time to detect (onset → state change) | **11 s** | — |

`reports/metrics.json` is the source of truth; `python -m divas_air.eval.report` regenerates every number and figure.

---

## Core idea: four dimensions, two axes

Every track gets four sub-scores, named as in ADR's brief. They fold into two independent axes, which is what separates **bad data** from **abnormal behavior**: a phantom runway incursion (untrusted data, verify by radio) versus a real one (trusted data, act now).

| Dimension | Checks | Axis |
|---|---|---|
| Kinetic | implied vs reported speed, acceleration, turn rate and radius vs class limits; heading vs course | **Integrity** — is the data sound? |
| Temporal | gaps, duplicates, out-of-order points, frozen positions | **Integrity** |
| Spatial | geofences, distance from authorized route, position inside buildings | **Normality** — is the behavior expected? |
| Contextual | speed vs zone limit, dwell time, phase consistency, approach path, identity vs behavior | **Normality** |

### Output per track, per window

| Field | Meaning |
|---|---|
| `integrity` | 0–100, `100 × (1 − calibrated P(unsound))`, smoothed with hysteresis |
| `normality` | min of the spatial and contextual scores |
| `trust_state` | `trusted` / `caution` / `untrusted` (enter untrusted < 40, leave > 55) |
| `cause` | `plausible`, `degraded`, `technical_error`, `gnss_anomaly`, `possible_interference`, `possible_spoofing`, `behavioral_anomaly` |
| `confidence` | separate from the score: low with few fixes, long gaps, or two close causes |
| `severity` | `max(1 − integrity/100, 1 − normality/100) × zone criticality` |
| `evidence` | up to three template sentences with raw values, e.g. *"implied speed 41 m/s vs 8 m/s reported"* |
| `action` | fixed operator text, looked up from quadrant and severity |

The full contract is in `src/divas_air/contract.py` and `contracts/*.schema.json`, with examples in `contracts/examples/`.

### Models

- **Dimension scores**: deterministic, from features against class limits.
- **Integrity and cause**: monotone-constrained LightGBM, isotonic calibration (integrity), temperature scaling (causes).
- **Normality**: rules, not a model; there are no labels for "normal behavior".
- **Fleet layer** (two passes): pass 1 scores integrity alone; H3 cells (~175 m on the apron) are flagged when ≥ 3 tracks, most of them degraded, exceed the cell's baseline; pass 2 adds leave-one-out fleet features so the model separates *possible interference* (many tracks together) from *technical error* (one track alone).
- **Explanations**: LightGBM's built-in TreeSHAP (`pred_contrib=True`) fills fixed sentence templates. No generated text.

---

## Pipeline

```
raw sources ─► 1 ingest ─► points ─► 3 features ─► 4 scoring + models ─► 5 fleet + pipeline ─► verdicts
2 generator ─► points (labeled) ─┘                                           │
                                                   6 engine + API + replay ◄─┤
                                                   8 evaluation report     ◄─┘
```

Real and synthetic tracks share one point schema (`src/divas_air/schema.py`), so every stage after ingest is identical for both.

| # | Module | Entry point |
|---|---|---|
| 1 | Ingest: all sources → unified schema, type overrides applied | `python -m divas_air.ingest --source all` |
| 2 | Synthetic generator: vehicles and taxiing aircraft on the route graph, causes injected and labeled | `python -m divas_air.synth`, `python -m divas_air.synth.demo` |
| 3 | Features: 30 s windows on a 5 s grid, five feature groups | `python -m divas_air.features --source all --calibrate` |
| 4 | Dimension scores, integrity and cause models, calibration, SHAP | `python -m divas_air.models.train` |
| 5 | Fleet layer and end-to-end pipeline | `python -m divas_air.fleet`, `python -m divas_air.pipeline --source all` |
| 6 | Trust engine, API, offline replay bundle | `uvicorn divas_air.api.app:app`, `python -m divas_air.api.replay` |
| 7 | Risk Map + demo replay | `map/` |
| 8 | Evaluation report | `python -m divas_air.eval.report` |

Each module has a spec in `specs/NN_name.md` (inputs, outputs, acceptance test). Cross-module contracts are in `specs/00_contracts.md` and enforced in code.

---

## Quickstart

Requires Python 3.12.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make contracts                                   # contract tests
pytest                                           # all module tests
```

Full rebuild, assuming the raw data is in `data/raw/` (see [Data](#data)):

```bash
python -m divas_air.ingest --source all
python -m divas_air.synth
python -m divas_air.features --source all --calibrate
python -m divas_air.models.train
python -m divas_air.pipeline --source all
python -m divas_air.eval.report                  # → reports/REPORT.md, reports/figures/
```

Serve the API and build the demo:

```bash
uvicorn divas_air.api.app:app --reload           # POST /tracks, GET /verdicts, GET /risk-zones
python -m divas_air.api.replay                   # offline replay bundle for the map
make stub                                        # contract-conforming stub server for frontend work
```

The trained models (`artifacts/models/`) and the replay bundle (`data/processed/demo/replay/`) are committed, so the API and the demo run without raw data.

---

## Data

Small outputs are in git; raw data stays local.

| Asset | Source | Role |
|---|---|---|
| FCO approach tracks, 7+ days | [adsb.lol](https://adsb.lol) (ODbL), ~2.7 s sampling | real-data validation, false-alarm rate, semi-synthetic approach scenes |
| Baltic interference day 2026-10-05 + France control | adsb.lol + [GPSJam](https://gpsjam.org) reference | real-interference test for the fleet layer |
| Aircraft types | adsb.lol type codes → `aircraft_types.csv` (161 codes, 8 classes) + `type_overrides.csv` | class limits per aircraft |
| Movement limits | `envelopes.csv` (8 aircraft + 6 vehicle classes) | kinetic thresholds, generator limits |
| GNSS error model | Google Smartphone Decimeter Challenge 2023 | generator noise, static halos |
| Map layers | ADR orthophoto, OSM, OurAirports, enriched in QGIS | spatial/contextual features, map, generator routes |
| Satellite overview | Copernicus Sentinel-2 L2A | zoomed-out basemap |
| Synthetic apron tracks | module 2 | training and benchmark (no ground ADS-B coverage at FCO) |

Notes on the reference files:

- **`type_overrides.csv`** corrects four aircraft in real FCO traffic whose database type (DA42, BE58, EFOX, CTLN) contradicts their airline callsign and airliner flight profile; all are set to A320.
- **`envelopes.csv`** gives realistic maxima per class; code applies a 1.5× margin. Validated at ~0% over-limit on real traffic. Helicopters skip kinematic checks (hover and sideways flight are normal).

### Layout

```
data/
  raw/                  local only, never committed
  processed/            points, features, verdicts (parquet); synth events and replay bundle in git
  reference/            aircraft_types, envelopes, type_overrides, zone_access, dimension_thresholds
map/
  layers/               GeoJSON: zones, routes, buildings, static halos
  tiles/                orthophoto XYZ tiles
artifacts/models/       trained models, calibration, splits, model card
contracts/              JSON schemas, feature registry, examples
reports/                metrics.json, REPORT.md, figures
specs/                  one spec per module + 00_contracts.md
src/divas_air/          the package
scripts/                data collection helpers
```

---

## Design rules (learned from real data)

1. **Every rate is computed over ≥ 5 s, never point to point.** Point-to-point rates gave ~0.2% false over-limits on clean traffic.
2. **Degradation is judged on the majority of readings in a window, never single values.** The majority rule reproduced GPSJam on the Baltic day (82 of 109 hexagons red; France control 0 of 172).
3. **Splits are by scene, never by row.** Windows overlap and fleet features couple tracks within a scene.
4. **Units**: meters, m/s, seconds; WGS84 for storage, geodesic distances between fixes, UTM 33N (EPSG:32633) against map layers.

All tunable constants are in `src/divas_air/params.py`; paths, CRS and area boxes in `src/divas_air/config.py`.

---

## Scope

**In:** aircraft on approach, taxiing aircraft, handling vehicles, SAR vehicles, airport-area interference.
**Out:** RF signal processing, automatic actions (the system recommends, the operator decides), real ADR operational data.

## Licensing

ADS-B data from adsb.lol is under ODbL. Public data is for development and validation; in production the engine runs on the customer's own feeds.
