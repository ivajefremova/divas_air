"""Step 9: build exact runway polygons for one airport from OurAirports runways.csv.

Usage:
    python runways_from_ourairports.py runways.csv map/layers/runways.geojson [ICAO]

ICAO defaults to LIRF (Rome Fiumicino).
Each runway becomes a rectangle: centerline from the two end points,
widened by the runway width (feet -> meters). The math is done in UTM 33N
(EPSG:32633, meters) and the result is saved in WGS84 (EPSG:4326).
"""
import sys

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

FT_TO_M = 0.3048
DEFAULT_WIDTH_FT = 150  # used only if a runway has no width in the CSV

csv_path = sys.argv[1]
out_path = sys.argv[2]
icao = sys.argv[3] if len(sys.argv) > 3 else "LIRF"

df = pd.read_csv(csv_path)
df = df[df["airport_ident"] == icao].copy()
if df.empty:
    sys.exit(f"No rows with airport_ident == {icao} in {csv_path}")

coord_cols = ["le_latitude_deg", "le_longitude_deg", "he_latitude_deg", "he_longitude_deg"]
missing = df[coord_cols].isna().any(axis=1)
missing_df = df[missing]
if missing.any():
    print("No end coordinates in OurAirports for:", ", ".join(
        f"{a}/{b}" for a, b in zip(missing_df["le_ident"], missing_df["he_ident"])))
    df = df[~missing]

rows = []
for r in df.itertuples():
    width_ft = r.width_ft if pd.notna(r.width_ft) else DEFAULT_WIDTH_FT
    if pd.isna(r.width_ft):
        print(f"Warning: runway {r.le_ident}/{r.he_ident} has no width, using {DEFAULT_WIDTH_FT} ft")
    center = LineString([(r.le_longitude_deg, r.le_latitude_deg),
                         (r.he_longitude_deg, r.he_latitude_deg)])
    rows.append({
        "runway": f"{r.le_ident}/{r.he_ident}",
        "length_ft": r.length_ft,
        "width_m": round(width_ft * FT_TO_M, 1),
        "surface": r.surface,
        "closed": int(r.closed) if pd.notna(r.closed) else 0,
        "zone_type": "runway",
        "criticality": 3,
        "geometry": center,
    })

g = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326).to_crs(32633)
# flat end caps so the polygon ends exactly at the runway thresholds
g["geometry"] = [geom.buffer(w / 2, cap_style="flat") for geom, w in zip(g.geometry, g["width_m"])]
g = g.to_crs(4326)

# Fallback: runways OurAirports has no end coordinates for are taken from the
# OpenStreetMap runway file (optional 4th argument), matched on its "ref" tag.
if len(sys.argv) > 4 and len(missing_df):
    osm = gpd.read_file(sys.argv[4]).to_crs(4326)
    if "ref" not in osm.columns:
        sys.exit(f"{sys.argv[4]} has no 'ref' column")
    extra = []
    for r in missing_df.itertuples():
        idents = {str(r.le_ident), str(r.he_ident)}
        hit = osm[osm["ref"].fillna("").apply(lambda s: bool(idents & set(str(s).replace(";", "/").split("/"))))]
        if hit.empty:
            print(f"Not found in OSM file either: {r.le_ident}/{r.he_ident}")
            continue
        width_ft = r.width_ft if pd.notna(r.width_ft) else 200
        width_m = round(width_ft * FT_TO_M, 1)
        geom = hit.to_crs(32633).geometry.union_all()
        if geom.geom_type in ("LineString", "MultiLineString"):
            geom = geom.buffer(width_m / 2, cap_style="flat")
        extra.append({"runway": f"{r.le_ident}/{r.he_ident}", "length_ft": r.length_ft,
                      "width_m": width_m, "surface": r.surface,
                      "closed": int(r.closed) if pd.notna(r.closed) else 0,
                      "zone_type": "runway", "criticality": 3, "geometry": geom})
        print(f"Added {r.le_ident}/{r.he_ident} from OSM (width {width_m} m, check it in QGIS)")
    if extra:
        g = pd.concat([g, gpd.GeoDataFrame(extra, geometry="geometry", crs=32633).to_crs(4326)],
                      ignore_index=True)

g.to_file(out_path, driver="GeoJSON")
print(f"Saved {len(g)} runway polygons to {out_path}")
print(g[["runway", "width_m", "length_ft"]].to_string(index=False))
