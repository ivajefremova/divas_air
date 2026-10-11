# ADR Safe Mobility dataset (FCO)

Inventory of ADR's challenge package and how it enters the pipeline as source `adr_mock`. Checked on 2026-10-11 against `MANIFEST.json`.

**Redistribution.** ADR data is "uso limitato alla challenge": it may not be republished or redistributed (PDF section 9). Nothing from `data/raw/adr/`, and nothing derived from it that contains positions, goes into git. This file holds aggregates only. The geofence geometry itself is OSM-derived (ODbL, says the GeoJSON metadata), but we treat it as ADR data anyway.

## 1. Files

`data/raw/adr/` holds `safemobility-challenge-fco-dataset.tar` (77.7 MB) and a standalone `DOCUMENTAZIONE.pdf`. The ingest reads the tar directly (`divas_air.ingest.adr.read_member`). An extracted `data/raw/adr/safemobility-challenge-fco-dataset/` is used instead if it exists. Nothing is unpacked into the repo.

All 17 files in the tar match their SHA-256 and byte count in `MANIFEST.json`. The tar contains no files missing from the manifest.

| Table | Rows (manifest = actual) | Columns | Used |
|---|---:|---:|---|
| vehicle_tracks | 4,842,589 | 10 | no |
| vehicle_alarms | 236,819 | 13 | no |
| speed_events | 624,148 | 6 | no |
| area_occupancy | 2,231,914 | 5 | no |
| vehicle_registry | 4,895 (csv: 4,895) | 6 | no |
| flights | 37,889 | 16 | no |
| **asset_tracks** | **664,573** | 11 | **`adr_mock` points** |
| asset_missions | 603 (csv: 603) | 9 | cross-check only |
| approach_tracks | 228,496 | 14 | no |
| total | 8,871,926 | | |

Column lists match the manifest exactly. Also in the tar: `geofences/fco_geofences.geojson.gz` (340 features, used), `reference/fco_ops_profile.json.gz`, `reference/fco_vehicle_ops_profile.json.gz` (per-type speed aggregates, used to justify the class map), `reference/meteo_era5_fco.json.gz`.

## 2. asset_tracks

Columns: `asset_id`, `asset_class`, `timestamp_unix` (float s), `timestamp_utc`, `lat`, `lon`, `speed_kmh`, `heading_deg`, `alt_m`, `inside_aerodrome` (bool), `runway_critical_ref` (str, null outside).

- **Coverage:** one day, 2026-10-08 00:00:21 to 13:44:12 UTC (13.7 h).
- **Identity:** 603 `asset_id` values, one per mission. Each id has exactly one class. Row counts, start, end and class per id all match `asset_missions`.
- **Order:** the file is sorted by time across assets (664,065 asset changes between consecutive rows). Within an asset, time is strictly increasing: no duplicate timestamps, nothing out of order.
- **Sampling:** exactly 1.000 s between samples of an asset, except 9 gaps of 33 to 86 s. Timestamps carry a fractional offset that stays constant within each asset. No gap exceeds `TRACK_GAP_SPLIT_S` (300 s).
- **Nulls:** none, except `runway_critical_ref` (97.66 % null, as the PDF says).
- **Speed:** median 9.5 km/h, p99 33.4, p99.9 71.9, max 2,181.73 km/h. 820 samples exceed 60 km/h and 87 exceed 200 km/h.
- **Heading:** within [0, 360]; 85 samples are exactly 360.
- **alt_m:** median 2.0 m, p99.9 3.9 m, range -0.79 to 896.23 m. 162 samples are above 10 m (altitude spikes).
- **inside_aerodrome:** True 661,496 / False 3,077. It matches the `AD-LIRF` polygon on all but 8 samples, which sit on the boundary.
- **runway_critical_ref:** 07/25 13,179, 16R/34L 1,695, 16L/34R 683. It matches point-in-`RWY-*-CRIT` exactly.

### asset_class counts (samples / missions)

