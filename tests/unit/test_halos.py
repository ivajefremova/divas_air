"""Risk halos on tiny in-code inputs (specs/05_fleet.md requirements 12-14)."""

import math
from itertools import pairwise
from types import SimpleNamespace

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
import shapely

from divas_air import config, contract, params
from divas_air.geo import to_metric
from divas_air.halos import forecast_paths, live_halos, ring_error, static_halos
from tests.helpers import LAT0, LON0, T0, offset


def one_building(height: float = 20.0):
    x, y = to_metric([LON0], [LAT0])
    poly = shapely.box(x[0] - 10, y[0] - 10, x[0] + 10, y[0] + 10)
    b = gpd.GeoDataFrame({"height_m": [height]}, geometry=[poly], crs=config.CRS_METRIC)
    return SimpleNamespace(buildings=b), poly


def test_static_rings_follow_the_elevation_angle():
    layers, _ = one_building(20.0)
    fc = static_halos(layers)
    contract.RiskZones(t=0.0, features=fc["features"])
    by_id = {f["properties"]["risk_zone_id"]: f for f in fc["features"]}
    assert set(by_id) == {f"static_elev{a:.0f}" for a in params.HALO_ELEVATION_DEG}
    # outer edge of each band sits at height / tan(angle) from the building
    for ang in params.HALO_ELEVATION_DEG:
        reach = 20.0 / math.tan(math.radians(ang))
        lat_in, lon_in = offset(LAT0, LON0, east=10.0 + reach - 1.5)
        lat_out, lon_out = offset(LAT0, LON0, east=10.0 + reach + 1.5)
        g = shapely.geometry.shape(by_id[f"static_elev{ang:.0f}"]["geometry"])
        assert g.contains(shapely.Point(float(lon_in), float(lat_in)))
        assert not g.contains(shapely.Point(float(lon_out), float(lat_out)))


def test_static_levels_grow_with_the_angle():
    errs = [ring_error(a) for a in sorted(params.HALO_ELEVATION_DEG)]
    assert all(e1[0] < e2[0] and e1[1] < e2[1] for e1, e2 in pairwise(errs))
    open_err, open_level = ring_error(0.0)
    assert open_level == 0.0
    assert open_err == pytest.approx(
        1.177 * math.sqrt(1 + params.GNSS_WHITE_FRAC**2) * params.GNSS_OPEN_SIGMA_M
    )


def alerts_table():
    cell = h3.latlng_to_cell(LAT0, LON0, params.APRON.h3_res)
    return pd.DataFrame(
        {
            "area_alert_id": ["area_x", "area_x"],
            "t_end": [T0, T0 + 5],
            "cells": [[cell], [cell]],
            "share": [0.8, 0.75],
            "n_tracks": [5, 4],
            "n_degraded": [4, 3],
            "flagged": [True, True],
            "geometry_wkt": ["", ""],
        }
    ), cell


def test_live_halo_covers_the_cells_plus_sigma():
    alerts, cell = alerts_table()
    halos = live_halos(alerts, T0 + 5, {"area_x": ["test:b:0", "test:a:0"]})
    assert len(halos) == 1
    p = halos[0]["properties"]
    assert p["kind"] == "live" and p["area_alert_id"] == "area_x"
    assert p["level"] == pytest.approx(0.75)
    assert p["track_ids"] == ["test:a:0", "test:b:0"]
    assert p["action"]["code"] == "area_gnss_unreliable"
    assert p["t_start"] == T0 and p["t_end"] == T0 + 5
    g = shapely.geometry.shape(halos[0]["geometry"])
    lat_c, lon_c = h3.cell_to_latlng(cell)
    lat, lon = offset(
        lat_c, lon_c, north=params.HALO_SIGMA_M + 150.0
    )  # cell radius is ~175 m
    assert g.contains(shapely.Point(float(lon), float(lat)))
    assert live_halos(alerts, T0 + 10, {}) == []


def test_forecast_enters_a_halo_ahead():
    alerts, cell = alerts_table()
    halo = live_halos(alerts, T0, {})[0]
    lat_c, lon_c = h3.cell_to_latlng(cell)
    lat, lon = offset(lat_c, lon_c, east=-700.0)
    rows = pd.DataFrame(
        {
            "track_id": ["test:moving:0", "test:away:0", "test:stopped:0"],
            "aux_lat": [float(lat)] * 3,
            "aux_lon": [float(lon)] * 3,
            "aux_gs_mps": [10.0, 10.0, 0.0],
            "aux_track_deg": [90.0, 270.0, 90.0],
        }
    )
    out = forecast_paths(rows, [halo], T0)
    assert [f["properties"]["track_ids"] for f in out] == [["test:moving:0"]]
    p = out[0]["properties"]
    assert (
        p["kind"] == "forecast"
        and p["enters_risk_zone_id"] == halo["properties"]["risk_zone_id"]
    )
    assert 0 < p["eta_s"] <= max(params.FORECAST_HORIZONS_S)
    assert out[0]["geometry"]["type"] == "LineString"
    # a track already inside the halo gets no forecast
    inside = rows.assign(aux_lat=lat_c, aux_lon=lon_c)
    assert forecast_paths(inside, [halo], T0) == []
    assert np.isfinite(p["eta_s"])
