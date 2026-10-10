"""Module 2 acceptance: every cause present, noise drawn from the error model.

Spec: specs/02_generator.md. Frozen: do not edit to make it pass.
"""

import json

import numpy as np
import pandas as pd
import pytest

from divas_air import config, schema
from tests.helpers import LAT0, LON0, T0, error_m, make_track, need, points_path

SYNTH_EVENTS = config.PROCESSED / "synth" / "events.parquet"
DEMO_EVENTS = config.PROCESSED / "synth" / "demo_events.parquet"
EVENT_COLUMNS = {
    "event_id",
    "scene_id",
    "cause",
    "t_onset",
    "t_end",
    "track_ids",
    "region_wkt",
    "params_json",
}


@pytest.fixture(scope="module")
def synth() -> pd.DataFrame:
    return pd.read_parquet(need(points_path("synthetic")))


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return pd.read_parquet(need(SYNTH_EVENTS))


@pytest.fixture(scope="module")
def demo() -> pd.DataFrame:
    return pd.read_parquet(need(points_path("demo")))


@pytest.fixture(scope="module")
def demo_events() -> pd.DataFrame:
    return pd.read_parquet(need(DEMO_EVENTS))


# --- the generated dataset ---------------------------------------------------


def test_synthetic_validates(synth):
    schema.validate(synth, labeled=True)
    assert synth["scene_id"].nunique() >= 30, "too few scenes to split by scene"
    assert set(synth["domain"]) == {"aircraft", "vehicle"}


def test_every_cause_present_and_balanced(synth):
    share = synth["label_cause"].value_counts(normalize=True)
    assert set(share.index) == set(schema.CAUSES)
    assert share["plausible"] >= 0.5
    anomalous = synth.loc[synth["label_cause"] != "plausible", "label_cause"].value_counts(normalize=True)
    assert (anomalous >= 0.05).all(), anomalous.to_dict()


def test_some_scenes_are_fully_clean(synth):
    clean = synth.groupby("scene_id")["label_cause"].apply(lambda s: (s == "plausible").all())
    assert clean.mean() >= 0.10


def test_all_vehicle_classes_appear(synth):
    veh = set(synth.loc[synth["domain"] == "vehicle", "asset_class"])
    assert veh == {"baggage_tractor", "bus", "fuel_truck", "catering_truck", "sar_vehicle", "follow_me"}


def test_events_table(synth, events):
    assert EVENT_COLUMNS <= set(events.columns)
    assert events["event_id"].is_unique
    assert (events["t_end"] > events["t_onset"]).all()
    assert set(events["cause"]) <= set(schema.CAUSES) - {"plausible"}
    used = set(synth["label_event_id"].dropna())
    assert used <= set(events["event_id"])
    json.loads(events["params_json"].iloc[0])


def test_nominal_noise_has_scale_and_memory(synth):
    """Plausible vehicle fixes: error of a few meters, time-correlated (not white)."""
    veh = synth[(synth["domain"] == "vehicle") & (synth["label_cause"] == "plausible")]
    err = error_m(veh)
    rms = float(np.sqrt(np.mean(err**2)))
    assert 0.3 <= rms <= 15.0, f"plausible position error RMS {rms:.2f} m"

    clean_tracks = (
        synth[synth["domain"] == "vehicle"]
        .groupby("track_id")
        .filter(lambda g: (g["label_cause"] == "plausible").all() and len(g) >= 60)
    )
    rhos = []
    for _, g in list(clean_tracks.groupby("track_id"))[:200]:
        g = g.sort_values("t")
        x = (g["lat"] - g["label_true_lat"]).to_numpy()
        if np.std(x) > 0:
            rhos.append(np.corrcoef(x[:-1], x[1:])[0, 1])
    assert len(rhos) >= 20
    assert np.median(rhos) > 0.5, f"lag-1 autocorrelation {np.median(rhos):.2f}: noise looks white"