| class | samples | missions | | class | samples | missions |
|---|---:|---:|---|---|---:|---:|
| fork_lift | 72,102 | 29 | | prm_minibus | 15,031 | 18 |
| baggage_tug | 61,073 | 54 | | follow_me | 12,752 | 22 |
| belt_loader | 57,031 | 36 | | transporter | 11,587 | 3 |
| aircraft_taxi | 49,943 | 99 | | gpu_unit | 7,822 | 11 |
| catering_truck | 48,225 | 20 | | fuel_dispenser | 7,088 | 10 |
| cargo_loader | 47,472 | 21 | | runway_sweeper | 6,234 | 6 |
| cargo_truck | 45,762 | 67 | | sar_ambulance | 5,813 | 8 |
| pax_stairs | 42,173 | 24 | | deicing_truck | 5,148 | 4 |
| security_patrol | 39,411 | 65 | | snow_vehicle | 4,269 | 4 |
| pushback_tug | 34,530 | 22 | | sar_fire | 4,037 | 12 |
| pax_bus | 32,819 | 29 | | water_truck | 3,138 | 4 |
| ambulift | 24,614 | 20 | | bird_control | 2,179 | 4 |
| transloader | 20,445 | 4 | | lavatory_truck | 2,127 | 3 |
| | | | | works_vehicle | 1,748 | 4 |

## 3. Geofences

340 features in CRS84: 329 Polygons and 11 MultiPolygons. One polygon is invalid (`RWY-07/25-STRIP`, self-intersecting); the loader repairs it with `make_valid`. The metadata reads "Geofence semplificate per hackathon - NON per uso operativo", source OSM (ODbL).

| zone_class | n | sensitivity | speed limit (km/h) | allowed_assets | clearance_required |
|---|---:|---|---|---|---|
| aircraft_stand | 147 | medium | 10 | aircraft, handling, sar, ops_authorized | false |
| taxi_corridor | 100 | medium | 50 | aircraft, sar, ops_authorized | false |
| holding_position | 65 | high | 10 | aircraft, ops_authorized | true |
| apron | 20 | medium | 25 | aircraft, handling, sar, ops_authorized | false |
| runway_critical | 3 | high | null | aircraft, sar, ops_authorized | true |
| runway_strip | 3 | high | 30 | aircraft, sar, ops_authorized | true |
| service_road_corridor | 1 | low | 30 | handling, sar, ops_authorized | false |
| airside_boundary | 1 | medium | null | all | null |

Every rule is constant within a zone class. `allowed_assets` names four **groups**, not the 27 asset classes. ADR does not say which class belongs to which group; `adr_group` in `data/reference/adr_class_map.csv` is our assumption.

Geometry facts:

- Each `runway_critical` polygon is about 150 m wide over the runway length (the `width_m` property of 60 or 45 m is the paved width).
- Each `runway_strip` is a **ring**: the 300 m strip minus the critical area. The two have identical area and zero overlap.
- The single `service_road_corridor` (1.43 km²) covers 86 % of all asset samples and overlaps taxi corridors, stands and aprons.
- 98.7 % of samples fall in at least one zone besides the boundary. 24 % fall in two or more.
- OSM's runway 16R/34L centerline (4,308 m) is longer than ADR's critical area (3,903 m). 94 % of it lies inside.

## 4. How it enters the pipeline

### Ingest (`python -m divas_air.ingest --source adr_mock`)

