# LIRF map layers – files, attributes and assumptions

Airport: Rome Fiumicino (LIRF / FCO) · Safe Mobility Hack 2026, ADR challenge (Track Trust)
Last updated: 2026-10-11

## Where the data is

| Copy | CRS | Use |
|---|---|---|
| `layers/*.geojson` | EPSG:4326 (lon, lat) | One file per layer, for the web demo and the AI team |
| `network/*.geojson` | EPSG:4326 (lon, lat) | Routable network (nodes + edges) |
| `LIRF_map.gpkg` | EPSG:32633 (WGS 84 / UTM 33N, meters) | Same layers in one file, in meters, plus the `settings` table |

- GeoJSON coordinates are **longitude, latitude** (not lat, lon).
- **Never compute distances or speeds in EPSG:4326.** Reproject to EPSG:32633 first, or use the GeoPackage.

## Layer files

| File | Geometry | Count | Source |
|---|---|---|---|
| `runways.geojson` | polygon | 3 | OurAirports `runways.csv` (LIRF): end coordinates + width, built in UTM 33N |
| `taxiway_lines.geojson` | line (centerline) | 231 | OSM `aeroway=taxiway` / `taxilane` |
| `aprons.geojson` | polygon | 19 | OSM `aeroway=apron` |
| `stands.geojson` | point | 78 | OSM `aeroway=parking_position` |
| `holding_points.geojson` | point | 65 | OSM `aeroway=holding_position` |
| `service_roads.geojson` | line | 471 | OSM `highway=service` |
| `buildings.geojson` | polygon | 24 | OSM `aeroway=hangar` / `aeroway=terminal` |
| `sensitive_zones.geojson` | polygon | 37 | Built by rules: runway strips, runway holding areas, fuel stations |
| `restricted_parking.geojson` | polygon | 14 | OSM `amenity=parking` (private / reserved) inside the airport boundary |
| `taxiway_area.geojson` | polygon | 4 | Taxiway / taxilane centerlines buffered: `core` (paved width) and `tolerance` (+ GNSS margin) |
| `approach_corridors.geojson` | polygon | 6 | Funnel from each runway end, 18 km long, ±7.5° |
| `key_points.geojson` | point | 69 | 4 fire stations (OSM) + 65 holding points |
| `airport_boundary.geojson` | polygon | 1 | OSM `aeroway=aerodrome` |
| `runways_centerline.geojson` | line | 3 | OSM runway centerlines |
| `../network/network_nodes.geojson` | point | 1307 | Junctions of the taxiway + service road network |
| `../network/network_edges.geojson` | line | 1734 | Network segments between two nodes |

## Common zone attributes

Every zone layer has these three:

| Attribute | Type | Meaning |
|---|---|---|
| `zone_type` | text | `runway`, `taxiway`, `apron`, `stand`, `parking`, `restricted`, `building`, `other` |
| `criticality` | integer | `1` low · `2` medium · `3` high (runways, holding areas) |
| `speed_limit_kmh` | integer | Max vehicle speed inside the zone, km/h. `0` = no driving (buildings) |

## Attributes per layer

### runways
| Attribute | Meaning |
|---|---|
| `id` | Runway designator, e.g. `16L/34R` |
| `width_m` | Paved width in meters (OurAirports `width_ft` × 0.3048) |
| `length_m` | Length in meters, measured between the two end coordinates in UTM 33N |
| `heading_deg_true` | True heading of the low-numbered end, degrees |
| `zone_type` / `criticality` / `speed_limit_kmh` | `runway` / `3` / `near_runway_vehicle_speed_kmh` (30) |
| `source` | Where the geometry comes from |

### taxiway_lines
| Attribute | Meaning |
|---|---|
| `name` | Taxiway name (A, B, …) from OSM `ref` or `name`, where OSM has one |
| `kind` | `taxiway` or `taxilane` (apron taxilane) |
| `max_speed_kt` | Max aircraft taxi speed, knots: `taxiway_max_speed_kt` (25) or `taxilane_max_speed_kt` (10) |
| `one_way` | Whether the taxiway is one-way (from OSM `oneway`) |
| `speed_source` | Marks the speed as an assumption |

Centerlines only. The taxiway **zone** is `taxiway_area` in the GeoPackage (`kind`, `zone` = `core`/`tolerance`, `width_m`, `tolerance_m`; zone_type `taxiway`, criticality 2, `taxiway_area_vehicle_speed_kmh` = 20 km/h).

### aprons
| Attribute | Meaning |
|---|---|
| `name` | Apron name from OSM |
| `allowed_assets` | Vehicle types allowed (`;`-separated): `aircraft;handling;sar;service` |
| `assets_source` | Marks `allowed_assets` as an assumption |
| `zone_type` / `criticality` / `speed_limit_kmh` | `apron` / `2` / `apron_vehicle_speed_kmh` (25) |