def test_behavioral_anomalies_keep_nominal_noise(synth):
    veh = synth[synth["domain"] == "vehicle"]
    rms = lambda d: float(np.sqrt(np.mean(error_m(d) ** 2)))  # noqa: E731
    plaus = rms(veh[veh["label_cause"] == "plausible"])
    behav = rms(veh[veh["label_cause"] == "behavioral_anomaly"])
    # same noise process; the factor allows for incursions happening mostly in open sky
    assert 0.3 * plaus <= behav <= 3.0 * plaus, (plaus, behav)


@pytest.mark.parametrize("cause", ["gnss_anomaly", "possible_spoofing"])
def test_position_faults_move_the_reported_position(synth, cause):
    plaus = error_m(synth[(synth["domain"] == "vehicle") & (synth["label_cause"] == "plausible")])
    base = max(float(np.sqrt(np.mean(plaus**2))), 1.0)
    err = error_m(synth[synth["label_cause"] == cause])
    assert np.quantile(err, 0.75) > 2.0 * base


def test_interference_is_an_area_event(events):
    ev = events[events["cause"] == "possible_interference"]
    assert len(ev) >= 5
    assert (ev["track_ids"].map(len) >= 3).all()
    assert ev["region_wkt"].notna().all()


def test_single_track_causes_hit_one_track(events):
    ev = events[events["cause"].isin(["technical_error", "gnss_anomaly", "degraded", "behavioral_anomaly"])]
    assert (ev["track_ids"].map(len) == 1).all()


# --- inject() on helper tracks (no data, no layers) -------------------------


def _two_tracks() -> pd.DataFrame:
    a = make_track(track_id="test:veh_001:0", n=200)
    b = make_track(track_id="test:veh_002:0", n=200, lat0=LAT0 + 0.01)
    return pd.concat([a, b], ignore_index=True)


def test_inject_is_pure_and_local():
    from divas_air.synth import inject

    pts = _two_tracks()
    before = pts.copy(deep=True)
    onset = T0 + 60.0
    out = inject(pts, "gnss_anomaly", onset_t=onset, duration_s=60.0, track_ids=["test:veh_001:0"], seed=1)

    pd.testing.assert_frame_equal(pts, before)  # input untouched
    schema.validate(out, labeled=True)

    a_in = pts[pts["track_id"] == "test:veh_001:0"].sort_values("seq")
    a = out[out["track_id"] == "test:veh_001:0"].sort_values("seq")
    b = out[out["track_id"] == "test:veh_002:0"].sort_values("seq")
    assert len(a) == len(a_in)

    pre = a[a["t"] < onset]
    assert (pre["label_cause"] == "plausible").all()
    np.testing.assert_allclose(pre["lat"], a_in.loc[a_in["t"] < onset, "lat"])

    during = a[(a["t"] >= onset) & (a["t"] < onset + 60.0)]
    assert (during["label_cause"] == "gnss_anomaly").mean() > 0.9
    assert (during["label_onset_t"] == onset).all()
    assert during["label_event_id"].notna().all()
    assert error_m(during).max() > 5.0

    np.testing.assert_allclose(a["label_true_lat"], a_in["lat"])  # truth = the input path
    assert (b["label_cause"] == "plausible").all()
    np.testing.assert_allclose(b["lat"], pts.loc[pts["track_id"] == "test:veh_002:0", "lat"])


def test_inject_is_deterministic():
    from divas_air.synth import inject

    pts = _two_tracks()
    kw = dict(onset_t=T0 + 60.0, duration_s=60.0, track_ids=["test:veh_001:0"], seed=3)
    pd.testing.assert_frame_equal(
        inject(pts, "possible_spoofing", **kw), inject(pts, "possible_spoofing", **kw)
    )


def test_spoofing_keeps_integrity_indicators():
    from divas_air.synth import inject

    pts = _two_tracks()
    onset = T0 + 60.0
    out = inject(
        pts, "possible_spoofing", onset_t=onset, duration_s=100.0, track_ids=["test:veh_001:0"], seed=2
    )
    a = out[(out["track_id"] == "test:veh_001:0") & (out["t"] >= onset)]
    assert a["nacp"].median() >= 10 - 1e-9, "spoofing must not lower NACp"
    assert error_m(a).max() > 20.0


