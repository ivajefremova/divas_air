"""Module 3 acceptance: about 0 % over-limit on clean real traffic.

Spec: specs/03_features.md. Frozen: do not edit to make it pass.
The helper-track tests need no data and no map layers (layers=None).
"""

import numpy as np
import pandas as pd
import pytest

from divas_air import config, params, registry, schema
from tests.helpers import T0, features_path, make_track, need, renumber, shift_m

KEYS = ["track_id", "t_end"]
ENV = registry.ENVELOPE_RATIO_COLUMNS
MAP_FEATURES = registry.columns("spatial", "contextual")


@pytest.fixture(scope="module")
def cf():
    from divas_air.features import compute_features

    return lambda pts: compute_features(pts, layers=None).sort_values(KEYS).reset_index(drop=True)


def full_windows(f: pd.DataFrame) -> pd.DataFrame:
    return f[f["tmp_n_points"] >= 25]


# --- shape ---------------------------------------------------------------------


def test_output_columns_are_exactly_the_registry(cf):
    f = cf(make_track())
    expected = set(KEYS) | {"t_start"} | set(registry.FEATURE_COLUMNS) | set(registry.AUX_COLUMNS)
    assert set(f.columns) == expected
    schema.assert_no_leakage(registry.FEATURE_COLUMNS)
    assert f[MAP_FEATURES].isna().all().all(), "layers=None must leave map features NaN"

    fl = cf(make_track(labeled=True))
    assert set(fl.columns) == expected | set(schema.WINDOW_LABEL_COLUMNS)


def test_window_grid(cf):
    f = cf(make_track(n=120, dt=1.0))  # fixes at T0 .. T0+119
    assert not f.duplicated(KEYS).any()
    assert (f["t_end"] % config.STRIDE_S == 0).all()
    assert f["t_end"].min() == T0
    assert f["t_end"].max() == T0 + 120
    assert np.allclose(np.diff(f["t_end"]), config.STRIDE_S)
    assert np.allclose(f["t_start"], f["t_end"] - config.WINDOW_S)


# --- clean motion --------------------------------------------------------------


def test_clean_vehicle_track_scores_clean(cf):
    f = full_windows(cf(make_track(asset_class="bus", speed_mps=5.0)))
    assert len(f) >= 10
    assert f["kin_speed_resid_max"].max() < 0.5
    assert f["kin_pos_jitter_m"].max() < 0.5
    assert np.allclose(f["kin_speed_ratio_max"], 5.0 / 8.5, atol=0.05)
    assert np.nanmax(f[ENV].to_numpy()) < 1.0
    assert f["tmp_gap_max_s"].max() <= 1.5
    assert (f["tmp_dup_count"] == 0).all() and (f["tmp_nonmono_count"] == 0).all()
    assert (f["tmp_frozen_run_s"] == 0).all()
    assert (f["sig_nacp_median"] == 10).all()
    assert (f["aux_asset_class"] == "bus").all() and (f["aux_domain"] == "vehicle").all()
    assert np.allclose(f["aux_gs_mps"], 5.0)
    assert np.allclose(f["aux_class_max_speed_mps"], 8.5)


def test_airborne_aircraft_uses_the_air_limit(cf):
    pts = make_track(
        track_id="test:4ca001:0",
        domain="aircraft",
        asset_class="narrowbody",
        speed_mps=80.0,
        alt_m=500.0,
        dt=2.5,
        n=80,
    )  # 12 fixes per window
    f = cf(pts)
    f = f[f["tmp_n_points"] >= 10]
    assert len(f) >= 5
    assert np.allclose(f["kin_speed_ratio_max"], 80.0 / 320.0, atol=0.02)
    assert np.allclose(f["aux_class_max_speed_mps"], 320.0)
    assert f["aux_airborne"].astype(bool).all()
    assert f["kin_speed_resid_max"].max() < 1.0


def test_helicopters_skip_envelope_checks(cf):
    pts = make_track(
        track_id="test:heli01:0", domain="aircraft", asset_class="helicopter", speed_mps=20.0, alt_m=300.0
    )
    f = full_windows(cf(pts))
    assert f[ENV].isna().all().all()
    assert f["kin_speed_resid_max"].notna().all(), "consistency checks still apply to helicopters"


# --- the 5 s rule ---------------------------------------------------------------


def test_rates_use_a_five_second_base(cf):
    """Two fixes 0.2 s apart and 5 m off: point-to-point speed would be 25 m/s."""
    a = make_track(asset_class="bus", speed_mps=5.0)
    extra = a.iloc[[60]].copy()
    extra["t"] += 0.2
    extra = shift_m(extra, [True], north=5.0)
    pts = renumber(pd.concat([a.iloc[:61], extra, a.iloc[61:]]))
    schema.validate(pts)
    f = cf(pts)
    assert np.nanmax(f["kin_speed_ratio_max"]) < 1.2
    assert np.nanmax(f["kin_accel_ratio_max"]) < 1.0
    assert np.nanmax(f["kin_speed_resid_max"]) < 3.0


