# LIRF map pack – Track Trust for Airport Mobility (ADR)

Geospatial model of **Rome Fiumicino airport (LIRF / FCO)** for the Safe Mobility Hack 2026, ADR challenge.
The AI side compares vehicle and aircraft tracks against it: *is this point on a taxiway? inside a restricted zone? moving at a plausible speed for this zone? on a valid route?*

Map builder: Ivana · Version: 2026-10-11

## Folder

```
LIRF_map_handoff/
├── README.md              ← this file
├── layers/                ← one GeoJSON per layer, EPSG:4326 (14 files)
│   └── README_layers.md   ← every layer and attribute explained
├── network/               ← routable network: network_nodes.geojson, network_edges.geojson
├── rules.csv              ← expected behaviour per zone and vehicle type
├── map_settings.csv       ← every number used (speeds, widths, buffers); all ASSUMPTIONS
├── LIRF_map.gpkg          ← all layers in one file, EPSG:32633 (meters) + settings table
└── imagery/               ← Sentinel-2 image of the airport (2026-09-01)
```

## The 3 rules to remember

1. **GeoJSON = longitude, latitude** (EPSG:4326). Many libraries expect lat, lon; don't swap them by mistake.
2. **Never compute distances or speeds in lon/lat.** Reproject to **EPSG:32633** (UTM 33N, meters) first, or read `LIRF_map.gpkg`, which is already in meters.
3. **All thresholds are assumptions**, not official ADR values. Read them from `map_settings.csv` / `rules.csv`; don't hard-code them, so they can be changed in one place.

## What to use for which check

| Question | Use |
|---|---|
| Is the point on a runway? | `layers/runways.geojson` |
| On a taxiway, or just GPS noise next to it? | `layers/taxiway_area.geojson`: `zone=core` = on it; `zone=tolerance` only = within GNSS margin |
| Inside a restricted zone? | `layers/sensitive_zones.geojson` (runway strips, runway holding areas, fuel) |
| Parked where it shouldn't, or too long? | `layers/restricted_parking.geojson` + `max_dwell_min` |
| Speed plausible here for this vehicle? | zone's `speed_limit_kmh`, or `rules.csv` (`zone_kind` + `asset_type`) |
| Is this vehicle type allowed here? | `rules.csv` → `allowed` |
| Valid route? Distance to nearest allowed path? | `network/` → graph from `from_node`/`to_node`, weight `length_m`, filter by `allowed_assets` |
| GNSS multipath / shadow risk near tall buildings? | `layers/buildings.geojson` → `height_m` (hangars, terminals) |
| Aircraft approaching from an unexpected direction? | `layers/approach_corridors.geojson` |
| Track inside a building footprint? | `layers/buildings.geojson`: likely a GNSS error |

Vehicle types used everywhere: `aircraft`, `handling`, `sar` (search and rescue / fire), `service`.

## rules.csv

`;`-separated. One row per zone kind × vehicle type.

| Column | Meaning |
|---|---|
| `zone_type` | Common zone type (`runway`, `taxiway`, `apron`, `stand`, `parking`, `restricted`, `building`, `other`) |
| `zone_kind` | Finer kind, matches the layer (e.g. `runway_strip`, `taxilane`, `fuel`, `service_road`) |
| `layer` | GeoJSON file in `layers/` that holds the zone |
| `asset_type` | `aircraft`, `handling`, `sar`, `service` |
| `allowed` | `yes` / `no` |
| `max_speed_kmh` | Max speed; empty = not checked |
| `max_dwell_min` | Max time to stay; empty = no limit |
| `requires_clearance` | `yes` = only allowed with ATC clearance (cannot be verified from the track; flag for review) |
| `direction` | `any`, `follow_one_way` (see `one_way` on taxiway lines), `stop_before_runway`, `runway_in_use` |
| `setting` | Name of the `map_settings.csv` row the value comes from |
| `source` | `assumption` for every row until the organisers give official values |

Where zones overlap (e.g. a runway strip over a taxiway), apply the **strictest** rule: lowest speed, `no` beats `yes`.

## map_settings.csv

`;`-separated: `name;value;unit;meaning`. 20 settings (widths, GNSS tolerance, corridor shape, speed limits, dwell time, zone sizes). Also stored as the `settings` table in `LIRF_map.gpkg`.
If a value changes, the map builder regenerates the layers so they stay consistent.

## Known limits

- Runway **16C/34C** is not included (no end coordinates in OurAirports; mostly used as a taxiway).
- `sensitive_zones` and `restricted_parking` are built from rules + OSM, **not official ADR geofences**. Replaced if the organisers provide them.
- Building heights are estimates (OSM has no heights for FCO).
- Road network is ~75% connected; some segments are isolated, so route checks there can fail.
- `aircraft_class` on stands is empty.
- Ground vehicles rarely broadcast ADS-B, so vehicle tracks will mostly be synthetic.

## Checks done

- All 15 layers: valid geometries, no CRS mismatch.
- Runways from OurAirports vs OSM: lengths within 18 m, ~97% overlap.
- Layers line up with the 2023 ADR orthophoto (0.2 m): runway and taxiway lines within ~1–3 m of the painted lines.

## Sources and attribution (show on the demo)

- © OpenStreetMap contributors (ODbL): airport geometry, parking, fuel.
- Contains modified Copernicus Sentinel data 2026 (Sentinel-2 L2A, 2026-09-01), processed with Copernicus Browser.
- OurAirports (public domain): runway ends and widths.
- ADR / AGEA 2023 orthophoto: used for visual checking only, not included.

## imagery/

| File | Content |
|---|---|
| `LIRF_S2_20260901.tif` | Sentinel-2 L2A, 10 m, EPSG:32633, 4 bands UInt16: 1 = B04 red, 2 = B03 green, 3 = B02 blue, 4 = B08 near-infrared |
| `LIRF_S2_20260901_truecolor.tif` | Same area, 3-band true-colour image for display / web demo |
