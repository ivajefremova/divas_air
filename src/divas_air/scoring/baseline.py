"""Naive baseline (specs/04_models.md requirement 4): the comparison for every metric.

Fixed thresholds on point-to-point quantities, deliberately without the 5 s
rate base: baseline_score = max(clip(speed_p2p / V, 0, 1), clip(jump / J, 0, 1))
over the pairs of consecutive fixes that both lie in the window. V = 350 m/s
for an airborne aircraft fix, 30 m/s on the ground; J = 500 m. A pair with
dt <= 0 contributes its jump only. Same window grid as the features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Geod

from divas_air.features.windows import Slices, build_grid

V_AIR_MPS = 350.0
V_GROUND_MPS = 30.0
JUMP_M = 500.0
_GEOD = Geod(ellps="WGS84")


def naive_score(points: pd.DataFrame) -> pd.DataFrame:
    """track_id, t_end, baseline_score in [0, 1], baseline_flag."""
    cols = ["track_id", "t_end", "baseline_score", "baseline_flag"]
    if points.empty:
        return pd.DataFrame(columns=cols)
    p = points.sort_values(["track_id", "t"], kind="stable").reset_index(drop=True)
    code, tracks = pd.factorize(p["track_id"])
    t = p["t"].to_numpy(dtype="float64")
    lat = p["lat"].to_numpy(dtype="float64")
    lon = p["lon"].to_numpy(dtype="float64")

    same = np.r_[False, code[1:] == code[:-1]]
    _, _, d = _GEOD.inv(np.r_[lon[0], lon[:-1]], np.r_[lat[0], lat[:-1]], lon, lat)
    dt = t - np.r_[t[0], t[:-1]]
    on_ground = (
        p["on_ground"].astype("boolean").fillna(False).to_numpy(dtype=bool)
        if "on_ground" in p
        else np.zeros(len(p), bool)
    )
    airborne = (p["domain"].astype(str).to_numpy() == "aircraft") & ~on_ground
    v_lim = np.where(airborne, V_AIR_MPS, V_GROUND_MPS)
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.where(dt > 0, d / dt, np.nan)
    pair = np.fmax(np.clip(speed / v_lim, 0, 1), np.clip(d / JUMP_M, 0, 1))
    pair = np.where(same, pair, np.nan)  # pair i joins fixes i-1 and i of one track

    g = build_grid(code, t)
    # pairs with both fixes in [lo, hi) are pair indices lo+1 .. hi-1
    score = Slices(np.minimum(g.lo + 1, g.hi), g.hi).max(pair)
    score = np.where(np.isnan(score), 0.0, score)
    return pd.DataFrame(
        {
            "track_id": np.asarray(tracks, dtype=object)[g.w_track],
            "t_end": g.t_end,
            "baseline_score": score,
            "baseline_flag": score >= 1.0,
        }
    )
