"""ADR geofences as an alternative LIRF layer set: `MapLayers.load(profile="adr")`.

ADR's 340 polygons replace the OSM zones; buildings, the route graph and the
runway ends stay OSM because ADR provides none. The boundary becomes the
`airside_boundary` polygon (it matches ADR's `inside_aerodrome`). See
docs/ADR_DATASET.md section 4 for the mapping and its assumptions.
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from divas_air import config, params

GEOFENCES = "geofences/fco_geofences.geojson.gz"

# ADR zone_class -> zone type used by zone_access and the feature layer.
# `runway_strip` is a ring around `runway_critical` (300 m strip minus the 150 m
# critical area), not the runway itself: it gets its own type so a runway
# incursion means ADR's critical area, as in `runway_critical_ref`.
ZONE_TYPE = {
    "runway_critical": "runway",
    "runway_strip": "runway_strip",
    "taxi_corridor": "taxiway",
    "holding_position": "holding_point",
    "apron": "apron",
    "aircraft_stand": "stand",
    "service_road_corridor": "service_road",
}
BOUNDARY_CLASS = "airside_boundary"
ALL_GROUPS = ("aircraft", "handling", "sar", "ops_authorized")
ZONE_COLUMNS = [
    "zone_id",
    "zone_name",
    "zone_type",
    "criticality",
    "speed_limit_mps",
    "adr_zone_class",
    "sensitivity",
    "allowed_groups",
    "clearance_required",
    "geometry",
]


def read_geofences() -> dict:
    from divas_air.ingest.adr import read_member

    return json.loads(gzip.decompress(read_member(GEOFENCES)))


def _groups(allowed: str) -> str:
    """ADR `allowed_assets` -> sorted comma list of groups; `all` expands."""
    g = {x.strip() for x in str(allowed).split(",") if x.strip()}
    if "all" in g:
        g = set(ALL_GROUPS)
    return ",".join(sorted(g))


def zones_from_geofences(fc: dict) -> tuple[gpd.GeoDataFrame, shapely.Geometry]:
    """(zones in CRS_METRIC with the default zone columns plus ADR's, boundary polygon)."""
    g = gpd.GeoDataFrame.from_features(fc["features"], crs=config.CRS_WGS84)
    g = g.to_crs(config.CRS_METRIC)
    # one ADR strip polygon self-intersects; make_valid keeps its area
    g["geometry"] = shapely.make_valid(g.geometry.to_numpy())

    is_b = g["zone_class"] == BOUNDARY_CLASS
    if is_b.sum() != 1:
        raise ValueError(
            f"expected one {BOUNDARY_CLASS} polygon, got {int(is_b.sum())}"
        )
    boundary = g.loc[is_b, "geometry"].iloc[0]
    z = g[~is_b].reset_index(drop=True)

    unknown = set(z["zone_class"]) - set(ZONE_TYPE)
    if unknown:
        raise ValueError(f"unmapped ADR zone classes: {sorted(unknown)}")
    zone_type = z["zone_class"].map(ZONE_TYPE)
    sens = z["sensitivity"].astype("string").str.lower()
    zones = gpd.GeoDataFrame(
        {
            "zone_id": z["gf_id"].astype("string").to_numpy(),
            "zone_name": z["name"].astype("string").to_numpy(),
            "zone_type": zone_type.to_numpy(),
            "criticality": sens.map(params.CRITICALITY).astype("float64").to_numpy(),
            "speed_limit_mps": (
                pd.to_numeric(z["speed_limit_kmh"], errors="coerce") / 3.6
            ).to_numpy(dtype="float64"),
            "adr_zone_class": z["zone_class"].astype("string").to_numpy(),
            "sensitivity": sens.to_numpy(),
            "allowed_groups": z["allowed_assets"].map(_groups).to_numpy(),
            "clearance_required": z.get(
                "clearance_required", pd.Series(pd.NA, index=z.index)
            )
            .astype("boolean")
            .to_numpy(),
        },
        geometry=z.geometry.to_numpy(),
        crs=config.CRS_METRIC,
    )[ZONE_COLUMNS]
    if zones["criticality"].isna().any():
        raise ValueError("ADR sensitivity outside params.CRITICALITY")
    return zones, boundary


def category_groups() -> dict[str, str]:
    """Envelope category -> ADR group. Aircraft categories are `aircraft`; vehicle
    categories take the group of the ADR classes mapped onto them (must be unique)."""
    from divas_air.ingest.adr import class_map

    env = pd.read_csv(config.REFERENCE / "envelopes.csv")
    out = {c: "aircraft" for c in env.loc[env["domain"] == "aircraft", "category"]}
    cm = class_map().reset_index()
    cm = cm[(cm["asset_class"] != "") & (cm["domain"] == "vehicle")]
    for cat, grp in cm.groupby("asset_class")["adr_group"]:
        groups = set(grp) - {""}
        if len(groups) != 1:
            raise ValueError(f"category {cat} maps to ADR groups {sorted(groups)}")
        out[cat] = groups.pop()
    # unmatched ADR classes keep their own name as asset_class (ingest.adr.map_classes)
    nomatch = class_map().reset_index()
    nomatch = nomatch[(nomatch["asset_class"] == "") & (nomatch["adr_group"] != "")]
    out.update(dict(zip(nomatch["adr_class"], nomatch["adr_group"], strict=True)))
    return out


def zone_access(zones: gpd.GeoDataFrame) -> pd.DataFrame:
    """ADR access in the shape of data/reference/zone_access.csv.

    allowed = the class's ADR group is allowed in every ADR polygon of that zone
    type (the most restrictive polygon wins; today each type has one rule).
    max_dwell_s comes from the default table: ADR gives none.
    """
    default = pd.read_csv(config.REFERENCE / "zone_access.csv")
    dwell = default.groupby("zone_type")["max_dwell_s"].first()
    groups = category_groups()
    rows = []
    for ztype, allowed in zones.groupby("zone_type")["allowed_groups"]:
        ok = set.intersection(*(set(a.split(",")) for a in allowed))
        for cls, grp in groups.items():
            rows.append((ztype, cls, grp in ok, dwell.get(ztype, np.nan)))
    return pd.DataFrame(
        rows, columns=["zone_type", "asset_class", "allowed", "max_dwell_s"]
    )


@lru_cache(maxsize=1)
def load_adr():
    from divas_air.geo import MapLayers

    base = MapLayers.load()
    zones, boundary = zones_from_geofences(read_geofences())
    layers = MapLayers(
        zones=zones,
        buildings=base.buildings,
        boundary=boundary,
        runways=base.runways,
        routes=base.routes,
        runway_lines=base.runway_lines,
    )
    layers.profile = "adr"
    layers.zone_access = zone_access(zones)
    return layers
