"""Module 3 unit tests: spatial and contextual features on the LIRF layers."""

import numpy as np
import pytest
import shapely

from divas_air import config, params
from divas_air.features import compute_features
from tests.helpers import T0, make_track, renumber


@pytest.fixture(scope="module")
def layers():
    if not (config.LAYERS / "runways.geojson").exists():
        pytest.skip("map layers not present")
    from divas_air.geo import MapLayers

    return MapLayers.load()


def _on(layers, zone_type: str):
    """A (lat, lon) inside a zone of this type, away from every other zone type's polygon."""
    z = layers.zones
    others = shapely.union_all(z[z["zone_type"] != zone_type].geometry.to_numpy())
    for geom in z[z["zone_type"] == zone_type].geometry:
        p = shapely.difference(geom, others.buffer(5.0)).representative_point()
        if not p.is_empty:
            lon, lat = layers.to_wgs84([p.x], [p.y])
            return float(lat[0]), float(lon[0])
    raise AssertionError(f"no clear {zone_type} point")


def test_bus_parked_on_a_runway(layers):
    lat, lon = _on(layers, "runway")
    pts = make_track(asset_class="bus", speed_mps=0.0, lat0=lat, lon0=lon, n=200)
    f = compute_features(pts, layers).set_index("t_end")
    assert (f["spa_zone_crit_max"] == 1.0).all()
    assert (f["aux_zone_type"] == "runway").all()
    assert (f["ctx_type_violation_crit_max"] == 1.0).all()
    assert (f["spa_off_airport"] == 0).all()
    # dwell: the runway allows 120 s; the bus has been still since T0
    assert f.loc[T0 + 60, "ctx_dwell_ratio"] < 1.0
    assert abs(f.loc[T0 + 180, "ctx_dwell_ratio"] - 180 / 120) < 0.05


def test_aircraft_rolling_on_a_runway_uses_the_air_limit(layers):
    rw = layers.runways.set_index("end")
    lat = float(rw.loc[["16R", "34L"], "threshold_lat"].mean())
    lon = float(rw.loc[["16R", "34L"], "threshold_lon"].mean())
    pts = make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca010:0",
        speed_mps=60.0,
        course_deg=float(rw.loc["16R", "bearing_deg"]),
        lat0=lat,
        lon0=lon,
        n=12,
    )
    f = compute_features(pts, layers)
    assert np.allclose(f["aux_class_max_speed_mps"], 320.0)
    assert np.nanmax(f["kin_speed_ratio_max"]) < 1.0
    assert (f["ctx_type_violation_crit_max"] == 0).all()


def test_aircraft_on_a_taxiway_uses_the_taxi_limit(layers):
    lat, lon = _on(layers, "taxiway")
    pts = make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca011:0",
        speed_mps=0.5,
        lat0=lat,
        lon0=lon,
    )
    f = compute_features(pts, layers)
    assert np.allclose(f["aux_class_max_speed_mps"], 15.0)


def test_service_road_speeding(layers):
    z = layers.zones
    road = z[(z["zone_type"] == "service_road") & z["speed_limit_mps"].notna()].iloc[0]
    p = road.geometry.representative_point()
    lon, lat = layers.to_wgs84([p.x], [p.y])
    pts = make_track(
        asset_class="follow_me",
        speed_mps=0.0,
        lat0=float(lat[0]),
        lon0=float(lon[0]),
        n=40,
    )
    pts["gs_mps"] = (
        1.5 * road["speed_limit_mps"]
    )  # reports speeding while the map position is still
    f = compute_features(pts, layers)
    assert np.nanmax(f["ctx_zone_speed_ratio_max"]) == pytest.approx(1.5)
    assert np.nanmax(f["aux_zone_speed_limit_mps"]) == pytest.approx(
        road["speed_limit_mps"]
    )


def test_far_from_the_map_there_are_no_map_features(layers):
    pts = make_track(asset_class="bus", lat0=55.0, lon0=20.0)
    f = compute_features(pts, layers)
    from divas_air.features import MAP_FEATURES

    assert f[MAP_FEATURES].isna().all().all()


def test_map_features_are_causal(layers):
    lat, lon = _on(layers, "runway")
    a = make_track(asset_class="bus", speed_mps=0.0, lat0=lat, lon0=lon, n=200)
    full = compute_features(a, layers)
    cut = compute_features(renumber(a[a["t"] <= T0 + 100]), layers)
    left = full[full["t_end"] <= T0 + 100].reset_index(drop=True)
    right = cut[cut["t_end"] <= T0 + 100].reset_index(drop=True)
    cols = [c for c in left.columns if c.startswith(("spa_", "ctx_"))]
    np.testing.assert_allclose(
        left[cols].to_numpy(float), right[cols].to_numpy(float), equal_nan=True
    )
    assert params.DWELL_MOVE_M > 0


def test_ground_fixes_away_from_lirf_get_no_map_features(layers):
    """Ciampino lies inside the approach box but has no layers."""
    pts = make_track(asset_class="bus", lat0=41.80, lon0=12.59)
    f = compute_features(pts, layers)
    assert (
        f[["spa_off_airport", "spa_route_dist_max_m", "spa_zone_crit_max"]]
        .isna()
        .all()
        .all()
    )


def _final(layers, end: str, dist_m: float, height_m: float, n: int = 40):
    from divas_air.features.core import GEOD

    rw = layers.runways.set_index("end").loc[end]
    lon, lat, _ = GEOD.fwd(
        rw["threshold_lon"], rw["threshold_lat"], rw["bearing_deg"] + 180.0, dist_m
    )
    return make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca012:0",
        speed_mps=70.0,
        course_deg=float(rw["bearing_deg"]),
        lat0=lat,
        lon0=lon,
        alt_m=height_m,
        n=n,
    )


def test_final_approach_picks_the_runway_on_the_centerline(layers):
    f = compute_features(_final(layers, "16R", 8000.0, 420.0), layers)
    assert (f["aux_zone_id"] == "approach_16R").all()
    assert f["ctx_app_lateral_dev_deg"].max() < 0.5
    assert (f["spa_zone_crit_max"] == params.CRITICALITY_AIRBORNE_FINAL).all()


def test_overflight_is_not_on_final(layers):
    f = compute_features(_final(layers, "16R", 8000.0, 10000.0), layers)
    assert f["ctx_app_lateral_dev_deg"].isna().all()
    assert (f["spa_zone_crit_max"] == params.CRITICALITY_AIRBORNE_OTHER).all()


def test_airline_callsign_on_an_unknown_light_type(layers):
    pts = _final(layers, "16R", 8000.0, 420.0)
    pts["typecode_raw"] = pts["typecode_raw"].astype("string")
    pts.loc[:, "typecode_raw"] = "EFOX"  # maps to `other`
    pts.loc[pts.index[0], "callsign"] = "AZA123"  # sent once, carried forward
    f = compute_features(pts, layers)
    assert (f["ctx_identity_mismatch"] >= 1).all()
