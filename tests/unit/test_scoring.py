import numpy as np
import pandas as pd

from divas_air import registry
from divas_air.scoring import dimension_scores, normality_score, tau_of, violations
from divas_air.scoring.baseline import naive_score
from tests.helpers import make_track, renumber, shift_m


def _frame(n=1, domain="vehicle", **values):
    f = pd.DataFrame({c: np.full(n, np.nan) for c in registry.FEATURE_COLUMNS})
    f["aux_domain"] = domain
    for k, v in values.items():
        f[k] = v
    return f


def test_violation_uses_domain_tau():
    tau_air = tau_of("kin_speed_resid_max", "aircraft")
    tau_veh = tau_of("kin_speed_resid_max", "vehicle")
    f = _frame(2, kin_speed_resid_max=[tau_air, tau_air])
    f["aux_domain"] = ["aircraft", "vehicle"]
    v = violations(f)["kin_speed_resid_max"].to_numpy()
    assert v[0] == 0.0
    assert np.isclose(v[1], np.clip((tau_air - tau_veh) / 20.0, 0, 1))


def test_missing_columns_are_no_evidence():
    f = pd.DataFrame({"aux_domain": ["vehicle"], "kin_speed_ratio_max": [3.0]})
    d = dimension_scores(f)
    assert np.isclose(d["d_kinetic"].iloc[0], 0.0)
    assert np.allclose(d[["d_temporal", "d_spatial", "d_contextual"]], 100)


def test_unknown_domain_uses_registry_default():
    f = _frame(1, domain="other", kin_speed_resid_max=[20.0])
    assert np.isclose(violations(f)["kin_speed_resid_max"].iloc[0], (20 - 10) / 20)


def test_normality_ignores_kinetic():
    f = _frame(2, kin_speed_ratio_max=[9.0, 1.0], spa_in_building_frac=[0.0, 0.8])
    n = normality_score(dimension_scores(f))
    assert np.allclose(n, [100, 0])


def test_naive_baseline_flags_a_jump_and_not_a_clean_track():
    clean = make_track(n=60, dt=1.0, speed_mps=5.0)
    jumped = make_track(track_id="test:veh_002:0", n=60, dt=1.0, speed_mps=5.0)
    jumped = shift_m(jumped, jumped["seq"] == 30, north=800.0)
    b = naive_score(renumber(pd.concat([clean, jumped])))
    by = b.groupby("track_id")["baseline_score"].max()
    assert by["test:veh_001:0"] < 0.2
    assert by["test:veh_002:0"] == 1.0
    assert b["baseline_score"].between(0, 1).all()
    assert (b["t_end"] % 5 == 0).all()
