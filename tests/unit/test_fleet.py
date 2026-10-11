"""Fleet layer on tiny in-code tables (specs/05_fleet.md)."""

import h3
import numpy as np
import pandas as pd

from divas_air import config, params, registry
from divas_air.fleet import (
    alert_members,
    apron_baseline,
    area_alerts,
    cells_from_points,
    cells_from_windows,
    fleet_features,
)
from tests.helpers import LAT0, LON0, T0, make_track

APRON = params.APRON
STEP = config.STRIDE_S


def windows_at(
    centers: list[tuple[float, float]], degraded: dict[int, float], seconds: int = 120
) -> pd.DataFrame:
    rows = []
    for i, (lat, lon) in enumerate(centers):
        for k in range(seconds // STEP + 1):
            t = T0 + k * STEP
            rows.append(
                (
                    f"test:veh_{i:03d}:0",
                    t,
                    lat,
                    lon,
                    i in degraded and t >= T0 + degraded[i],
                )
            )
    return pd.DataFrame(
        rows, columns=["track_id", "t_end", "aux_lat", "aux_lon", "degraded"]
    )


def cell_center(cell: str) -> tuple[float, float]:
    return h3.cell_to_latlng(cell)


def test_fleet_features_one_row_per_input_in_order():
    w = (
        windows_at([(LAT0, LON0)] * 3, {0: 0.0})
        .sample(frac=1.0, random_state=0)
        .reset_index(drop=True)
    )
    ff = fleet_features(w, APRON)
    assert list(ff.columns) == ["track_id", "t_end", *registry.FLEET_COLUMNS]
    assert (
        ff[["track_id", "t_end"]].to_numpy() == w[["track_id", "t_end"]].to_numpy()
    ).all()


def test_leave_one_out_counts_neighbors_in_k_ring():
    c0 = h3.latlng_to_cell(LAT0, LON0, APRON.h3_res)
    nbr = min(h3.grid_ring(c0, 1))
    far = min(h3.grid_ring(c0, 3))
    centers = [cell_center(c0), cell_center(nbr), cell_center(nbr), cell_center(far)]
    w = windows_at(centers, {1: 0.0, 2: 0.0, 3: 0.0})
    ff = fleet_features(w, APRON).set_index("track_id")
    last = ff[ff["t_end"] == T0 + 120]
    assert (
        last.loc["test:veh_000:0", "flt_n_others"] == 2
    )  # the far track is outside the ring
    assert last.loc["test:veh_000:0", "flt_deg_count_loo"] == 2
    assert last.loc["test:veh_001:0", "flt_deg_count_loo"] == 1  # not itself
    assert last.loc["test:veh_003:0", "flt_n_others"] == 0
    assert last.loc["test:veh_003:0", "flt_deg_rate_loo"] == 0


def test_neighbor_flag_fraction():
    c0 = h3.latlng_to_cell(LAT0, LON0, APRON.h3_res)
    nbr = min(h3.grid_ring(c0, 1))
    centers = [cell_center(c0)] + [cell_center(nbr)] * 4
    w = windows_at(centers, {i: 0.0 for i in range(1, 5)})
    ff = fleet_features(w, APRON)
    v = ff.loc[ff["track_id"] == "test:veh_000:0", "flt_nbr_flagged_frac"]
    assert np.allclose(v, 1 / 6)


def test_presence_span_carries_a_finished_track():
    w = windows_at([(LAT0, LON0)] * 3, {0: 0.0, 1: 0.0, 2: 0.0}, seconds=60)
    cells = cells_from_windows(w, APRON)
    assert cells["t_end"].max() == T0 + 60 + APRON.bin_s - STEP
    assert not (cells["t_end"] >= T0 + 60 + APRON.bin_s).any()


def test_apron_baseline_is_the_cell_rate():
    w = windows_at([(LAT0, LON0)] * 4, {0: 0.0})
    b = apron_baseline(w, APRON)
    assert len(b) == 1 and np.isclose(b["baseline"].iloc[0], 0.25)


def test_alert_held_then_dropped_and_members():
    w = windows_at([(LAT0, LON0)] * 4, {i: 0.0 for i in range(4)}, seconds=60)
    w2 = w.copy()
    # recover the tracks after 30 s so the cell is no longer flagged
    w2.loc[w2["t_end"] > T0 + 30, "degraded"] = False
    cells = cells_from_windows(w2, APRON)
    alerts = area_alerts(cells, APRON)
    assert alerts["area_alert_id"].nunique() == 1
    held = alerts[~alerts["flagged"]]
    assert held["t_end"].min() == T0 + 35
    assert held["t_end"].max() == T0 + 30 + APRON.bin_s - STEP
    m = alert_members(w2, alerts, APRON)
    assert set(m["track_id"]) == set(w2["track_id"])
    assert m["t_end"].max() == T0 + 60


def test_two_separate_components_get_two_ids():
    c0 = h3.latlng_to_cell(LAT0, LON0, APRON.h3_res)
    far = min(h3.grid_ring(c0, 4))
    centers = [cell_center(c0)] * 3 + [cell_center(far)] * 3
    w = windows_at(centers, {i: 0.0 for i in range(6)})
    alerts = area_alerts(cells_from_windows(w, APRON), APRON)
    assert alerts.groupby("t_end")["area_alert_id"].nunique().max() == 2
    assert alerts["area_alert_id"].nunique() == 2


def test_regional_reads_nacp_when_no_degraded_column():
    lat_c, lon_c = h3.cell_to_latlng(
        h3.latlng_to_cell(LAT0, LON0, params.REGIONAL.h3_res)
    )
    frames = []
    for i in range(10):
        g = make_track(
            track_id=f"test:{i:06x}:0",
            domain="aircraft",
            asset_class="narrowbody",
            alt_m=9000.0,
            n=20,
            lat0=lat_c + 0.001 * i,
            lon0=lon_c,
            speed_mps=1.0,
        )
        if i < 2:
            g.loc[g.index[5:], "nacp"] = (
                6.0  # good first, then degraded: eligible and bad
            )
        frames.append(g)
    never_good = make_track(
        track_id="test:ffffff:0",
        domain="aircraft",
        asset_class="narrowbody",
        alt_m=9000.0,
        n=20,
        lat0=lat_c,
        lon0=lon_c,
        nacp=5.0,
        speed_mps=1.0,
    )
    cells = cells_from_points(
        pd.concat(frames + [never_good], ignore_index=True), params.REGIONAL
    )
    row = cells.iloc[0]
    assert (
        row["n_tracks"] == 10 and row["n_degraded"] == 2
    )  # the never-good aircraft is not eligible
    assert row["level"] == "red"


def test_regional_skips_ground_readings():
    g = make_track(
        track_id="test:aaaaaa:0", domain="aircraft", asset_class="narrowbody", n=10
    )
    assert bool(g["on_ground"].all())
    assert len(cells_from_points(g.assign(degraded=True), params.REGIONAL)) == 0
