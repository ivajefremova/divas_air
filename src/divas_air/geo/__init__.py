"""Map-layer loader shared by the generator and the feature layer (specs/02_generator.md).

`MapLayers.load()` normalizes the OSM layers in `map/layers/` and the route graph
`map/fco_routes.graphml` (docs/DATA_INVENTORY.md section 3) into the names the
specs use. Everything metric is in `config.CRS_METRIC`.
"""

from __future__ import annotations

from functools import cached_property, lru_cache

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely
from pyproj import Geod, Transformer
from shapely.geometry import box

from divas_air import config, params

ROUTES_GRAPHML = config.ROOT / "map" / "fco_routes.graphml"
ZONE_COLUMNS = [
    "zone_id",
    "zone_name",
    "zone_type",
    "criticality",
    "speed_limit_mps",
    "geometry",
]
ROUTE_LAYER = {
    "aircraft": "taxiway",
    "vehicle": "service_road",
}  # graph edge `layer` per domain

_GEOD = Geod(ellps="WGS84")
_TO_METRIC = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)
_TO_WGS84 = Transformer.from_crs(config.CRS_METRIC, config.CRS_WGS84, always_xy=True)


def to_metric(lon, lat) -> tuple[np.ndarray, np.ndarray]:
    x, y = _TO_METRIC.transform(
        np.asarray(lon, dtype="float64"), np.asarray(lat, dtype="float64")
    )
    return np.asarray(x), np.asarray(y)


def to_wgs84(x, y) -> tuple[np.ndarray, np.ndarray]:
    """Returns (lon, lat)."""
    lon, lat = _TO_WGS84.transform(
        np.asarray(x, dtype="float64"), np.asarray(y, dtype="float64")
    )
    return np.asarray(lon), np.asarray(lat)


def _read(name: str) -> gpd.GeoDataFrame:
    return gpd.read_file(config.LAYERS / f"{name}.geojson").to_crs(config.CRS_METRIC)


def _criticality(zone_type: str) -> float:
    return params.CRITICALITY[params.ZONE_CRITICALITY[zone_type]]


def _zones_of(
    gdf: gpd.GeoDataFrame, zone_type: str, geometry, names, speed=None
) -> gpd.GeoDataFrame:
    n = len(gdf)
    return gpd.GeoDataFrame(
        {
            "zone_id": [f"{zone_type}_{i:04d}" for i in range(n)],
            "zone_name": pd.Series(names, dtype="string").to_numpy(),
            "zone_type": zone_type,
            "criticality": _criticality(zone_type),
            "speed_limit_mps": np.full(n, np.nan)
            if speed is None
            else np.asarray(speed, dtype="float64"),
        },
        geometry=gpd.GeoSeries(geometry, crs=config.CRS_METRIC).to_numpy(),
        crs=config.CRS_METRIC,
    )


