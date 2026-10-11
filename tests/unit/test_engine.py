"""Online engine on helper tracks with a stand-in model bundle (specs/06_api.md req. 1-5)."""

from typing import ClassVar

import numpy as np
import pandas as pd

from divas_air import params, registry
from divas_air.engine import TrustEngine
from divas_air.features import compute_features
from divas_air.models import P_COLUMNS
from divas_air.pipeline import verdicts
from divas_air.verdict import assemble
from tests.helpers import LAT0, LON0, T0, make_track, offset


class StubBundle:
    """Pass 1 is unsound where NACp is low; pass 2 falls with the max gap; causes constant."""

    boosters: ClassVar[dict] = {
        "integrity_p1": None,
        "integrity_p2": None,
        "cause": None,
    }

    def p_unsound(self, features, pass_=2, calibrated=True):
        if pass_ == 1:
            return np.where(features["sig_nacp_median"].fillna(10) < 8, 0.9, 0.01)
        gap = features["tmp_gap_max_s"].fillna(30.0).to_numpy()
        return np.clip(gap / 20.0, 0.01, 0.99)

    def cause_probs(self, features):
        p = np.zeros((len(features), len(P_COLUMNS)))
        p[:, 0], p[:, 2] = 0.7, 0.3
        return pd.DataFrame(p, columns=P_COLUMNS, index=features.index)

    def contributions(self, features, pass_=2):
        cols = registry.MODEL_INPUTS_INTEGRITY_P2
        return pd.DataFrame(0.0, index=features.index, columns=cols)


def scene() -> pd.DataFrame:
    """Three parked tracks degraded together, one clean, one moving with a 20 s gap."""
    frames = []
    for i in range(4):
        lat, lon = offset(LAT0, LON0, north=3.0 * i)
        g = make_track(
            track_id=f"test:veh_{i:03d}:0",
            speed_mps=0.0,
            n=120,
            lat0=float(lat),
            lon0=float(lon),
        )
        if i < 3:
            g.loc[g["t"] >= T0 + 40, "nacp"] = 5.0
        frames.append(g)
    m = make_track(track_id="test:veh_mov:0", n=120, lat0=LAT0 + 0.003)
    frames.append(m[(m["t"] < T0 + 50) | (m["t"] > T0 + 70)])
    return pd.concat(frames, ignore_index=True)


def replay(
    engine: TrustEngine, pts: pd.DataFrame, t0: float, t1: float
) -> pd.DataFrame:
    rows, prev = [], -np.inf
    for now in np.arange(t0, t1 + 1e-6, 5.0):
        engine.ingest(pts[(pts["t"] > prev) & (pts["t"] <= now)])
        prev = now
        for v in engine.step(float(now)):
            rows.append(
                (
                    v.track_id,
                    v.t,
                    v.integrity_raw,
                    v.integrity,
                    v.trust_state,
                    v.area_alert_id,
                )
            )
    return pd.DataFrame(
        rows, columns=["track_id", "t_end", "ir", "integ", "state", "alert"]
    )


def test_engine_matches_the_batch_pipeline():
    pts = scene()
    batch, _ = verdicts(compute_features(pts), StubBundle(), None)
    online = replay(TrustEngine(None, StubBundle()), pts, T0, T0 + 120)
    m = online.merge(batch, on=["track_id", "t_end"])
    assert len(m) == len(batch)
    assert np.allclose(m["ir"], m["integrity_raw"])
    assert np.allclose(m["integ"], m["integrity"])
    assert (m["state"] == m["trust_state"]).all()
    assert (m["alert"].fillna("") == m["area_alert_id"].fillna("")).all()
    assert m["alert"].notna().any()
    # the gap is a signal: the moving track has a verdict at every grid time of its silence
    gap = online[
        (online["track_id"] == "test:veh_mov:0")
        & online["t_end"].between(T0 + 55, T0 + 70)
    ]
    assert len(gap) == 4


def test_single_fix_gets_a_low_confidence_verdict():
    eng = TrustEngine(None, StubBundle())
    eng.ingest(make_track(n=1, t0=T0 + 2))
    out = eng.step(T0 + 5)
    assert len(out) == 1 and out[0].confidence_level == "low"


def test_silent_track_is_dropped_after_the_gap_limit():
    eng = TrustEngine(None, StubBundle())
    eng.ingest(make_track(n=10))
    last = T0 + 9
    assert len(eng.step(T0 + 10)) == 1
    keep = np.ceil((last + params.TRACK_GAP_SPLIT_S) / 5) * 5 - 5
    assert len(eng.step(keep)) == 1
    assert eng.step(keep + 10) == []
    assert eng.history("test:veh_001:0") == []


def test_history_is_ordered_and_bounded():
    eng = TrustEngine(None, StubBundle())
    pts = make_track(n=400)
    replay(eng, pts, T0, T0 + 395)
    h = eng.history("test:veh_001:0", 60)
    assert [v.t for v in h] == sorted(v.t for v in h)
    assert len(h) == 13 and h[-1].t == T0 + 395
    assert len(eng.history("test:veh_001:0")) == params.HISTORY_S // 5 + 1


def test_features_until_extends_a_silent_track():
    t = make_track(n=12)  # last fix at T0 + 11
    f = compute_features(t, until=T0 + 30)
    assert f["t_end"].max() == T0 + 30
    later = pd.concat(
        [t, make_track(n=1, t0=T0 + 33).assign(seq=99)], ignore_index=True
    )
    ref = compute_features(later)
    a = f[f["t_end"] == T0 + 30].iloc[0]
    b = ref[ref["t_end"] == T0 + 30].iloc[0]
    for c in registry.FEATURE_COLUMNS:
        assert (np.isnan(a[c]) and np.isnan(b[c])) or np.isclose(a[c], b[c]), c


def test_assemble_continues_from_init():
    pts = scene()
    f = compute_features(pts)
    f = f.assign(area_alert_id=None)
    one = assemble(f, StubBundle())
    cut = T0 + 60
    first = assemble(f[f["t_end"] <= cut], StubBundle())
    last = first.sort_values("t_end").groupby("track_id").tail(1).set_index("track_id")
    init = last[["integrity", "trust_state", "normality_state"]]
    second = assemble(f[f["t_end"] > cut], StubBundle(), init=init)
    ref = one[one["t_end"] > cut].reset_index(drop=True)
    assert np.allclose(second["integrity"], ref["integrity"])
    assert (second["trust_state"] == ref["trust_state"]).all()
