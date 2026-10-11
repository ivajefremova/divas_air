"""ADR dataset: asset_tracks -> adr_mock points, and the ADR geofence layer set.

In-code fixtures only; nothing here reads data/raw/adr.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box, mapping

from divas_air import config, schema
from divas_air.geo import adr as gadr
from divas_air.ingest import adr
from tests.helpers import LAT0, LON0, T0, offset


def _raw() -> pd.DataFrame:
    """Two assets interleaved by time, as in ADR's file; one implausible sample each."""
    n = 6
    rows = []
    for k in range(n):
        for aid, cls in (("ACF-0001", "aircraft_taxi"), ("FLT-0002", "fork_lift")):
            rows.append(
                {
                    "asset_id": aid,
                    "asset_class": cls,
                    "timestamp_unix": T0 + k + 0.25,
                    "lat": LAT0 + 1e-5 * k,
                    "lon": LON0,
                    "speed_kmh": 18.0,
                    "heading_deg": 360.0 if k == 1 else 90.0,
                    "alt_m": 2.0,
                    "inside_aerodrome": True,
                    "runway_critical_ref": "07/25" if k == 2 else None,
                }
            )
    df = pd.DataFrame(rows)
    df.loc[3, "speed_kmh"] = 2181.73  # implausible: must survive
    df.loc[4, "alt_m"] = 896.23  # altitude spike: must survive
    return df


def test_points_pass_schema_and_keep_every_sample():
    raw = _raw()
    pts, side, counts = adr.from_asset_tracks(raw)
    schema.validate(pts)
    assert len(pts) == len(raw) == len(side)
    assert counts["missing_t_lat_lon"] == 0
    assert set(pts["track_id"]) == {"adr_mock:ACF-0001:0", "adr_mock:FLT-0002:0"}
    assert pts["gs_mps"].max() == pytest.approx(2181.73 / 3.6)
    assert pts["alt_geom_m"].max() == pytest.approx(896.23)
    assert pts["alt_baro_m"].isna().all() and pts["track_deg"].isna().all()


def test_units_angles_and_arrival_order():
    pts, _, counts = adr.from_asset_tracks(_raw())
    assert pts["gs_mps"].iloc[0] == pytest.approx(5.0)  # 18 km/h
    assert pts["heading_deg"].between(0, 360, inclusive="left").all()
    assert counts["heading_360_wrapped"] == 2
    for _, g in pts.groupby("track_id"):
        assert g["seq"].tolist() == list(range(len(g)))
        assert g["t"].is_monotonic_increasing  # file order == time order here


def test_class_mapping_and_domains():
    pts, _, counts = adr.from_asset_tracks(_raw())
    by = pts.groupby("asset_id").first()
    assert by.loc["ACF-0001", "domain"] == "aircraft"
    assert by.loc["ACF-0001", "asset_class"] == "other"
    # a fork lift takes the nearest envelope (approximate match)
    assert by.loc["FLT-0002", "domain"] == "vehicle"
    assert by.loc["FLT-0002", "asset_class"] == "baggage_tractor"
    assert (pts["typecode_raw"] == pts["typecode"]).all()
    assert counts["class_no_envelope"] == 0


def test_class_without_envelope_keeps_its_name():
    raw = _raw()
    raw.loc[raw["asset_id"] == "FLT-0002", "asset_class"] = "cleaning_van"
    pts, _, counts = adr.from_asset_tracks(raw)
    assert (
        pts.loc[pts["asset_id"] == "FLT-0002", "asset_class"] == "cleaning_van"
    ).all()
    assert counts["class_no_envelope"] == 6


def test_unknown_class_is_kept_and_counted():
    raw = _raw()
    raw.loc[raw["asset_id"] == "FLT-0002", "asset_class"] = "hovercraft"
    pts, _, counts = adr.from_asset_tracks(raw)
    assert counts["class_not_in_map"] == 6
    assert (pts.loc[pts["asset_id"] == "FLT-0002", "asset_class"] == "hovercraft").all()


def test_side_table_joins_back_to_adr_rows():
    raw = _raw()
    pts, side, _ = adr.from_asset_tracks(raw)
    assert not side.duplicated(["track_id", "seq"]).any()
    j = side.merge(pts[["track_id", "seq", "t"]], on=["track_id", "seq"])
    assert (j["t"] == j["timestamp_unix"]).all()
    back = raw.iloc[side["adr_row"]]
    assert (back["asset_id"].to_numpy() == side["asset_id"].to_numpy()).all()
    assert (side["runway_critical_ref"] == "07/25").sum() == 2