# --- anomalies show up in the right feature --------------------------------------


def test_position_jump(cf):
    a = make_track(asset_class="bus", speed_mps=5.0)
    pts = shift_m(a, a["t"] >= T0 + 60, north=300.0)  # 300 m jump, held
    f = cf(pts)
    before = f[f["t_end"] <= T0 + 55]
    hit = f[(f["t_end"] >= T0 + 60) & (f["t_end"] <= T0 + 70)]
    assert before["kin_speed_resid_max"].max() < 0.5
    assert hit["kin_speed_resid_max"].max() > 30.0
    assert hit["kin_speed_ratio_max"].max() > params.LIMIT_MARGIN
    worst = hit.loc[hit["kin_speed_resid_max"].idxmax()]
    assert worst["aux_speed_implied_mps"] > 30.0
    assert abs(worst["aux_speed_reported_mps"] - 5.0) < 0.5


def test_frozen_position(cf):
    a = make_track(asset_class="bus", speed_mps=5.0)
    pts = a.copy()
    frozen = (pts["t"] >= T0 + 60) & (pts["t"] <= T0 + 80)
    pts.loc[frozen, "lat"] = pts.loc[pts["t"] == T0 + 60, "lat"].iloc[0]
    pts.loc[frozen, "lon"] = pts.loc[pts["t"] == T0 + 60, "lon"].iloc[0]
    f = cf(pts)
    hit = f[(f["t_end"] >= T0 + 80) & (f["t_end"] <= T0 + 85)]
    assert hit["tmp_frozen_run_s"].max() >= 15.0
    assert hit["tmp_frozen_frac"].max() > 0.4
    assert (f.loc[f["t_end"] <= T0 + 55, "tmp_frozen_run_s"] == 0).all()


def test_gap_and_empty_windows(cf):
    a = make_track(asset_class="bus", speed_mps=5.0, n=200)
    pts = renumber(a[(a["t"] <= T0 + 60) | (a["t"] >= T0 + 110)])  # 50 s of silence
    f = cf(pts)
    assert set(np.arange(T0 + 65, T0 + 110, 5)) <= set(f["t_end"]), "windows inside a gap must be emitted"
    assert f.loc[f["t_end"] == T0 + 75, "tmp_gap_max_s"].iloc[0] >= 15.0 - 1e-6
    assert f.loc[f["t_end"] == T0 + 75, "tmp_staleness_s"].iloc[0] >= 15.0 - 1e-6
    empty = f[f["t_end"] == T0 + 100]
    assert empty["tmp_n_points"].iloc[0] == 0
    assert empty["tmp_gap_max_s"].iloc[0] >= 40.0 - 1e-6
    assert f.loc[f["t_end"] == T0 + 110, "tmp_gap_max_s"].iloc[0] >= 50.0 - 1e-6


def test_out_of_order_and_duplicate_timestamps(cf):
    a = make_track(asset_class="bus", speed_mps=5.0)
    late = a.copy()
    late.loc[late["seq"] == 70, "t"] = T0 + 65.5  # arrives after seq 69 but is older
    f = cf(late)
    assert f.loc[f["t_end"] <= T0 + 60, "tmp_nonmono_count"].max() == 0
    assert f["tmp_nonmono_count"].max() >= 1

    dup = a.copy()
    dup.loc[dup["seq"] == 71, "t"] = T0 + 70.0  # same time as seq 70
    f = cf(dup)
    assert f.loc[f["t_end"] <= T0 + 60, "tmp_dup_count"].max() == 0
    assert f["tmp_dup_count"].max() >= 1


def _degraded_values():
    """A (nacp, nic) pair the repo's own rule calls degraded. The rule comes from
    the GPSJam reproduction, so the test asks it instead of assuming a threshold."""
    from divas_air.degradation import is_degraded_reading

    probe = make_track(
        domain="aircraft",
        asset_class="narrowbody",
        track_id="test:4ca002:0",
        speed_mps=80.0,
        alt_m=500.0,
        n=5,
    )
    assert not bool(is_degraded_reading(probe).any()), "NACp 10 / NIC 8 must not count as degraded"
    for nacp, nic in ((0, 0), (1, 1), (2, 2), (4, 4), (5, 5), (6, 6), (7, 6)):
        if bool(is_degraded_reading(probe.assign(nacp=float(nacp), nic=float(nic))).all()):
            return float(nacp), float(nic)
    pytest.fail("is_degraded_reading flags no low NACp/NIC reading")


