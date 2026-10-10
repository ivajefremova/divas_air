"""Module 2 unit tests: inject() per cause, speed profile, sampling. No data, no layers."""

import numpy as np
import pandas as pd
import pytest

from divas_air import params, schema
from divas_air.synth import inject
from divas_air.synth.inject import apply_event
from divas_air.synth.motion import envelopes, sample_times, speed_profile
from tests.helpers import LAT0, T0, error_m, make_track

ONSET = T0 + 60.0
A, B = "test:veh_001:0", "test:veh_002:0"


def two_tracks(**kw) -> pd.DataFrame:
    a = make_track(track_id=A, n=200, **kw)
    b = make_track(track_id=B, n=200, lat0=LAT0 + 0.01, **kw)
    return pd.concat([a, b], ignore_index=True)


def run(cause, duration=60.0, seed=0, **p):
    pts = two_tracks()
    out, info = apply_event(
        pts,
        cause,
        onset_t=ONSET,
        duration_s=duration,
        track_ids=[A],
        seed=seed,
        params=p,
    )
    schema.validate(out, labeled=True)
    a = out[out["track_id"] == A].sort_values("seq")
    return pts, out, a, info


def during(df, duration=60.0):
    return df[(df["t"] >= ONSET) & (df["t"] < ONSET + duration)]


def test_inject_adds_label_columns_and_keeps_track_ids():
    pts, out, _, info = run("degraded")
    assert set(schema.LABEL_COLUMNS) <= set(out.columns)
    assert set(out["track_id"]) == set(pts["track_id"])
    assert info["track_ids"] == [A]
    assert (out.loc[out["track_id"] == B, "label_cause"] == "plausible").all()


def test_degraded_adds_noise_and_lowers_integrity():
    _, _, a, info = run("degraded", noise_factor=8.0, integrity_drop=2)
    ev = during(a)
    assert error_m(ev).mean() > 3 * params.GNSS_OPEN_SIGMA_M
    assert (ev["nacp"] == 8).all()
    assert info["params_json"].count("noise_factor") == 1


@pytest.mark.parametrize(
    "mode", ["freeze", "jump", "duplicate_t", "out_of_order", "loss"]
)
def test_technical_error_modes(mode):
    _, _, a, _ = run("technical_error", mode=mode)
    ev = during(a)
    assert (ev["label_cause"] == "technical_error").all()
    assert (a["nacp"] == 10).all()
    if mode == "freeze":
        assert ev["lat"].nunique() == 1 and (ev["gs_mps"] > 0).all()
    elif mode == "jump":
        assert error_m(ev).min() >= 49.0
    elif mode == "duplicate_t":
        assert a["t"].duplicated().any()
    elif mode == "out_of_order":
        assert (np.diff(a.sort_values("seq")["t"].to_numpy()) < 0).any()
    elif mode == "loss":
        assert len(a) < 200
        assert len(ev) >= 2  # both edges keep a labeled fix
        assert np.diff(ev["t"].to_numpy()).max() >= 10.0


def test_gnss_anomaly_grows_and_lowers_nacp():
    _, _, a, _ = run("gnss_anomaly", drift_mps=3.0)
    ev = during(a)
    err = error_m(ev)
    assert err[-5:].mean() > err[:5].mean() + 100
    assert ev["nacp"].iloc[-1] < 10
    np.testing.assert_allclose(ev["gs_mps"], 5.0)  # true motion still reported


def test_spoofing_is_smooth_and_keeps_nacp():
    _, _, a, _ = run("possible_spoofing", duration=100.0, drift_mps=2.0)
    ev = during(a, 100.0)
    err = error_m(ev)
    assert (ev["nacp"] == 10).all()
    assert err.max() > 150
    assert np.abs(np.diff(err, 2)).max() < 1.0  # no jitter added on top of the drift


def test_interference_region_fades_and_collapses_nacp():
    from shapely.geometry import Point

    from tests.helpers import LON0

    tracks = [
        make_track(track_id=f"test:veh_{i:03d}:0", n=200, lat0=LAT0 + 0.0005 * i)
        for i in range(4)
    ]
    pts = pd.concat(tracks, ignore_index=True)
    out, info = apply_event(
        pts,
        "possible_interference",
        onset_t=ONSET,
        duration_s=90.0,
        region=Point(LON0, LAT0).buffer(0.01),
        seed=1,
    )
    schema.validate(out, labeled=True)
    assert len(info["track_ids"]) == 4
    assert info["region_wkt"].startswith("POLYGON")
    ev = out[out["label_cause"] == "possible_interference"]
    assert ev["nacp"].median() <= 5