def test_class_map_reference_is_complete():
    cm = adr.class_map().reset_index()
    data = cm[cm["seen_in"].str.contains("data")]
    assert len(data) == 27
    assert set(cm["match"]) <= {"exact", "approx", "none"}
    matched = cm[cm["match"] != "none"]
    assert set(matched["asset_class"]) <= set(schema.ASSET_CLASSES)
    assert (cm.loc[cm["match"] == "none", "asset_class"] == "").all()
    assert (cm["reason"].str.len() > 0).all()
    assert set(cm["adr_group"]) <= {"", *gadr.ALL_GROUPS}


# --- geofences ---------------------------------------------------------------


def _poly(north: float, east: float, half: float = 30.0):
    lat, lon = offset(LAT0, LON0, north=north, east=east)
    dlat, dlon = half / 111_000, half / 83_000
    return mapping(box(lon - dlon, lat - dlat, lon + dlon, lat + dlat))


def _fc() -> dict:
    def f(gid, zc, sens, speed, allowed, geom):
        return {
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "gf_id": gid,
                "name": gid,
                "zone_class": zc,
                "sensitivity": sens,
                "speed_limit_kmh": speed,
                "allowed_assets": allowed,
                "clearance_required": sens == "high",
            },
        }

    return {
        "type": "FeatureCollection",
        "features": [
            f("AD", "airside_boundary", "medium", None, "all", _poly(0, 0, 2000)),
            f(
                "RWY-CRIT",
                "runway_critical",
                "high",
                None,
                "aircraft,sar,ops_authorized",
                _poly(0, 0),
            ),
            f(
                "RWY-STRIP",
                "runway_strip",
                "high",
                30,
                "aircraft,sar,ops_authorized",
                _poly(0, 100),
            ),
            f(
                "HP-1",
                "holding_position",
                "high",
                10,
                "aircraft,ops_authorized",
                _poly(200, 0),
            ),
            f(
                "STAND-1",
                "aircraft_stand",
                "medium",
                10,
                "aircraft,handling,sar,ops_authorized",
                _poly(400, 0),
            ),
            f(
                "ROAD",
                "service_road_corridor",
                "low",
                30,
                "handling,sar,ops_authorized",
                _poly(600, 0),
            ),
        ],
    }


def test_zones_from_geofences_maps_properties():
    zones, boundary = gadr.zones_from_geofences(_fc())
    assert zones.crs.to_string() == config.CRS_METRIC
    assert "AD" not in set(zones["zone_id"]) and boundary.area > zones.union_all().area
    z = zones.set_index("zone_id")
    assert z.loc["RWY-CRIT", "zone_type"] == "runway"
    assert z.loc["RWY-STRIP", "zone_type"] == "runway_strip"
    assert z.loc["HP-1", "zone_type"] == "holding_point"
    assert z.loc["RWY-CRIT", "criticality"] == 1.0
    assert z.loc["STAND-1", "criticality"] == 0.5
    assert z.loc["ROAD", "criticality"] == 0.2
    assert np.isnan(z.loc["RWY-CRIT", "speed_limit_mps"])
    assert z.loc["ROAD", "speed_limit_mps"] == pytest.approx(30 / 3.6)
    assert z.loc["HP-1", "allowed_groups"] == "aircraft,ops_authorized"


def test_unknown_zone_class_fails_loudly():
    fc = _fc()
    fc["features"][1]["properties"]["zone_class"] = "deicing_pad"
    with pytest.raises(ValueError, match="deicing_pad"):
        gadr.zones_from_geofences(fc)


def test_zone_access_follows_adr_groups():
    zones, _ = gadr.zones_from_geofences(_fc())
    za = gadr.zone_access(zones).set_index(["zone_type", "asset_class"])["allowed"]
    assert not za[("runway", "baggage_tractor")]
    assert za[("runway", "sar_vehicle")] and za[("runway", "follow_me")]
    assert not za[("holding_point", "sar_vehicle")]  # stricter than the default table
    assert za[("stand", "cleaning_van")]  # unmatched class, known group
    assert not za[("service_road", "narrowbody")]


def test_default_layers_unchanged_and_adr_profile(monkeypatch):
    from divas_air.geo import MapLayers

    default = MapLayers.load()
    assert default.profile == "osm" and default.zone_access is None
    assert MapLayers.load() is default

    gadr.load_adr.cache_clear()
    monkeypatch.setattr(gadr, "read_geofences", _fc)
    try:
        layers = MapLayers.load(profile="adr")
        assert layers.profile == "adr"
        assert len(layers.zones) == 5
        assert layers.routes is default.routes and layers.buildings is default.buildings
        assert set(layers.zone_access.columns) == {
            "zone_type",
            "asset_class",
            "allowed",
            "max_dwell_s",
        }
    finally:
        gadr.load_adr.cache_clear()
    with pytest.raises(ValueError):
        MapLayers.load(profile="nope")