def test_majority_rule_for_degraded_readings(cf):
    """A minority of bad readings does not make a window degraded."""
    bad_nacp, bad_nic = _degraded_values()
    a = make_track(
        domain="aircraft", asset_class="narrowbody", track_id="test:4ca002:0", speed_mps=80.0, alt_m=500.0
    )

    few = a.copy()
    few.loc[few["t"].between(T0 + 60, T0 + 64), ["nacp", "nic"]] = [bad_nacp, bad_nic]  # 5 of 30 fixes
    row = cf(few)[lambda d: d["t_end"] == T0 + 75].iloc[0]
    assert 0.1 < row["sig_degraded_frac"] < 0.3
    assert row["sig_degraded_majority"] == 0

    many = a.copy()
    many.loc[many["t"] >= T0 + 50, ["nacp", "nic"]] = [bad_nacp, bad_nic]
    row = cf(many)[lambda d: d["t_end"] == T0 + 90].iloc[0]
    assert row["sig_degraded_frac"] == 1.0
    assert row["sig_degraded_majority"] == 1
    assert row["sig_nacp_drop"] >= (10.0 - bad_nacp) - 1e-9


# --- causality ---------------------------------------------------------------------


def test_features_are_causal(cf):
    a = make_track(asset_class="bus", speed_mps=5.0, n=200)
    pts = shift_m(a, a["t"] >= T0 + 150, north=300.0)  # the future contains a jump
    full = cf(pts)
    cut = cf(pts[pts["t"] <= T0 + 100])
    cols = KEYS + registry.FEATURE_COLUMNS + list(registry.AUX_COLUMNS)
    left = full.loc[full["t_end"] <= T0 + 100, cols].reset_index(drop=True)
    right = cut.loc[cut["t_end"] <= T0 + 100, cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right, check_dtype=False, rtol=1e-9, atol=1e-9)


# --- window labels -------------------------------------------------------------------


def test_window_labels_follow_the_positive_fraction_rule(cf):
    a = make_track(asset_class="bus", labeled=True)
    late = a["t"] >= T0 + 60
    a.loc[late, "label_cause"] = "technical_error"
    a.loc[late, "label_onset_t"] = T0 + 60
    a.loc[late, "label_event_id"] = "ev1"
    schema.validate(a, labeled=True)
    f = cf(a).set_index("t_end")

    assert f.loc[T0 + 55, "label_frac"] == 0
    assert f.loc[T0 + 55, "label_cause"] == "plausible" and not f.loc[T0 + 55, "label_transition"]
    # T0+65: 6 of 30 fixes anomalous -> transition, still labeled plausible
    assert f.loc[T0 + 65, "label_cause"] == "plausible" and f.loc[T0 + 65, "label_transition"]
    # T0+70: 11 of 30 -> anomalous
    assert f.loc[T0 + 70, "label_cause"] == "technical_error" and not f.loc[T0 + 70, "label_transition"]
    assert f.loc[T0 + 110, "label_frac"] == 1.0
    assert (f["scene_id"] == "scene_test").all()
    assert f.loc[T0 + 70, "label_event_id"] == "ev1"


# --- real data ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fco() -> pd.DataFrame:
    return pd.read_parquet(need(features_path("fco")))


def test_fco_feature_table(fco):
    expected = set(KEYS) | {"t_start"} | set(registry.FEATURE_COLUMNS) | set(registry.AUX_COLUMNS)
    assert set(fco.columns) == expected
    assert not fco.duplicated(KEYS).any()
    scored = fco[fco["tmp_n_points"] >= params.MIN_POINTS]
    for spec in registry.REGISTRY.values():
        if spec.priority == "P0" and spec.group != "fleet" and spec.applies_to in ("all", "aircraft"):
            assert scored[spec.name].notna().mean() > 0.5, f"P0 feature {spec.name} is mostly NaN on fco"


def test_over_limit_share_on_clean_real_traffic(fco):
    """The module's headline: about 0 %. Point-to-point rates gave 0.2 %."""
    scored = fco[fco["tmp_n_points"] >= params.MIN_POINTS]
    over = (scored[ENV] > params.LIMIT_MARGIN).any(axis=1)
    assert over.mean() < 0.001, f"over-limit share {over.mean():.4%}"


def test_threshold_file():
    th = pd.read_csv(need(config.REFERENCE / "dimension_thresholds.csv"))
    assert {"name", "domain", "tau", "scale"} <= set(th.columns)
    scored = [s for s in registry.REGISTRY.values() if s.scored]
    have = set(zip(th["name"], th["domain"], strict=True))
    for s in scored:
        for domain in ("aircraft", "vehicle"):
            assert (s.name, domain) in have, f"no threshold for {s.name} / {domain}"
    th = th.set_index(["name", "domain"])
    for s in scored:
        for domain in ("aircraft", "vehicle"):
            tau = th.loc[(s.name, domain), "tau"]
            if s.tau_source == "calibrated":
                assert tau >= s.tau - 1e-9, f"{s.name}: fitted tau below the registry floor"
            else:
                assert abs(tau - s.tau) < 1e-9, (
                    f"{s.name}: {s.tau_source} tau must stay at the registry value"
                )