### stands
| Attribute | Meaning |
|---|---|
| `stand_id` | Stand number from OSM `ref` |
| `aircraft_class` | Aircraft size class the stand takes. **Empty for now** (not in OSM) |
| `zone_type` / `criticality` / `speed_limit_kmh` | `stand` / `2` / `stand_vehicle_speed_kmh` (10) |

### holding_points
| Attribute | Meaning |
|---|---|
| `osm_id` | OpenStreetMap node id |
| `ref` | Holding point name, where OSM has one |
| `holding_type` | `runway` = stop before entering a runway · `intermediate` = taxiway holding point · empty = not tagged in OSM |
| `zone_type` / `criticality` / `speed_limit_kmh` | `restricted` / `3` / `holding_area_vehicle_speed_kmh` (10) |

### service_roads
| Attribute | Meaning |
|---|---|
| `name`, `service` | OSM road name and service type |
| `asset_types` | Which vehicle types may use the road (`;`-separated) |
| `allowed_assets` | Same as `asset_types` (original column name) |
| `max_speed_kmh` / `speed_limit_kmh` | `service_road_max_speed_kmh` (30) |
| `values_source` | Marks the values as assumptions |

### buildings
| Attribute | Meaning |
|---|---|
| `type` | `hangar` or `terminal` |
| `name` | Building name from OSM |
| `height_m` | Height in meters (see below) |
| `height_source` | How `height_m` was obtained |
| `zone_type` / `criticality` / `speed_limit_kmh` | `building` / `1` / `0` |

`height_m`: guide rule is OSM `height`, else `building:levels` × 3.5, else an estimate. OSM has neither tag for any FCO building, so **all heights are estimates**: terminals ≥ 15 000 m² → 20 m, other terminals → 15 m, hangars ≥ 10 000 m² → 25 m, hangars 2 000–10 000 m² → 15 m, smaller → 10 m. Only hangars and terminals matter (they drive the GNSS risk halos); replace with real values when known.

### sensitive_zones
| Attribute | Meaning |
|---|---|
| `kind` | `runway_strip` · `runway_holding_area` · `fuel` |
| `name` | e.g. `Runway strip 16L/34R` |
| `access_level` | `atc_clearance` (strips) · `stop_for_clearance` (holding areas) · `authorised_only` (fuel) |
| `zone_type` | `restricted` |
| `criticality` | `3` strips and holding areas · `2` fuel |
| `speed_limit_kmh` | `near_runway_vehicle_speed_kmh` (30) for strips · `holding_area_vehicle_speed_kmh` (10) · `fuel_zone_vehicle_speed_kmh` (10) |
| `source` | Rule used to build the zone |

How they are built:
- `runway_strip` ×3: ICAO code 4 instrument runway strip around each OurAirports runway, 140 m each side of the centerline and 60 m past each end.
- `runway_holding_area` ×32: 25 m circle around every OSM runway-holding position.
- `fuel` ×2: OSM `amenity=fuel` inside the airport boundary.

### restricted_parking
| Attribute | Meaning |
|---|---|
| `name` | Car park name from OSM, or `Reserved parking` |
| `osm_access` | OSM `access` tag (`private`, `no`, `unknown`) |
| `allowed_assets` | Vehicle types allowed to park (`handling;sar;service`) |
| `max_dwell_min` | Max minutes a vehicle may stay: `parking_max_dwell_min` (60) |
| `zone_type` / `criticality` / `speed_limit_kmh` | `parking` / `1` / `parking_vehicle_speed_kmh` (10) |
| `source` | Rule used to select the area |

Selection: OSM `amenity=parking` inside the airport boundary, ≥ 300 m², with `access=private/no` or a reserved `PR…` name. Public car parks (multi-storey, Kiss&Go, customers) are left out.

### taxiway_area
| Attribute | Meaning |
|---|---|
| `kind` | `taxiway` or `taxilane` |
| `zone` | `core` = the paved surface · `tolerance` = core + GNSS margin (contains the core) |
| `width_m` | Paved width used for the core: `taxiway_width_m` (23) / `taxilane_width_m` (15) |
| `tolerance_m` | Extra margin: `gnss_tolerance_m` (20) |
| `zone_type` / `criticality` / `speed_limit_kmh` | `taxiway` / `2` / `taxiway_area_vehicle_speed_kmh` (20) |

Use: a point inside `core` is on the taxiway; inside `tolerance` but not `core` is GNSS noise, not a violation.

### approach_corridors
| Attribute | Meaning |
|---|---|
| `runway_id`, `runway_end` | Runway and the end the corridor starts from |
| `approach_heading_deg_true` | Heading an arriving aircraft flies inside this corridor |
| `half_angle_deg`, `length_m`, `start_half_width_m` | Corridor shape (`corridor_*` settings) |

Use: an ADS-B track heading toward the airport outside every corridor is an unexpected approach.

### key_points
| Attribute | Meaning |
|---|---|
| `type` | `fire_station` (4) or `holding_point` (65) |
| `name`, `source` | Name and data source |

