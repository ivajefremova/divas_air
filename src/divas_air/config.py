import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW, PROCESSED, REFERENCE = DATA / "raw", DATA / "processed", DATA / "reference"
LAYERS = ROOT / "map" / "layers"

# orthophoto XYZ tiles for the web map (kept off git; point at the hard drive if elsewhere)
TILES = Path(os.getenv("DIVAS_TILES_DIR", ROOT / "map" / "tiles"))

CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:32633"  # UTM 33N, distances in meters

# (lat_min, lon_min, lat_max, lon_max)
AIRPORT_BOX = (41.77, 12.20, 41.86, 12.30)
APPROACH_BOX = (41.53, 11.89, 42.07, 12.61)

WINDOW_S = 30
STRIDE_S = 5
