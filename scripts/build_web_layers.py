"""Slim map layers for the web map: app/web/data/*.geojson.

Keeps only the properties the map draws, rounds coordinates to ~10 cm, clips buildings to the
airport box, and turns map/fco_routes.graphml (UTM 33N) into a lon/lat route network.

    python scripts/build_web_layers.py
"""

import json
import sys
from pathlib import Path

import networkx as nx
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from divas_air import config as C  # noqa: E402

OUT = C.ROOT / "app" / "web" / "data"
KEEP = {  # layer -> properties kept
    "runways": ["runway", "criticality"],
    "aprons": ["ref", "name"],
    "taxiway_lines": ["ref"],
    "service_roads": ["name"],
    "stands": ["ref"],
    "holding_points": ["ref"],
    "buildings": ["name", "aeroway", "building"],
}


def rnd(c):
    return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 6), round(c[1], 6)]


def in_box(geom) -> bool:
    lat0, lon0, lat1, lon1 = C.AIRPORT_BOX
    c = geom["coordinates"]
    while isinstance(c[0], (list, tuple)):
        c = c[0]
    return lon0 <= c[0] <= lon1 and lat0 <= c[1] <= lat1


def slim(name: str) -> dict:
    src = json.loads((C.LAYERS / f"{name}.geojson").read_text())
    feats = []
    for f in src["features"]:
        g = f.get("geometry")
        if not g or (name == "buildings" and not in_box(g)):
            continue
        props = {k: f["properties"].get(k) for k in KEEP[name] if f["properties"].get(k) is not None}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}})
    return {"type": "FeatureCollection", "features": feats}


def routes() -> dict:
    """Route network edges as lines, kind = taxiway | service."""
    utm = Transformer.from_crs(C.CRS_METRIC, C.CRS_WGS84, always_xy=True)
    G = nx.read_graphml(C.ROOT / "map" / "fco_routes.graphml")
    feats = []
    for _, _, d in G.edges(data=True):
        xy = [tuple(map(float, p.split())) for p in d["geometry"].split("(", 1)[1].rstrip(")").split(",")]
        feats.append({"type": "Feature",
                      "properties": {"kind": d.get("layer"), "ref": d.get("ref") or d.get("name")},
                      "geometry": {"type": "LineString", "coordinates": rnd([utm.transform(x, y) for x, y in xy])}})
    return {"type": "FeatureCollection", "features": feats}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name in KEEP:
        (OUT / f"{name}.geojson").write_text(json.dumps(slim(name), separators=(",", ":")))
    (OUT / "routes.geojson").write_text(json.dumps(routes(), separators=(",", ":")))
    for p in sorted(OUT.glob("*.geojson")):
        print(f"{p.name:24} {p.stat().st_size // 1024:6} KB")
