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

- 6 exact matches, 17 approximate, and **4 with no match**: `fork_lift`, `cargo_truck`, `gpu_unit`, `works_vehicle`. Together they hold 127,434 samples (19 %).
- An unmatched class keeps its ADR name as `asset_class`. That name is in no envelope, so the feature layer applies no envelope check to it, rather than a wrong one.
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
- **Per-sample output.** ADR scores per sample; we output per 30 s window every 5 s. Mapping each sample to its window is still to be done; the side table keeps `adr_row` for the join.
- **Unmatched classes.** The 4 classes without a match get no envelope check. Fixing that needs new envelope categories, and `envelopes.csv` is tied to the frozen `schema.ASSET_CLASSES`.
