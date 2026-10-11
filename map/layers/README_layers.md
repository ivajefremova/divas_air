# Map layers (LIRF)

All files EPSG:4326 (lon/lat). Read by `divas_air.geo.MapLayers.load()` unless marked display only.

| File | Geometry | Content |
|---|---|---|
| `runways.geojson` | LineString | Runway **centre lines** from OpenStreetMap, with `ref` (e.g. `"16R/34L"`). Read by `divas_air.geo`: one merged centre line per `ref`, runway ends from it. Do not replace with polygons. |
| `runway_areas.geojson` | Polygon | Runway **outlines** from OurAirports (`scripts/runways_from_ourairports.py`), with `ref` in the same format as the centre lines so the two join, plus `runway`, `length_ft`, `width_m`, `surface`, `closed`, `zone_type`, `criticality`. **Display only** (web map); not read by `divas_air.geo` or `divas_air.synth`. |
| `aprons.geojson` | Polygon | Aprons (OSM). |
| `taxiway_lines.geojson` | LineString | Taxiway centre lines (OSM), `ref`. |
| `service_roads.geojson` | LineString | Airside service roads (OSM). |
| `stands.geojson` | Point | Aircraft stands (OSM), `ref`. |
| `holding_points.geojson` | Point | Runway holding points (OSM). |
| `buildings.geojson` | Polygon | Buildings (OSM). |

Route network for vehicles and taxiing aircraft: `map/fco_routes.graphml` (UTM 33N, edges `layer` = `taxiway` | `service_road`).
