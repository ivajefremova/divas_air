"""Module 5 acceptance: flags the Baltic day, silent on the control.

Spec: specs/05_fleet.md. Frozen: do not edit to make it pass.
"""

import json

import h3
import numpy as np
import pandas as pd
import pytest

from divas_air import config, params, registry
from tests.helpers import LAT0, LON0, MODELS, T0, make_track, need, offset, verdicts_path

APRON, REGIONAL = params.APRON, params.REGIONAL
STEP = config.STRIDE_S


def apron_windows(n_tracks: int, degraded: dict[int, float], seconds: int = 240) -> pd.DataFrame:
    """Per-window table for n tracks parked within 10 m of one H3 cell center.

    `degraded` maps track index -> time (s after T0) from which it is degraded.
    """
    lat_c, lon_c = h3.cell_to_latlng(h3.latlng_to_cell(LAT0, LON0, APRON.h3_res))
    rows = []
    for i in range(n_tracks):
        lat, lon = offset(lat_c, lon_c, north=3.0 * (i % 3 - 1), east=3.0 * (i // 3 - 1))
        for k in range(seconds // STEP + 1):
            t = T0 + k * STEP
            rows.append(
                (f"test:veh_{i:03d}:0", t, float(lat), float(lon), i in degraded and t >= T0 + degraded[i])
            )
    return pd.DataFrame(rows, columns=["track_id", "t_end", "aux_lat", "aux_lon", "degraded"])


# --- apron profile on helper data -------------------------------------------------


def test_one_degraded_track_alone_is_not_an_area_event():
    from divas_air.fleet import cells_from_windows, fleet_features

    w = apron_windows(5, {0: 0.0})
    cells = cells_from_windows(w, APRON)
    assert not cells["flagged"].any()

    ff = fleet_features(w, APRON)
    assert len(ff) == len(w)
    assert set(registry.FLEET_COLUMNS) <= set(ff.columns)
    late = ff[ff["t_end"] >= T0 + 120]
    own = late[late["track_id"] == "test:veh_000:0"]
    assert (own["flt_n_others"] == 4).all()
    assert (own["flt_deg_count_loo"] == 0).all(), "a track must not see its own degradation"
    assert (own["flt_deg_rate_loo"] == 0).all()
    assert (own["flt_cell_flagged_loo"] == 0).all()
    other = late[late["track_id"] == "test:veh_001:0"]
    assert (other["flt_deg_count_loo"] == 1).all()


def test_many_degraded_together_raise_one_stable_area_alert():
    from divas_air.fleet import area_alerts, cells_from_windows, fleet_features

    w = apron_windows(6, {i: 60.0 for i in range(5)})
    cells = cells_from_windows(w, APRON)
    assert {"cell", "t_end", "n_tracks", "n_degraded", "share", "flagged"} <= set(cells.columns)
    assert not cells.loc[cells["t_end"] <= T0 + 55, "flagged"].any(), "flagged before the onset"
    late = cells[cells["t_end"] >= T0 + 60 + APRON.bin_s]
    assert late["flagged"].any()
    first_flag = cells.loc[cells["flagged"], "t_end"].min()
    assert first_flag <= T0 + 60 + APRON.bin_s, "area alert must appear within one bin of the onset"

    ff = fleet_features(w, APRON)
    end = ff[ff["t_end"] == T0 + 240].set_index("track_id")
    assert end.loc["test:veh_000:0", "flt_deg_count_loo"] == 4
    assert end.loc["test:veh_000:0", "flt_cell_flagged_loo"] == 1
    assert end.loc["test:veh_005:0", "flt_deg_count_loo"] == 5
    assert np.isclose(end.loc["test:veh_005:0", "flt_deg_rate_loo"], 1.0)

    alerts = area_alerts(cells, APRON)
    assert {"area_alert_id", "t_end", "cells", "geometry_wkt"} <= set(alerts.columns)
    late_alerts = alerts[alerts["t_end"] >= T0 + 60 + APRON.bin_s]
    assert late_alerts.groupby("t_end")["area_alert_id"].nunique().max() == 1
    assert late_alerts["area_alert_id"].nunique() == 1, "the alert id must be stable over time"


def test_two_tracks_are_too_few():
    from divas_air.fleet import cells_from_windows

    w = apron_windows(2, {0: 0.0, 1: 0.0})
    assert not cells_from_windows(w, APRON)["flagged"].any()


def test_noisy_cell_baseline_suppresses_the_flag():
    from divas_air.fleet import cells_from_windows

    w = apron_windows(4, {0: 0.0, 1: 0.0, 2: 0.0})
    cell = h3.latlng_to_cell(LAT0, LON0, APRON.h3_res)
    assert cells_from_windows(w, APRON)["flagged"].any()
    chronic = pd.DataFrame({"cell": [cell], "baseline": [0.7]})
    assert not cells_from_windows(w, APRON, baseline=chronic)["flagged"].any()


# --- regional profile on helper data ----------------------------------------------


def regional_points(n_tracks: int, bad_share: dict[int, float]) -> pd.DataFrame:
    lat_c, lon_c = h3.cell_to_latlng(h3.latlng_to_cell(LAT0, LON0, REGIONAL.h3_res))
    frames = []
    for i in range(n_tracks):
        g = make_track(
            track_id=f"test:{i:06x}:0",
            domain="aircraft",
            asset_class="narrowbody",
            speed_mps=1.0,
            alt_m=9000.0,
            n=20,
            lat0=lat_c + 0.001 * i,
            lon0=lon_c,
        )
        g["degraded"] = np.arange(len(g)) < round(bad_share.get(i, 0.0) * len(g))
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def test_regional_majority_rule():
    from divas_air.fleet import cells_from_points

    # track 0: a minority of bad readings; tracks 1-3: mostly bad; 8 clean
    cells = cells_from_points(regional_points(12, {0: 0.4, 1: 0.75, 2: 0.75, 3: 0.75}), REGIONAL)
    assert len(cells) == 1
    row = cells.iloc[0]
    assert row["n_tracks"] == 12 and row["n_degraded"] == 3
    assert np.isclose(row["share"], 0.25) and row["level"] == "red" and bool(row["flagged"])

    cells = cells_from_points(regional_points(12, {0: 0.4}), REGIONAL)
    assert cells.iloc[0]["n_degraded"] == 0 and cells.iloc[0]["level"] == "green"

    cells = cells_from_points(regional_points(REGIONAL.min_tracks - 1, {0: 1.0}), REGIONAL)
    assert len(cells) == 0, "cells below min_tracks do not qualify"


# --- real interference ------------------------------------------------------------


def regional_cells(source: str) -> pd.DataFrame:
    return pd.read_parquet(need(config.PROCESSED / "fleet" / f"{source}_regional_cells.parquet"))


def test_baltic_day_is_flagged():
    cells = regional_cells("baltic")
    assert len(cells) >= 50, f"only {len(cells)} qualifying cells; the reference has 109"
    red = (cells["level"] == "red").mean()
    assert red >= 0.70, f"red share {red:.0%}; the reference is 82 of 109"


def test_control_region_is_silent():
    cells = regional_cells("control")
    assert len(cells) >= 50, f"only {len(cells)} qualifying cells; the reference has 172"
    assert (cells["share"] > REGIONAL.warn_share).sum() == 0


# --- the batch pipeline -----------------------------------------------------------


@pytest.fixture(scope="module")
def verdicts() -> pd.DataFrame:
    return pd.read_parquet(need(verdicts_path("synthetic")))


def test_verdict_table_shape(verdicts):
    cols = {
        "track_id",
        "t_end",
        "integrity_raw",
        "integrity",
        "normality",
        "d_kinetic",
        "d_temporal",
        "d_spatial",
        "d_contextual",
        "trust_state",
        "normality_state",
        "quadrant",
        "confidence",
        "confidence_level",
        "cause",
        "severity_score",
        "severity_level",
        "zone_criticality",
        "action_code",
        "action_text",
        "area_alert_id",
        "evidence_json",
        "label_cause",
    }
    assert cols <= set(verdicts.columns)
    assert not verdicts.duplicated(["track_id", "t_end"]).any()
    assert verdicts["integrity"].between(0, 100).all() and verdicts["normality"].between(0, 100).all()
    assert set(verdicts["trust_state"]) <= {"trusted", "caution", "untrusted"}
    json.loads(verdicts["evidence_json"].iloc[0])


def test_interference_is_told_apart_from_a_single_fault(verdicts):
    splits = json.loads(need(MODELS / "splits.json").read_text())
    v = verdicts[verdicts["scene_id"].isin(splits["test"]) & ~verdicts["label_transition"].astype(bool)]

    jam = v[v["label_cause"] == "possible_interference"]
    assert len(jam) > 50
    grouped = (jam["cause"] == "possible_interference") | jam["area_alert_id"].notna()
    assert grouped.mean() >= 0.5, (
        f"only {grouped.mean():.0%} of interference windows recognized as an area event"
    )

    alone = v[v["label_cause"] == "technical_error"]
    assert len(alone) > 50
    assert (alone["cause"] == "possible_interference").mean() < 0.3
    assert alone["area_alert_id"].notna().mean() < 0.3


def test_models_were_retrained_with_fleet_features():
    card = json.loads(need(MODELS / "model_card.json").read_text())
    assert card["fleet"] is True