def test_behavioral_deviation_moves_truth_and_keeps_noise():
    pts = pd.concat(
        [
            make_track(track_id=A, n=400),
            make_track(track_id=B, n=400, lat0=LAT0 + 0.01),
        ],
        ignore_index=True,
    )
    # give the clean track some noise so we can check it is carried over
    rng = np.random.default_rng(0)
    pts = inject(
        pts, "degraded", onset_t=T0 - 100, duration_s=1.0, track_ids=[A]
    )  # adds labels only
    pts["lat"] = pts["lat"] + rng.normal(0, 1e-5, len(pts))
    out = inject(
        pts,
        "behavioral_anomaly",
        onset_t=ONSET,
        duration_s=200.0,
        track_ids=[A],
        params={"mode": "deviate", "offset_m": 80.0},
    )
    a_in = pts[pts["track_id"] == A].sort_values("seq")
    a = out[out["track_id"] == A].sort_values("seq")
    moved = error_m(
        a.assign(
            lat=a_in["lat"].to_numpy(),
            lon=a_in["lon"].to_numpy(),
            label_true_lat=a["label_true_lat"],
            label_true_lon=a["label_true_lon"],
        )
    )
    assert moved.max() > 70
    noise_in = a_in["lat"].to_numpy() - a_in["label_true_lat"].to_numpy()
    noise_out = a["lat"].to_numpy() - a["label_true_lat"].to_numpy()
    np.testing.assert_allclose(
        noise_in, noise_out, atol=2e-7
    )  # same receiver error, metres-level
    limit = envelopes().loc["bus", "max_ground_speed_mps"] * params.LIMIT_MARGIN
    assert a["gs_mps"].max() < limit


def test_incursion_reaches_target_and_labels_from_zone_entry():
    from shapely.geometry import box

    from tests.helpers import LON0, offset

    slow = make_track(track_id=A, n=300, speed_mps=0.2)  # waiting at the roadside
    tlat, tlon = (float(v) for v in offset(LAT0, LON0, north=150.0))
    zone = box(tlon - 0.002, tlat - 0.0005, tlon + 0.002, tlat + 0.002)
    p = {
        "mode": "incursion",
        "target_lat": tlat,
        "target_lon": tlon,
        "speed_mps": 5.0,
        "zone_wkt": zone.wkt,
    }
    out, info = apply_event(
        slow,
        "behavioral_anomaly",
        onset_t=ONSET,
        duration_s=120.0,
        track_ids=[A],
        params=p,
    )
    schema.validate(out, labeled=True)
    assert info["t_onset"] > ONSET
    lab = out[out["label_cause"] == "behavioral_anomaly"]
    assert lab["t"].min() == pytest.approx(info["t_onset"])
    assert (lab["label_onset_t"] == info["t_onset"]).all()
    # 45 s in, 30 s held at the target, 45 s back
    held = out[(out["t"] > ONSET + 50) & (out["t"] < ONSET + 70)]
    truth = held.assign(lat=tlat, lon=tlon)
    assert error_m(truth).max() < 2.0


def test_inject_without_selection_raises():
    with pytest.raises(ValueError):
        inject(two_tracks(), "degraded", onset_t=ONSET, duration_s=10.0)


def test_speed_profile_stays_in_envelope():
    poly = np.array([[0, 0], [300, 0], [300, 300], [0, 300]], dtype=float)
    t, x, y, v = speed_profile(poly, np.full(4, np.inf), "fuel_truck", 6.0)
    env = envelopes().loc["fuel_truck"]
    assert v[0] == 0 and v[-1] == 0 and v.max() <= 6.0 + 1e-9
    ts = np.arange(0, t[-1], 1.0)
    vs = np.interp(ts, t, v)
    acc = np.abs(vs[5:] - vs[:-5]) / 5.0
    assert acc.max() <= env["max_accel_mps2"]
    hd = np.unwrap(
        np.arctan2(np.gradient(np.interp(ts, t, y)), np.gradient(np.interp(ts, t, x)))
    )
    rate = np.degrees(np.abs(hd[5:] - hd[:-5])) / 5.0
    assert rate[vs[5:] > params.COURSE_MIN_MPS].max() <= env["max_turn_rate_dps"]


def test_sample_times():
    rng = np.random.default_rng(0)
    ts = sample_times(rng, "vehicle", T0, T0 + 100)
    dt = np.round(np.diff(ts))
    assert set(dt) <= {1.0, 2.0} and len(set(dt)) == 1
    full = sample_times(rng, "aircraft", T0, T0 + 100, full_span=True)
    assert full[0] == T0 and full[-1] == T0 + 100 and np.all(np.diff(full) > 0)


def test_holdout_days_are_excluded():
    from divas_air.synth.motion import not_held_out

    day = 86400.0
    t = pd.Series(T0 - (T0 % day) + day * np.array([0, 1, 2, 3, 4, 5]) + 100.0)
    np.testing.assert_array_equal(
        not_held_out(t), [True, True, True, True, False, False]
    )