### runways_centerline
`id`, `width_m`, `length_m`, `heading_deg_true`, `source` – OSM centerlines (the runway polygons come from OurAirports; both agree within 18 m).

### network_nodes / network_edges (folder `network/`)
| Attribute | Meaning |
|---|---|
| `node_id` | Node number |
| `x`, `y` | Node position in **EPSG:32633 meters** (kept for metric calculations, even in the 4326 GeoJSON) |
| `edge_id` | Segment number |
| `from_node`, `to_node` | The two `node_id`s the segment connects |
| `kind` | `taxiway` (663) · `taxilane` (62) · `service_road` (1009) |
| `name` | Taxiway or road name |
| `length_m` | Segment length in meters |
| `max_speed_kmh` | taxiway 46 (25 kt) · taxilane 18.5 (10 kt) · service road 30 |
| `allowed_assets` | taxiway `aircraft;sar` · taxilane `aircraft;handling;sar` · service road `handling;sar;service` |

Use: build a graph (e.g. networkx) from `from_node` / `to_node` with `length_m` as weight. "Is this a valid route?" = is there a path using only edges whose `allowed_assets` contain the vehicle type. About 75% of the network is connected in one piece; some segments are isolated.

## Vehicle type values

Used in `allowed_assets` and `asset_types`: `aircraft`, `handling`, `sar` (search and rescue / fire), `service`.

## Assumptions (map_settings.csv)

All tunable values live in `map_settings.csv` (`;`-separated, also the `settings` table in the GeoPackage). **Every value is an ASSUMPTION** until the organisers give official thresholds.

| Setting | Value | Used for |
|---|---|---|
| `taxiway_width_m` | 23 m | Taxiway area core (ICAO code E) |
| `taxilane_width_m` | 15 m | Taxilane area core |
| `gnss_tolerance_m` | 20 m | Tolerance margin around taxiway areas |
| `corridor_length_m` | 18 000 m | Approach corridor length |
| `corridor_half_angle_deg` | 7.5° | Approach corridor widening |
| `corridor_start_half_width_m` | 150 m | Corridor half-width at the runway end |
| `taxiway_max_speed_kt` | 25 kt | Aircraft taxi speed, taxiways |
| `taxilane_max_speed_kt` | 10 kt | Aircraft taxi speed, taxilanes |
| `service_road_max_speed_kmh` | 30 km/h | Vehicles on service roads |
| `apron_vehicle_speed_kmh` | 25 km/h | Vehicles on aprons |
| `near_runway_vehicle_speed_kmh` | 30 km/h | Vehicles on a runway or in its strip (with ATC clearance) |
| `parking_max_dwell_min` | 60 min | Max stay in restricted parking |
| `taxiway_area_vehicle_speed_kmh` | 20 km/h | Vehicles inside the taxiway area |
| `stand_vehicle_speed_kmh` | 10 km/h | Vehicles at aircraft stands |
| `holding_area_vehicle_speed_kmh` | 10 km/h | Vehicles at runway holding points / holding areas |
| `fuel_zone_vehicle_speed_kmh` | 10 km/h | Vehicles inside fuel station zones |
| `parking_vehicle_speed_kmh` | 10 km/h | Vehicles inside restricted parking |
| `holding_area_radius_m` | 25 m | Circle around each runway holding point |
| `runway_strip_half_width_m` | 140 m | Runway strip, each side of the centerline (ICAO code 4) |
| `runway_strip_end_extension_m` | 60 m | Runway strip, past each runway end (ICAO) |

Every number used in the layers is in this table. Building heights are the only estimates kept in the layer itself (rule under buildings). If you change a setting, the layers must be regenerated to match.

## Checks done

- OurAirports runways vs OSM runways: lengths within 18 m, polygons overlap ~97%.
- Runways, taxiways and aprons line up with the 2023 ADR orthophoto (0.2 m) in QGIS.

## Known gaps

- Runway **16C/34C** is not in `runways`: OurAirports has no end coordinates for it (mostly used as a taxiway). Confirm with the team.
- `sensitive_zones` and `restricted_parking` are rule-based, not official ADR geofences. Replace them if the organisers provide real ones.
- Building heights are estimates (see buildings).
- The road network (`network_edges`) is about 75% connected; some segments are isolated.

## Sources and attribution

- Airport geometry: © OpenStreetMap contributors (ODbL). Overpass exports of 2026-10-10 and 2026-10-11 (raw files kept by the map builder, not in this folder).
- Runway ends and widths: OurAirports (public domain), `runways.csv` downloaded 2026-10-11.
- Basemap: Contains modified Copernicus Sentinel data 2026 (Sentinel-2 L2A, 2026-09-01), files in `imagery/`.
- Orthophoto: ADR / AGEA 2023, 0.2 m, EPSG:7792 (participants kit). Not included here (3 GB, organisers' terms); used only for visual checking.
