# Ivana's map pack (reference only)

Uploaded by Ivana on 2026-10-10 ("Add files via upload"). Kept on this branch only,
so the main pipeline (`map/layers/`, `src/divas_air/geo`, `src/divas_air/synth`) never reads it.

Contents: airport boundary, approach corridors, taxiway areas with GNSS tolerance band,
key points (holding points, fire/SAR stations), route network (edges, nodes, sqlite),
runways (3 polygons with `id`), aprons, stands, buildings, service roads, taxiways, and the
GeoPackages they came from. Used by `demo_map.html`.

Possible later use, display only, in the web map: boundary, GNSS tolerance band, approach corridors, stations.
