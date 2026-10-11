"""ADR per-sample detectors (divas_air.adr) on hand-made tracks."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from divas_air import config
from divas_air.adr import behaviour, score, signal
from divas_air.adr.kin import kinematics
from divas_air.geo import to_metric
from tests.helpers import LAT0, LON0, T0, make_track, offset, renumber, shift_m


def _adr_style(df: pd.DataFrame) -> pd.DataFrame:
    """ADR derives speed and heading from consecutive positions: do the same."""
    df = df.sort_values(["track_id", "t"]).reset_index(drop=True)
    k = kinematics(df)
    dx, dy = np.r_[0, np.diff(k.x)], np.r_[0, np.diff(k.y)]
    dt = np.r_[1.0, np.diff(k.t)]
    first = np.r_[True, df["track_id"].to_numpy()[1:] != df["track_id"].to_numpy()[:-1]]
    gs = np.where(first, np.nan, np.hypot(dx, dy) / dt)
    hdg = np.where(first, np.nan, np.degrees(np.arctan2(dx, dy)) % 360)
    df["gs_mps"] = pd.Series(gs).bfill().to_numpy()
    df["heading_deg"] = pd.Series(hdg).bfill().to_numpy()
    return df


def _noisy(
    df: pd.DataFrame, sigma: float = 0.5, seed: int = 0, rows=None
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = df.copy()
    idx = np.arange(len(df)) if rows is None else np.asarray(rows)
    lat, lon = offset(
        out.loc[idx, "lat"].to_numpy(),
        out.loc[idx, "lon"].to_numpy(),
        north=rng.normal(0, sigma, len(idx)),
        east=rng.normal(0, sigma, len(idx)),
    )
    out.loc[idx, "lat"], out.loc[idx, "lon"] = lat, lon
    return out


def _flagged(d: pd.DataFrame, lab: str) -> list[int]:
    return np.flatnonzero(d[lab].to_numpy()).tolist()


# --- signal ------------------------------------------------------------------------


def test_clean_track_raises_nothing():
    d = signal.detect(_adr_style(_noisy(make_track(n=200, alt_m=2.0))))
    assert (d["signal_label"] == "").all()


def test_held_jump_labels_the_offset_samples():
    df = shift_m(
        make_track(n=120), (np.arange(120) >= 50) & (np.arange(120) < 60), north=40
    )
    d = signal.detect(_adr_style(_noisy(df)))
    assert _flagged(d, "position_jump") == list(range(50, 60))
    assert d.loc[50, "step_m"] > 30


def test_single_outlier_is_one_sample_jump():
    df = shift_m(make_track(n=120), np.arange(120) == 70, east=-80)
    d = signal.detect(_adr_style(_noisy(df)))
    assert _flagged(d, "position_jump") == [70]


def test_frozen_position_with_speed_reported_or_derived():
    df = make_track(n=120, speed_mps=6.0)
    df.loc[50:69, ["lat", "lon"]] = df.loc[49, ["lat", "lon"]].to_numpy()
    d = signal.detect(df)  # reported speed keeps saying 6 m/s
    assert _flagged(d, "frozen_position") == list(range(50, 70))
    d = signal.detect(_adr_style(df))  # ADR style: speed 0 while frozen, catch-up after
    assert _flagged(d, "frozen_position") == list(range(50, 70))
    assert not d["position_jump"].any()  # the catch-up step belongs to the freeze


def test_parked_asset_with_identical_fixes_is_not_frozen():
    df = make_track(n=60, speed_mps=0.0)
    assert not signal.detect(_adr_style(df))["frozen_position"].any()


def test_fix_loss_labels_samples_around_the_gap():
    df = make_track(n=150)
    df = renumber(df[(df["seq"] < 50) | (df["seq"] >= 90)].reset_index(drop=True))
    d = signal.detect(_adr_style(_noisy(df)))
    assert _flagged(d, "fix_loss") == [49, 50]
    assert d.loc[50, "gap_s"] == 41


def test_multipath_scatter_without_step():
    df = _noisy(make_track(n=200), sigma=0.5)
    df = _noisy(df, sigma=8.0, seed=1, rows=np.arange(80, 130))
    d = signal.detect(_adr_style(df))
    mp = d["multipath_noise"].to_numpy()
    assert mp[85:125].mean() > 0.9
    assert not mp[:70].any() and not mp[140:].any()
    assert not d["position_jump"].to_numpy()[85:125].any()


def test_implausible_speed_bound_and_contradiction():
    fast = make_track(n=60, speed_mps=30.0, asset_class="baggage_tractor")
    assert signal.detect(fast)["implausible_speed"].sum() > 40
    ok = make_track(n=60, speed_mps=6.0, asset_class="baggage_tractor")
    assert not signal.detect(ok)["implausible_speed"].any()
    lie = ok.copy()
    lie.loc[20:39, "gs_mps"] = 20.0  # reported speed contradicts a smooth path
    assert _flagged(signal.detect(lie), "implausible_speed") == list(range(20, 40))


def test_heading_incoherent_is_folded():
    df = make_track(n=60, speed_mps=6.0, course_deg=90.0)
    side = df.copy()
    side.loc[20:39, "heading_deg"] = 0.0  # 90 deg off the travel direction
    assert _flagged(signal.detect(side), "heading_incoherent") == list(range(20, 40))
    rev = df.copy()
    rev["heading_deg"] = 270.0  # reversing: nose opposite to travel
    assert not signal.detect(rev)["heading_incoherent"].any()


def test_altitude_spike_against_track_median():
    df = make_track(n=60, alt_m=2.0)
    df.loc[30, "alt_geom_m"] = 250.0
    df.loc[31, "alt_geom_m"] = 6.0
    assert _flagged(signal.detect(df), "altitude_spike") == [30]


# --- behaviour ---------------------------------------------------------------------


def _zones(*specs) -> gpd.GeoDataFrame:
    """specs: (zone_id, zone_class, allowed_groups, limit_kmh, (s, w, n, e) in m around LAT0/LON0)."""
    x0, y0 = to_metric([LON0], [LAT0])
    rows = []
    for zid, cls, groups, kmh, (s, w, n, e) in specs:
        rows.append(
            {
                "zone_id": zid,
                "adr_zone_class": cls,
                "allowed_groups": groups,
                "speed_limit_mps": np.nan if kmh is None else kmh / 3.6,
                "geometry": box(x0[0] + w, y0[0] + s, x0[0] + e, y0[0] + n),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.CRS_METRIC)


def _beh(df, zones, groups, rwy=None):
    df = df.sort_values(["track_id", "t"], kind="stable").reset_index(drop=True)
    sig = signal.detect(df)
    grp = df["typecode_raw"].map(groups).fillna("").to_numpy(dtype=object)
    return df, behaviour.detect(df, sig, zones, grp, kinematics(df).seg, rwy)


ROAD = (
    "ROAD",
    "service_road_corridor",
    "handling,ops_authorized,sar",
    30,
    (-5000, -5000, 5000, 5000),
)
TWY = (
    "TWY-A",
    "taxi_corridor",
    "aircraft,ops_authorized,sar",
    50,
    (-50, -50, 50, 2000),
)
APRON = (
    "APR-1",
    "apron",
    "aircraft,handling,ops_authorized,sar",
    25,
    (-50, -50, 50, 2000),
)
GROUPS = {
    "baggage_tug": "handling",
    "pushback_tug": "handling",
    "sar_fire": "sar",
    "aircraft_taxi": "aircraft",
    "follow_me": "ops_authorized",
}


def _track(tid, cls, **kw):
    df = make_track(track_id=f"t:{tid}:0", **kw)
    df["typecode_raw"] = cls
    return df


def test_overspeed_against_posted_limit_unless_bulk_exceeds_it():
    kw = {"asset_class": "sar_vehicle"}
    slow = _track("slow", "sar_fire", n=1500, speed_mps=3.0, lat0=LAT0 + 0.01, **kw)
    fast = _track("fast", "sar_fire", n=20, speed_mps=15.0, **kw)
    df, b = _beh(pd.concat([slow, fast]), _zones(ROAD), GROUPS)
    hit = df.loc[b["overspeed"], "track_id"].unique().tolist()
    assert hit == ["t:fast:0"] and b["overspeed"].sum() >= 14
    # every asset above the limit: the limit is not the norm here, nothing is flagged
    df, b = _beh(fast, _zones(ROAD), GROUPS)
    assert not b["overspeed"].any()


def test_runway_incursion_from_group_and_runway_ref():
    z = _zones(
        ROAD,
        (
            "RWY-CRIT",
            "runway_critical",
            "aircraft,ops_authorized,sar",
            None,
            (-50, -50, 50, 2000),
        ),
    )
    for cls, expect in (("baggage_tug", True), ("sar_fire", False)):
        df = _track("a", cls, n=60, speed_mps=5.0)
        rwy = pd.Series(np.where(np.arange(60) >= 20, "07/25", None))
        _, b = _beh(df, z, GROUPS, rwy)
        assert b["runway_incursion"].any() == expect
        if expect:
            assert np.flatnonzero(b["runway_incursion"]).tolist() == list(range(20, 60))


def test_unauthorized_zone_needs_every_containing_zone_to_forbid():
    df = _track("a", "baggage_tug", n=60, speed_mps=5.0)
    _, b = _beh(df, _zones(TWY), GROUPS)
    assert b["unauthorized_zone"].all()
    _, b = _beh(df, _zones(TWY, ROAD), GROUPS)  # crossing on a service road
    assert not b["unauthorized_zone"].any()
    tug = _track("b", "pushback_tug", n=60, speed_mps=2.0)
    _, b = _beh(tug, _zones(TWY), GROUPS)  # towing aircraft is its job
    assert not b["unauthorized_zone"].any()


def test_position_labels_suppress_zone_labels():
    df = _track("a", "baggage_tug", n=120, speed_mps=5.0, lat0=LAT0 + 0.01)
    on = (np.arange(120) >= 60) & (np.arange(120) < 70)
    df = shift_m(df, on, north=-0.01 * 111_000)  # a phantom jump into the taxiway
    _, b = _beh(df, _zones(TWY), GROUPS)
    assert b["raw_unauthorized_zone"].to_numpy()[60:70].all()
    assert not b["unauthorized_zone"].any()


def _stop_track(cls, stop_at=(100, 500)):
    df = _track("s", cls, n=700, speed_mps=3.0)
    t = df["t"].to_numpy() - T0
    a, b = stop_at
    dist = np.where(t < a, 3.0 * t, np.where(t < b, 3.0 * a, 3.0 * (t - (b - a))))
    df["lat"], df["lon"] = offset(
        np.full(len(t), LAT0), np.full(len(t), LON0), east=dist
    )
    return _adr_style(_noisy(df, sigma=0.05))


def test_unexpected_stop_outside_parking_only():
    _, b = _beh(_stop_track("sar_fire"), _zones(TWY, ROAD), GROUPS)
    st = b["unexpected_stop"].to_numpy()
    assert st[200:400].all() and not st[:50].any() and not st[600:].any()
    _, b = _beh(_stop_track("sar_fire"), _zones(APRON, ROAD), GROUPS)
    assert not b["unexpected_stop"].any()


def test_aircraft_proximity_same_second():
    ac = _track("ac", "aircraft_taxi", n=60, speed_mps=5.0, domain="aircraft")
    veh = _track("v", "baggage_tug", n=60, speed_mps=5.0)
    veh["lat"], veh["lon"] = offset(
        veh["lat"].to_numpy(), veh["lon"].to_numpy(), north=8.0
    )
    _, b = _beh(pd.concat([ac, veh]), _zones(ROAD), GROUPS)
    assert b["aircraft_proximity"].sum() >= 50  # edges lack a 5 s speed
    veh["typecode_raw"] = "follow_me"
    _, b = _beh(pd.concat([ac, veh]), _zones(ROAD), GROUPS)
    assert not b["aircraft_proximity"].any()


# --- per-sample trust ----------------------------------------------------------------


def test_trust_is_the_window_ending_at_or_after_the_sample():
    p = pd.DataFrame({"track_id": ["a"] * 4 + ["b"], "t": [0.0, 5.0, 6.0, 12.0, 1.0]})
    v = pd.DataFrame(
        {
            "track_id": ["a", "a", "b"],
            "t_end": [5.0, 10.0, 0.0],
            "integrity": [90.0, 40.0, 70.0],
        }
    )
    tr = score.sample_trust(p, v)
    assert tr["integrity"].tolist() == [90.0, 90.0, 40.0, 40.0, 70.0]
