"""Module 3 unit tests: kinetic, temporal and signal features, labels, thresholds."""

import numpy as np
import pandas as pd
import pytest

from divas_air import params, registry, schema
from divas_air.degradation import is_degraded_reading
from divas_air.features import compute_features
from divas_air.features.calibrate import fit_thresholds
from tests.helpers import T0, make_track, renumber

KEYS = ["track_id", "t_end"]


def cf(pts):
    return compute_features(pts, layers=None).sort_values(KEYS).reset_index(drop=True)


def test_degraded_reading_rule():
    pts = make_track(n=4).assign(nacp=[7.0, 8.0, np.nan, 0.0])
    assert is_degraded_reading(pts).tolist() == [True, False, False, True]


def test_overspeed_on_the_ground():
    f = cf(make_track(asset_class="bus", speed_mps=15.0))
    f = f[f["tmp_n_points"] >= 25]
    assert np.allclose(f["kin_speed_ratio_max"], 15.0 / 8.5, atol=0.05)
    assert (f["kin_speed_ratio_max"] > params.LIMIT_MARGIN).all()


def test_turn_rate_over_the_class_limit():
    pts = make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca005:0",
        speed_mps=80.0,
        alt_m=500.0,
    )
    pts["track_deg"] = (
        90.0 + 12.0 * (pts["t"] - T0)
    ) % 360.0  # reports 12 deg/s, narrowbody max 6
    f = cf(pts)
    assert np.nanmax(f["kin_turn_rate_ratio_max"]) == pytest.approx(2.0)


def test_update_rate_change_needs_history():
    a = make_track(asset_class="bus", n=200)
    pts = renumber(
        a[(a["t"] < T0 + 100) | ((a["t"] - T0) % 3 == 1)]
    )  # 1 s, then every 3 s
    f = cf(pts).set_index("t_end")
    assert f.loc[T0 + 25 : T0 + 30, "tmp_dt_dev_ratio"].isna().all(), (
        "no baseline before 30 s of history"
    )
    assert f.loc[T0 + 60, "tmp_dt_dev_ratio"] == 0
    assert abs(f.loc[T0 + 140, "tmp_dt_dev_ratio"] - 2.0) < 1e-9


def test_position_only_fixes_get_no_envelope_ratios():
    """No velocity, no NACp, NIC 0 (MLAT/TIS-B): implied motion is not checked against the envelope."""
    pts = make_track(
        domain="aircraft",
        asset_class="light",
        track_id="test:3004aa:0",
        speed_mps=200.0,
        alt_m=500.0,
    )
    pts = pts.assign(
        gs_mps=np.nan,
        track_deg=np.nan,
        heading_deg=np.nan,
        nacp=np.nan,
        nic=0.0,
        sil=np.nan,
    )
    f = cf(pts)
    assert f[registry.ENVELOPE_RATIO_COLUMNS].isna().all().all()
    assert f["kin_pos_jitter_m"].notna().any()


def test_moving_speed_without_course_is_not_a_report():
    """readsb keeps a stale ground speed when no velocity message arrived: no course, no speed."""
    pts = make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca003:0",
        speed_mps=80.0,
        alt_m=500.0,
    )
    stale = pts["t"].between(T0 + 60, T0 + 62)
    pts.loc[stale, "gs_mps"] = 12.0
    pts.loc[stale, "track_deg"] = np.nan
    f = cf(pts)
    assert np.nanmax(f["kin_accel_ratio_max"]) < 0.1
    assert np.nanmax(f["kin_speed_resid_max"]) < 1.0


def test_aircraft_on_the_ground_without_map_uses_the_ground_limit():
    pts = make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca004:0",
        speed_mps=10.0,
    )
    f = cf(pts)
    assert np.allclose(f["aux_class_max_speed_mps"], 15.0)
    assert not f["aux_airborne"].any()


def test_jitter_measures_position_noise():
    rng = np.random.default_rng(params.SEED)
    pts = make_track(asset_class="bus", speed_mps=5.0)
    from tests.helpers import shift_m

    noisy = pts.copy()
    for i in range(len(noisy)):
        noisy = shift_m(
            noisy, noisy.index == i, north=rng.normal(0, 2.0), east=rng.normal(0, 2.0)
        )
    f = cf(noisy)
    full = f[f["tmp_n_points"] >= 25]
    assert (
        full["kin_pos_jitter_m"].between(1.5, 4.0).all()
    )  # RMS of 2-D noise with sigma 2 m: ~2.8 m


def test_empty_window_takes_the_label_of_agreeing_neighbours():
    a = make_track(asset_class="bus", labeled=True, n=200)
    a.loc[a["t"] >= T0 + 50, ["label_cause", "label_event_id"]] = [
        "possible_interference",
        "ev2",
    ]
    a.loc[a["t"] >= T0 + 50, "label_onset_t"] = T0 + 50
    pts = renumber(a[(a["t"] <= T0 + 60) | (a["t"] >= T0 + 120)])
    schema.validate(pts, labeled=True)
    f = cf(pts).set_index("t_end")
    assert f.loc[T0 + 100, "tmp_n_points"] == 0
    assert f.loc[T0 + 100, "label_frac"] == 1.0
    assert f.loc[T0 + 100, "label_cause"] == "possible_interference"
    assert f.loc[T0 + 100, "label_event_id"] == "ev2"
    assert f.loc[T0 + 100, "label_onset_t"] == T0 + 50


def test_two_tracks_do_not_mix():
    a = make_track(track_id="test:veh_a:0", asset_class="bus", speed_mps=5.0)
    b = make_track(
        track_id="test:veh_b:0",
        asset_class="bus",
        speed_mps=5.0,
        lat0=41.81,
        t0=T0 + 7.0,
    )
    f = cf(pd.concat([a, b], ignore_index=True))
    assert set(f["track_id"]) == {"test:veh_a:0", "test:veh_b:0"}
    assert f["kin_speed_resid_max"].max() < 0.5
    one = cf(b)
    both = f[f["track_id"] == "test:veh_b:0"].reset_index(drop=True)
    pd.testing.assert_frame_equal(one, both)


def test_thresholds_floor_at_the_registry_default():
    rng = np.random.default_rng(params.SEED)
    cols = registry.FEATURE_COLUMNS
    df = pd.DataFrame({c: rng.uniform(0, 1, 1000) for c in cols})
    df["kin_speed_resid_max"] = rng.uniform(0, 50, 1000)  # p99.9 near 50 > default 10
    th = fit_thresholds({"aircraft": (df, "test")}).set_index(["name", "domain"])
    assert th.loc[("kin_speed_resid_max", "aircraft"), "tau"] > 45
    assert (
        th.loc[("kin_speed_resid_mean", "aircraft"), "tau"]
        == registry.REGISTRY["kin_speed_resid_mean"].tau
    )
    assert (
        th.loc[("kin_speed_resid_max", "vehicle"), "tau"] == 10.0
    )  # no clean vehicle windows
    assert th.loc[("kin_speed_ratio_max", "aircraft"), "tau"] == params.LIMIT_MARGIN
    assert th["tau"].notna().all()
    scored = {s.name for s in registry.REGISTRY.values() if s.scored}
    assert set(th.index.get_level_values("name")) == scored
