"""Batch pipeline on helper tracks with a stand-in model bundle (specs/05_fleet.md req. 15)."""

import numpy as np
import pandas as pd

from divas_air import registry, schema
from divas_air.features import compute_features
from divas_air.models import P_COLUMNS
from divas_air.pipeline import fleet_tables, verdicts
from tests.helpers import LAT0, LON0, T0, make_track, offset


class StubBundle:
    """Pass 1 is unsound exactly where NACp is low; pass 2 and causes are constant."""

    def p_unsound(self, features, pass_=2, calibrated=True):
        if pass_ == 1:
            return np.where(features["sig_nacp_median"].fillna(10) < 8, 0.9, 0.01)
        return np.full(len(features), 0.01)

    def cause_probs(self, features):
        p = np.zeros((len(features), len(P_COLUMNS)))
        p[:, 0] = 1.0
        return pd.DataFrame(p, columns=P_COLUMNS, index=features.index)

    def contributions(self, features, pass_=2):
        cols = registry.MODEL_INPUTS_INTEGRITY_P2
        return pd.DataFrame(0.0, index=features.index, columns=cols)


def parked(n_tracks: int, bad: set[int]) -> pd.DataFrame:
    frames = []
    for i in range(n_tracks):
        lat, lon = offset(LAT0, LON0, north=3.0 * i)
        g = make_track(
            track_id=f"test:veh_{i:03d}:0",
            speed_mps=0.0,
            n=90,
            dt=1.0,
            lat0=float(lat),
            lon0=float(lon),
        )
        if i in bad:
            g.loc[g["t"] >= T0 + 20, "nacp"] = 5.0
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def test_pipeline_groups_tracks_degraded_together():
    feats = compute_features(parked(4, {0, 1, 2}))
    out, ft = verdicts(feats, StubBundle(), None)
    assert len(out) == len(feats)
    assert (
        out[["track_id", "t_end"]].to_numpy() == feats[["track_id", "t_end"]].to_numpy()
    ).all()
    assert not out.duplicated(list(schema.WINDOW_KEYS)).any()
    assert ft.cells["flagged"].any()
    assert out["area_alert_id"].notna().any()
    assert out["area_alert_id"].dropna().nunique() == 1
    clean = ft.features[ft.features["track_id"] == "test:veh_003:0"]
    assert clean["flt_deg_count_loo"].max() == 3


def test_pipeline_single_fault_has_no_alert():
    feats = compute_features(parked(4, {0}))
    out, ft = verdicts(feats, StubBundle(), None)
    assert not ft.cells["flagged"].any()
    assert out["area_alert_id"].isna().all()
    own = ft.features[ft.features["track_id"] == "test:veh_000:0"]
    assert (own["flt_deg_count_loo"] == 0).all()


def test_scenes_do_not_see_each_other():
    a = compute_features(parked(4, {0, 1, 2})).assign(scene_id="s1")
    b = a.assign(scene_id="s2", track_id=a["track_id"].str.replace("veh", "other"))
    ft = fleet_tables(pd.concat([a, b], ignore_index=True), StubBundle(), None)
    assert ft.features["flt_n_others"].max() == 3