Output: `data/processed/points/adr_mock.parquet` (664,573 rows, 603 tracks), byte-identical across runs. Side table: `data/processed/adr/adr_mock_side.parquet`, keyed by (`track_id`, `seq`), with `adr_row` (row in ADR's file), `asset_id`, `timestamp_unix`, `inside_aerodrome`, `runway_critical_ref`. Both paths are gitignored.

| ADR | schema | rule |
|---|---|---|
| `asset_id` | `asset_id`, `track_id = adr_mock:<asset_id>:0` | one track per asset_id, case kept (ADR's join key) |
| file order | `seq` | arrival order within the asset |
| `timestamp_unix` | `t` | as is |
| `speed_kmh` | `gs_mps` | / 3.6 |
| `heading_deg` | `heading_deg` | 360 wrapped to 0 (85 samples) |
| `alt_m` | `alt_geom_m` | as is |
| `asset_class` | `typecode_raw`, `typecode` | as is |
| `asset_class` | `domain`, `asset_class` | `adr_class_map.csv` |
| none | `on_ground` | True: the table holds surface movements only |
| none | `track_deg`, `alt_baro_m`, `vrate_mps`, `nacp`, `nic`, `sil`, `callsign` | null |

No sample is dropped or altered, apart from the heading wrap required by spec 01 requirement 7. `adr_mock` stays out of `features --source all` and out of training (features' own source list excludes it).

### Class map (`data/reference/adr_class_map.csv`)

One row per class with domain, envelope category, match (`exact` / `approx` / `none`), ADR group and a reason. It covers the 27 data classes plus 9 class names that appear only in the PDF, as aliases. The reasons cite ADR's aggregate `fco_vehicle_ops_profile` (built from vehicle_tracks, a different table), so the map was not tuned on the data ADR scores.

- 6 exact matches and 21 approximate. Since 2026-10-11 the four classes that had no match take the nearest category, marked `approx` (127,434 samples, 19 %). Share of their samples above the category's ground-speed cap, and above 1.5x the cap (the feature layer's margin):

  | class | category | > cap | > 1.5x cap |
  |---|---|---:|---:|
  | fork_lift | baggage_tractor | 0.07 % | 0.07 % |
  | cargo_truck | bus | 3.51 % | 0.29 % |
  | gpu_unit | bus | 0.69 % | 0.45 % |
  | works_vehicle | follow_me | 0.69 % | 0.17 % |

  cargo_truck is the one class above 1 % at the nominal cap (p99 33.9 km/h against bus 30.6 km/h): no category fits it better without changing its ADR group. A fork lift pivots tighter than baggage_tractor's 4 m minimum radius, so turn checks may fire on it. works_vehicle keeps no ADR group.
- A class still missing from the map (only the PDF-only `cleaning_van` now) keeps its ADR name as `asset_class`. That name is in no envelope, so the feature layer applies no envelope check to it, rather than a wrong one.
- `aircraft_taxi` becomes `other`, since ADR gives no aircraft type.
- After the fact, the share of samples above the envelope ground speed stays under 1 % for every mapped class (max 0.90 % for `aircraft_taxi`). Some of that is ADR's injected implausible speed. Unmatched `cargo_truck` has p99 33.9 km/h, which confirms that the 25 km/h truck caps would not have fit.

### Layers (`MapLayers.load(profile="adr")`)

- **Zones:** the 339 polygons other than the boundary, in `CRS_METRIC`, with the default zone columns plus `adr_zone_class`, `sensitivity`, `allowed_groups`, `clearance_required`.
- **Zone type:** runway_critical → `runway`; runway_strip → `runway_strip` (a new type, so that "runway" means ADR's critical area); taxi_corridor → `taxiway`; holding_position → `holding_point`; apron → `apron`; aircraft_stand → `stand`; service_road_corridor → `service_road`.
- **Criticality:** `params.CRITICALITY[sensitivity]` (high 1.0, medium 0.5, low 0.2). Not the OSM per-type defaults.
- **Speed limit:** km/h / 3.6; runway_critical has none.
- **Boundary:** the `airside_boundary` polygon instead of the `AIRPORT_BOX` rectangle.
- **Zone access:** `layers.zone_access`, in the shape of `zone_access.csv`. A class is allowed in a zone type if its ADR group is allowed in every polygon of that type; dwell limits come from the default table.
  - It differs from `zone_access.csv` in one cell: `sar_vehicle` at `holding_point` (ADR: not allowed).
  - It adds rows for `runway_strip` and for the unmatched classes that have a known group.
- **Buildings, route graph, runway ends:** taken from OSM. ADR provides none of these.
- **Default:** `MapLayers.load()` is unchanged: same object and zones, `profile="osm"`, `zone_access=None`.

## 5. Contradictions with the PDF

1. **Period.** The PDF gives 1 Sep to 7 Oct 2026 for the whole dataset; asset_tracks are all from **8 Oct**. Section 5.7 says "una giornata operativa continua di circa 14 ore" and lists 2026-10-08 itself.
2. **Version.** The cover and README say 1.0; section 8 and `MANIFEST.json` say **1.2**.
3. **Asset class names.** Section 6 lists 27 classes, but only 18 of them occur in the data. In the PDF only: ambulance, cleaning_van, dispenser, fire_rescue, fuel_tanker, gpu, maintenance_truck, minibus, sweeper. In the data only: fuel_dispenser, gpu_unit, lavatory_truck, prm_minibus, runway_sweeper, sar_ambulance, sar_fire, water_truck, works_vehicle.
4. **proximity_events.** The table is described in sections 6 and 8 (pair_kind, severity, join on asset_a/asset_b) but is not in the package or the manifest. `signal_anomaly_label` and `behaviour_anomaly_label` are also described but held back, as stated.
5. **Empty strings.** Section 4 says absent values are native nulls, not empty strings. `asset_missions.stand_ref` uses empty strings (482 of 603), which section 5.8 itself allows ("vuoto se non applicabile").
6. **Speed warning.** The PDF says the high tail "va filtrata" and gives p99.9 = 66 km/h, but that is vehicle_tracks. In asset_tracks the tail is the anomaly to detect (p99.9 = 71.9 km/h, max 2,181.73), so it is not filtered.
7. **PDF copies.** The PDF in the tar (18 pages, matches the manifest hash) differs in bytes and layout from the standalone `data/raw/adr/DOCUMENTAZIONE.pdf` (27 pages). Their section structure is the same.

## 6. Gaps and assumptions

Assumptions:

- `adr_group` per class is ours; ADR defines groups only on polygons.
- `on_ground=True` for every sample, `aircraft_taxi` included. Otherwise the feature layer treats an aircraft with unknown `on_ground` as airborne.

Gaps that need code we did not touch:

- **ADR zone access not yet used.** `features/mapfeat.zone_access()` reads `zone_access.csv` directly. To use the ADR table it would read `layers.zone_access` when that is not None. Until then the ADR profile uses the default access, and `runway_strip` and the unmatched classes count as allowed everywhere.
- **Heading checks are blind.** ADR gives `heading_deg` but no course over ground. `kin_course_resid` and the heading/track difference need `track_deg`, so ADR's `heading_incoherent` class goes unseen. Copying heading into `track_deg` for `adr_mock` would switch them on, at the price of false hits when a vehicle reverses.
- **Altitude spikes are blind.** `alt_geom_m` has no baro reference, so the GNSS–baro divergence features are NaN.
- **Overlapping speed limits.** Overlapping ADR zones combine by minimum speed limit. An aircraft on a taxi corridor (50 km/h) that also lies in the service road corridor (30 km/h, aircraft not allowed) gets the 30 km/h limit.

Other gaps:

- **No signal fields.** No NACp, NIC or SIL, so the signal dimension is empty, and the source cannot separate interference from technical error by signal.
- **Per-sample output.** Built in section 7.

## 7. Per-sample result (`python -m divas_air.adr`)

Package `src/divas_air/adr/`, tunables in `adr/tunables.py` (not `params.py`). It writes `data/processed/adr/asset_tracks_scored.{parquet,csv}` (gitignored): one row per ADR sample in ADR's row order, with `asset_id, timestamp_unix, trust, signal_anomaly_label, behaviour_anomaly_label, cause, evidence` and no positions. The report goes to `asset_tracks_scored_report.json`. 17 s; byte-identical reruns. Dataset version 1.2 (`MANIFEST.json`).

### Key finding: ADR's speed and heading are computed from the positions

On all 664,573 samples, `speed_kmh` / 3.6 equals the distance from the previous sample over dt in EPSG:32633 (error <= 0.013 m/s, which is rounding). `heading_deg` is the UTM grid bearing of the same step (<= 1 deg; it is about 1.8 deg off true north from grid convergence). So:

- Dead reckoning from the reported speed and heading reproduces the reported track. Its residual is blind to every position error. The detectors dead-reckon from the **velocity implied by the positions over >= 5 s** on either side of each step, and use the 1 s step innovation against that prediction.
- Speed can never contradict displacement, and heading never disagrees with the step. implausible_speed and heading_incoherent find 0 samples on ADR. The detectors still work on data whose speed and heading are independent (unit tests).
- A frozen fix reports 0 km/h (zero displacement), followed by a catch-up step of 60 to 186 m/s.

### Trust

The trust value is the engine's calibrated, smoothed integrity (`integrity`, 0 to 100) of the window ending at or just after the sample, on the same track. The verdicts come from features with `MapLayers.load(profile="adr")` and `pipeline.verdicts` (pass 1, apron fleet, pass 2), stored in `data/processed/adr/adr_mock_{features,verdicts}.parquet` because `data/processed/verdicts/adr_mock.parquet` does not exist.

- Windows (133,495): trusted 98.05 %, caution 1.84 %, untrusted 0.11 %. Samples: 98.15 / 1.80 / 0.05 %.
- The engine is mostly blind here: ADR has no `track_deg`, so the feature layer treats every moving speed as a stale report (`_reported_gs`), and there is no NACp.

### Labels (samples / tracks)

| signal | samples | tracks | | behaviour | samples | tracks |
|---|---:|---:|---|---|---:|---:|
| frozen_position | 637 | 12 | | runway_incursion | 9,549 | 105 |
| position_jump | 60 | 11 | | unauthorized_zone | 1,876 | 62 |
| fix_loss | 18 | 9 | | overspeed | 1,503 | 48 |
| multipath_noise | 1,331 | 28 | | aircraft_proximity | 4 | 1 |
| gnss_drift | 0 | 0 | | unexpected_stop | 0 | 0 |
| implausible_speed | 0 | 0 | | wrong_way | not detected | |
| heading_incoherent | 0 | 0 | | | | |
| altitude_spike | 162 | 16 | | | | |

2,207 samples (0.33 %, 72 tracks) carry a signal label and 12,905 (1.94 %, 188 tracks) a behaviour label; no sample has both. 228 of 603 tracks carry some label, 105 of them from runway_incursion alone.

**Suppressed phantoms on ADR: 0 runway incursions, 0 unauthorized zones.** No ADR position error falls on a zone violation. The only suppression is 114 overspeed samples (18 tracks), all inside position errors. On synthetic vehicles (below), suppression removes 268 runway-incursion and 6,222 unauthorized-zone samples raised on wrong positions, at the cost of 241 and 114 samples of real behaviour that sat inside a false multipath flag.

**Detectors against the engine** (samples): of the 2,207 with a signal label, the engine calls 1,719 trusted, 459 caution and 29 untrusted (22 % not trusted). Of the 12,330 samples the engine does not trust, 4.0 % carry a signal label. In 97.7 % of the windows the engine does not trust, its top evidence is `kin_speed_resid_mean` (implied vs reported speed over 30 s). ADR's position-derived 1 s speed is the likely cause; this is not verified further.

**Cause:** the signal label decides (frozen, jump, fix_loss, implausible speed and heading -> technical_error; multipath -> degraded; drift and altitude -> gnss_anomaly). Otherwise a behaviour label gives behavioral_anomaly, and otherwise the engine's cause when the engine does not trust the sample (unsound causes only), else plausible. Shares: plausible 95.99 %, behavioral 1.94 %, gnss_anomaly 1.41 %, degraded 0.35 %, interference 0.17 %, technical 0.15 %.

**Evidence:** one fixed template per label from `adr/tunables.TEMPLATES`, filled with raw values. contracts/ is frozen, so the templates live there instead of `contracts/features.csv`. A sample with no label gets the engine's top evidence sentence when the engine does not trust it, else "No signal or behaviour check fired".

### Detector rules and their numbers

Thresholds come from physical limits and ADR's bulk, and lean toward not flagging. Windows are centered: the detectors are an offline annotator, not engine features (rule 7 binds the engine).

- **fix_loss:** a pause > 3 s in the stream. Labels 1 sample before and 1 after it (ADR: 9 gaps of 33 to 86 s).
- **frozen_position:** the same lat/lon repeated for >= 5 s, with evidence of motion (reported speed, speed over the 5 s before the freeze, or the catch-up after it) >= 1 m/s. Only the repeats are labeled; the catch-up step is not a jump. ADR has 638 identical consecutive fixes, all but 3 in runs of 20 to 86 s.
- **position_jump:** step innovation > 10 m (ADR bulk median 0.90 m, p99 2.96 m). A later step that cancels it (|out + back| < 0.5 |out|, within 300 s) closes the jump, and the samples in between are labeled.
- **multipath_noise:** an 11-sample running median of the innovation > 3 m (bulk p99 1.97 m) for >= 5 samples. The median ignores one or two steps.
- **gnss_drift:** **not detected.** With position-derived speed there is no independent reference for a slow ramp. The only slow straight creeps in ADR are freeze artifacts.
- **implausible_speed:** reported speed and 5 s speed both > 1.5x the class envelope (100 km/h with no envelope), or |reported - 5 s speed| > max(5 m/s, 50 %), on a path with no position label in the window, for >= 3 samples.
- **heading_incoherent:** heading vs the 5 s displacement (>= 15 m), folded so that reversing is not flagged, > 60 deg for >= 3 samples on a smooth path.
- **altitude_spike:** |alt - the track's median| > 10 m (bulk p99.9 2.0 m; exactly 162 samples > 5 m).
- **overspeed:** the 5 s speed > the limit of the smallest containing zone x 1.2, for >= 3 samples. Where more than 1 % of a zone class's traffic exceeds its posted limit, the threshold rises to that class's p99 speed. With the plain rule, 16,646 samples in 372 of 603 tracks were flagged, 71 % of them on 10 km/h stands (median track maximum 1.62x the limit) and holding positions (median sample ratio 1.01). The bulk rule leaves service roads and taxi corridors at their posted limit. Not raised under implausible_speed.
- **runway_incursion:** ADR's `runway_critical_ref` is set and the asset's group is not among the critical area's allowed groups (aircraft, sar, ops_authorized), for >= 3 samples. Unknown group (works_vehicle): not flagged.
- **unauthorized_zone:** no containing zone other than runway_critical allows the group, for >= 3 samples. "The smallest zone forbids it" flagged 96,437 samples, because the service-road corridor overlaps the taxi corridors that vehicles cross. A pushback tug may be on taxi corridors (it tows aircraft): it accounted for 31,170 of the 33,320 samples otherwise flagged.
- **unexpected_stop:** a 5 s speed < 0.5 m/s for longer than the zone's dwell limit (zone_access.csv: runway 120 s, taxiway 300 s, holding 900 s; service road 900 s, ours). It is not raised when most of the stop is in a stand or apron, when an aircraft stops on a taxi corridor or holding position, or when the stop touches the first or last sample of a mission. 0 on ADR.
- **aircraft_proximity:** a vehicle within 20 m of a moving `aircraft_taxi` asset (5 s speed >= 1 m/s, position not flagged) in the same second, for >= 3 samples. Pushback tugs and follow-me cars are exempt. 4 samples; across all vehicle-aircraft pairs, p1 of the nearest distance is 189 m.
- **wrong_way:** **not detected.** No zone carries a direction. For the 42 taxi corridors with >= 10 aircraft missions, the dominant direction (by mission) covers at most 75 %, so no one-way rule can be inferred.

### Synthetic check (`python -m divas_air.adr --synthetic-eval`)

Vehicle tracks of ground scenes: 8,497,918 samples, 18,998 tracks, every scene (the detectors are not trained). Per-sample precision / recall against the equivalent generator event:

| ADR label | generator event | flagged | true | precision | recall |
|---|---|---:|---:|---:|---:|
| frozen_position | technical_error/freeze | 2,427 | 2,465 | 1.000 | 0.985 |
| position_jump | technical_error/jump | 49,792 | 2,258 | 0.034 | 0.741 |
| multipath_noise | degraded | 653,222 | 12,489 | 0.016 | 0.859 |
| fix_loss | technical_error/loss | 22,648 | 1,223 | 0.003 | 0.057 |
| gnss_drift | gnss_anomaly | 0 | 12,467 | n/a | 0 |
| runway_incursion or unauthorized_zone | behavioral/incursion | 11,607 | 7,760 | 0.204 | 0.305 |
| overspeed | behavioral/speeding | 38,305 | 2,505 | 0.016 | 0.252 |

Recall is the informative number here. Precision is low because the generator's noise floor is far heavier than ADR's: the clean-sample step innovation has p99 8.0 m against ADR's 3.0 m (10.4 m at a 2 s cadence, right at the jump threshold). The ADR thresholds were not retuned on these results. fix_loss recall is low because the generator labels every fix of a loss event, not only those around the gap; its false flags are mostly dropped fixes in degraded and interference events. Overspeed truth uses OSM limits, while the detector reads ADR's zones.

### Assumptions

1. ADR groups per class are ours (`adr_class_map.csv`); works_vehicle has none, so it never gets an access label.
2. The pushback-tug role exemption on taxi corridors; pushback and follow-me are exempt from aircraft_proximity.
3. Stands and aprons are where assets park; ADR has no parking layer.
4. The service-road dwell limit (900 s) is ours; zone_access.csv has none.
5. The overspeed bulk rule (above) replaces the posted 10 km/h on stands and holding positions.
6. Label precedence on a sample: signal frozen > jump > fix_loss > multipath > drift > speed > heading > altitude; behaviour incursion > unauthorized > proximity > overspeed > stop.
7. Behaviour labels are suppressed on samples with frozen_position, position_jump, fix_loss, multipath_noise or gnss_drift; overspeed also under implausible_speed.
8. Trust is the engine run on points as ingested. `track_deg` is left null rather than copied from heading, so the engine's speed checks stay off.
