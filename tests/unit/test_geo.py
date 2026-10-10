"""Module 2 unit tests: map-layer loader and GNSS error model."""

import numpy as np
import pytest

from divas_air import config, params
from divas_air.geo import gnss
from tests.helpers import LAT0, LON0


@pytest.fixture(scope="module")
def layers():
    if not (config.LAYERS / "runways.geojson").exists():
        pytest.skip("map layers not present")
    from divas_air.geo import MapLayers

    return MapLayers.load()


def test_zones_are_normalized(layers):
    z = layers.zones
    assert z.crs.to_string() == config.CRS_METRIC
    assert {
        "zone_id",
        "zone_name",
        "zone_type",
        "criticality",
        "speed_limit_mps",
    } <= set(z.columns)
    assert set(z["zone_type"]) == set(params.ZONE_CRITICALITY)
    assert z["zone_id"].is_unique
    assert z["criticality"].between(0, 1).all()
    assert (z.loc[z["zone_type"] == "runway", "criticality"] == 1.0).all()
    lim = z["speed_limit_mps"].dropna()
    assert len(lim) > 0 and lim.between(4.0, 15.0).all()  # km/h converted to m/s


def test_runway_ends_have_matching_bearings(layers):
    rw = layers.runways
    assert len(rw) == 6
    for end, bearing in zip(rw["end"], rw["bearing_deg"], strict=True):
        diff = abs((int(end[:2]) * 10 - bearing + 180) % 360 - 180)
        assert diff < 15, (end, bearing)


def test_roundtrip_and_route_distance(layers):
    x, y = layers.to_metric([LON0], [LAT0])
    lon, lat = layers.to_wgs84(x, y)
    np.testing.assert_allclose([lon[0], lat[0]], [LON0, LAT0], atol=1e-9)

    g = layers.routes["vehicle"]
    nx_, ny_ = zip(
        *[(d["x"], d["y"]) for _, d in list(g.nodes(data=True))[:20]], strict=True
    )
    d = layers.route_distance_m(np.array(nx_), np.array(ny_), "vehicle")
    assert np.all(d < 1e-6)


def test_error_ratio_grows_with_obstruction():
    r = gnss.error_ratio([0.0, 15.0, 45.0, 80.0])
    assert r[0] == 1.0 and r[2] == params.GNSS_OBSTRUCTED_RATIO and r[3] == r[2]
    assert np.all(np.diff(r) >= 0)


def test_nacp_bounds():
    np.testing.assert_array_equal(
        gnss.nacp_from_epu([2.0, 5.0, 20.0, 50.0, 100.0]), [11, 10, 9, 8, 7]
    )
    nacp, _ = gnss.integrity_from_sigma(params.GNSS_OPEN_SIGMA_M)
    assert nacp == 10


def test_gauss_markov_is_correlated_and_unit_variance():
    rng = np.random.default_rng(0)
    t = np.arange(0, 20000, 1.0)
    x = gnss.gauss_markov(t, 30.0, rng)
    assert 0.8 < x.std() < 1.2
    rho = np.corrcoef(x[:-1], x[1:])[0, 1]
    assert abs(rho - np.exp(-1 / 30)) < 0.02


def test_nominal_integrity_matches_fco():
    nacp, nic = gnss.integrity_from_sigma(params.GNSS_OPEN_SIGMA_M)
    assert (nacp, nic) == (10, 8)
    nacp_bad, nic_bad = gnss.integrity_from_sigma(30 * params.GNSS_OPEN_SIGMA_M)
    assert nacp_bad < nacp and nic_bad < nic