def test_technical_error_keeps_nacp():
    from divas_air.synth import inject

    pts = _two_tracks()
    out = inject(
        pts, "technical_error", onset_t=T0 + 60.0, duration_s=60.0, track_ids=["test:veh_001:0"], seed=4
    )
    schema.validate(out, labeled=True)
    a = out[(out["track_id"] == "test:veh_001:0") & (out["t"] >= T0 + 60.0)]
    assert (a["label_cause"] == "technical_error").any()
    assert a["nacp"].dropna().min() >= 10 - 1e-9


def test_inject_region_hits_every_track_inside():
    from shapely.geometry import Point

    from divas_air.synth import inject

    inside = [make_track(track_id=f"test:veh_{i:03d}:0", n=200, lat0=LAT0 + 0.001 * i) for i in range(3)]
    far = make_track(track_id="test:veh_900:0", n=200, lat0=LAT0 + 0.5)
    pts = pd.concat(inside + [far], ignore_index=True)
    onset = T0 + 60.0
    out = inject(
        pts,
        "possible_interference",
        onset_t=onset,
        duration_s=90.0,
        region=Point(LON0, LAT0).buffer(0.05),
        seed=5,
    )
    schema.validate(out, labeled=True)

    for i in range(3):
        g = out[out["track_id"] == f"test:veh_{i:03d}:0"]
        ev = g[(g["t"] >= onset) & (g["t"] < onset + 90.0)]
        assert (ev["label_cause"] == "possible_interference").mean() > 0.5
        assert ev["nacp"].median() <= g.loc[g["t"] < onset, "nacp"].median() - 1
    g = out[out["track_id"] == "test:veh_900:0"]
    assert (g["label_cause"] == "plausible").all()
    assert out.loc[out["label_event_id"].notna(), "label_event_id"].nunique() == 1


# --- the scripted demo scene -------------------------------------------------


def test_demo_scene(demo, demo_events):
    schema.validate(demo, labeled=True)
    assert demo["scene_id"].nunique() == 1
    span = demo["t"].max() - demo["t"].min()
    assert 500 <= span <= 700

    ev = demo_events.set_index("event_id")
    assert set(ev.index) == {"ev_phantom", "ev_real", "ev_sector"}
    assert ev.loc["ev_phantom", "cause"] == "technical_error"
    assert ev.loc["ev_real", "cause"] == "behavioral_anomaly"
    assert ev.loc["ev_sector", "cause"] == "possible_interference"

    cls = demo.groupby("track_id")["asset_class"].first()
    assert len(ev.loc["ev_phantom", "track_ids"]) == 1
    assert len(ev.loc["ev_real", "track_ids"]) == 1
    assert cls[ev.loc["ev_phantom", "track_ids"][0]] == "baggage_tractor"
    assert cls[ev.loc["ev_real", "track_ids"][0]] == "fuel_truck"
    assert len(ev.loc["ev_sector", "track_ids"]) >= 5

    order = ev.sort_values("t_onset")
    assert list(order.index) == ["ev_phantom", "ev_real", "ev_sector"]
    gaps = order["t_onset"].to_numpy()[1:] - order["t_end"].to_numpy()[:-1]
    assert (gaps >= 90.0).all(), "events need 90 s of clean time between them"
    assert order["t_onset"].iloc[0] - demo["t"].min() >= 60.0, "start with a calm minute"


def test_generate_scene_is_deterministic_and_clean_on_request():
    from divas_air.synth import generate_scene

    need(config.LAYERS)  # the scene is drawn on the real route graph

    p1, e1 = generate_scene(7, duration_s=120.0, n_vehicles=5, n_aircraft=1)
    p2, e2 = generate_scene(7, duration_s=120.0, n_vehicles=5, n_aircraft=1)
    pd.testing.assert_frame_equal(p1, p2)
    schema.validate(p1, labeled=True)
    assert p1["scene_id"].nunique() == 1

    clean, ev = generate_scene(8, duration_s=120.0, n_vehicles=5, n_aircraft=1, events=[])
    assert (clean["label_cause"] == "plausible").all()
    assert len(ev) == 0