def _runway_lines(rw: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """One merged centerline per runway designator. Features without a ref join the nearest named runway."""
    rw = rw.reset_index(drop=True)
    named = rw[rw["ref"].notna()]
    refs = rw["ref"].copy()
    for i in rw.index[rw["ref"].isna()]:
        refs[i] = named.loc[named.distance(rw.geometry[i]).idxmin(), "ref"]
    rw = rw.assign(ref=refs)
    return rw.dissolve(by="ref", as_index=False)[["ref", "geometry"]]


def _runway_ends(lines: gpd.GeoDataFrame) -> pd.DataFrame:
    """Threshold of each runway end = the farthest pair of vertices of the merged centerline."""
    rows = []
    for ref, geom in zip(lines["ref"], lines.geometry, strict=True):
        xy = shapely.get_coordinates(geom)
        d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
        i, j = np.unravel_index(np.argmax(d), d.shape)
        lon, lat = to_wgs84(xy[[i, j], 0], xy[[i, j], 1])
        az_ij, az_ji, _ = _GEOD.inv(lon[0], lat[0], lon[1], lat[1])
        ends = ref.split("/")
        # designator number ~ bearing / 10: assign the end whose number matches the take-off bearing
        b0 = float(az_ij % 360)
        first = min(ends, key=lambda e: abs(((int(e[:2]) * 10 - b0 + 180) % 360) - 180))
        second = next((e for e in ends if e != first), first)
        rows.append((ref, first, lat[0], lon[0], b0))
        rows.append((ref, second, lat[1], lon[1], float(az_ji % 360)))
    out = pd.DataFrame(
        rows, columns=["runway", "end", "threshold_lat", "threshold_lon", "bearing_deg"]
    )
    out["elevation_m"] = params.AIRPORT_ELEVATION_M
    return out[
        [
            "runway",
            "end",
            "threshold_lat",
            "threshold_lon",
            "elevation_m",
            "bearing_deg",
        ]
    ]


def _building_heights(b: gpd.GeoDataFrame) -> np.ndarray:
    def num(col):
        if col not in b.columns:
            return pd.Series(np.nan, index=b.index)
        return pd.to_numeric(
            b[col].astype("string").str.extract(r"([\d.]+)")[0], errors="coerce"
        )

    h = num("height").fillna(num("building:height"))
    h = h.fillna(num("building:levels") * params.BUILDING_LEVEL_M)
    tall = b.get("aeroway", pd.Series(None, index=b.index)).isin(["hangar", "terminal"])
    h = h.fillna(
        pd.Series(
            np.where(
                tall, params.BUILDING_TALL_DEFAULT_M, params.BUILDING_DEFAULT_HEIGHT_M
            ),
            index=b.index,
        )
    )
    return h.to_numpy(dtype="float64")


def _route_graphs() -> dict[str, nx.MultiGraph]:
    g = nx.read_graphml(ROUTES_GRAPHML)
    for _, d in g.nodes(data=True):
        d["x"], d["y"] = float(d["x_utm"]), float(d["y_utm"])
    for _, _, d in g.edges(data=True):
        d["length_m"] = float(d["length_m"])
        d["geometry"] = shapely.from_wkt(d["geometry"])
    out = {}
    for domain, layer in ROUTE_LAYER.items():
        edges = [
            (u, v, k)
            for u, v, k, d in g.edges(keys=True, data=True)
            if d.get("layer") == layer
        ]
        out[domain] = nx.MultiGraph(g.edge_subgraph(edges))
    return out


class MapLayers:
    """Normalized LIRF layers. Build with `MapLayers.load()`."""

    def __init__(self, zones, buildings, boundary, runways, routes, runway_lines=None):
        self.zones = zones
        self.buildings = buildings
        self.boundary = boundary
        self.runways = runways
        self.routes = routes
        self.runway_lines = runway_lines

    @classmethod
    def load(cls, airport: str = "LIRF") -> MapLayers:
        if airport != "LIRF":
            raise ValueError(f"no layers for {airport}")
        return _load_lirf()

    # --- coordinates -------------------------------------------------------
    @staticmethod
    def to_metric(lon, lat) -> tuple[np.ndarray, np.ndarray]:
        return to_metric(lon, lat)

    @staticmethod
    def to_wgs84(x, y) -> tuple[np.ndarray, np.ndarray]:
        return to_wgs84(x, y)

    # --- routes ------------------------------------------------------------
    @cached_property
    def _route_trees(self) -> dict[str, shapely.STRtree]:
        return {
            dom: shapely.STRtree([d["geometry"] for _, _, d in g.edges(data=True)])
            for dom, g in self.routes.items()
        }

    def route_distance_m(self, x, y, domain: str) -> np.ndarray:
        """Distance in meters from metric points to the nearest authorized route edge of `domain`."""
        pts = shapely.points(
            np.asarray(x, dtype="float64"), np.asarray(y, dtype="float64")
        )
        tree = self._route_trees[domain]
        idx, dist = tree.query_nearest(pts, return_distance=True, all_matches=False)
        out = np.full(len(pts), np.nan)
        out[idx[0]] = dist
        return out

    # --- obstruction -------------------------------------------------------
    @cached_property
    def _obstruction_grid(self):
        """Max building elevation angle (deg) on a regular metric grid over the route network."""
        nodes = np.array(
            [
                (d["x"], d["y"])
                for g in self.routes.values()
                for _, d in g.nodes(data=True)
            ]
        )
        pad = params.BUILDING_SEARCH_M + 500.0
        x0, y0 = nodes.min(axis=0) - pad
        x1, y1 = nodes.max(axis=0) + pad
        step = params.OBSTRUCTION_GRID_M
        gx = np.arange(x0, x1, step)
        gy = np.arange(y0, y1, step)
        xx, yy = np.meshgrid(gx, gy)
        elev = max_building_elevation_deg(self.buildings, xx.ravel(), yy.ravel())
        return x0, y0, step, elev.reshape(xx.shape)

    def building_elevation_deg(self, x, y) -> np.ndarray:
        """Highest building elevation angle atan(height / distance) seen from metric points, in degrees."""
        x0, y0, step, grid = self._obstruction_grid
        i = np.clip(
            np.round((np.asarray(y) - y0) / step).astype(int), 0, grid.shape[0] - 1
        )
        j = np.clip(
            np.round((np.asarray(x) - x0) / step).astype(int), 0, grid.shape[1] - 1
        )
        return grid[i, j]


def max_building_elevation_deg(buildings: gpd.GeoDataFrame, x, y) -> np.ndarray:
    """Exact max over buildings within BUILDING_SEARCH_M of atan(height / distance), degrees."""
    pts = shapely.points(np.asarray(x, dtype="float64"), np.asarray(y, dtype="float64"))
    geoms = buildings.geometry.to_numpy()
    tree = shapely.STRtree(geoms)
    pi, bi = tree.query(pts, predicate="dwithin", distance=params.BUILDING_SEARCH_M)
    out = np.zeros(len(pts))
    if len(pi) == 0:
        return out
    d = np.maximum(shapely.distance(pts[pi], geoms[bi]), 1.0)
    ang = np.degrees(np.arctan(buildings["height_m"].to_numpy()[bi] / d))
    np.maximum.at(out, pi, ang)
    return out


@lru_cache(maxsize=1)
def _load_lirf() -> MapLayers:
    rw_lines = _runway_lines(_read("runways"))
    tw = _read("taxiway_lines")
    hp = _read("holding_points")
    ap = _read("aprons")
    st = _read("stands")
    sr = _read("service_roads")
    speed = pd.to_numeric(sr["maxspeed"], errors="coerce") / 3.6  # km/h -> m/s

    zones = pd.concat(
        [
            _zones_of(
                rw_lines,
                "runway",
                rw_lines.buffer(params.RUNWAY_HALF_WIDTH_M, cap_style="flat"),
                rw_lines["ref"],
            ),
            _zones_of(
                tw, "taxiway", tw.buffer(params.TAXIWAY_HALF_WIDTH_M), tw.get("ref")
            ),
            _zones_of(
                hp,
                "holding_point",
                hp.buffer(params.HOLDING_POINT_RADIUS_M),
                hp.get("ref"),
            ),
            _zones_of(ap, "apron", ap.geometry, ap.get("ref")),
            _zones_of(st, "stand", st.buffer(params.STAND_RADIUS_M), st.get("ref")),
            _zones_of(
                sr,
                "service_road",
                sr.buffer(params.SERVICE_ROAD_HALF_WIDTH_M),
                sr.get("name"),
                speed,
            ),
        ],
        ignore_index=True,
    )
    zones = gpd.GeoDataFrame(
        zones[ZONE_COLUMNS], geometry="geometry", crs=config.CRS_METRIC
    )

    b = _read("buildings")
    buildings = gpd.GeoDataFrame(
        {
            "height_m": _building_heights(b),
            "building": b["building"].astype("string").to_numpy(),
        },
        geometry=b.geometry.to_numpy(),
        crs=config.CRS_METRIC,
    )

    lat0, lon0, lat1, lon1 = config.AIRPORT_BOX
    bx, by = to_metric([lon0, lon1], [lat0, lat1])
    boundary = box(bx[0], by[0], bx[1], by[1])

    return MapLayers(
        zones=zones,
        buildings=buildings,
        boundary=boundary,
        runways=_runway_ends(rw_lines),
        routes=_route_graphs(),
        runway_lines=rw_lines,
    )
