"""Per-sample signal detectors for ADR's `signal_anomaly_label`.

ADR's speed and heading are computed from consecutive reported positions
(checked on every sample: |speed - step/dt| <= 0.013 m/s, heading within 1 deg
of the UTM grid bearing of the step). Dead reckoning from them reproduces the
reported track, so the residual here is taken against dead reckoning from the
velocity implied by the positions themselves over >= RATE_BASE_S on either
side of each step.

These are an offline annotator: windows are centered, so labels line up with
the event instead of lagging it. The engine's trust stays causal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from divas_air import config
from divas_air.adr import tunables as T
from divas_air.adr.kin import Kin, count_in, keep_long_runs, kinematics, runs

VALUE_COLUMNS = (
    "v5_mps",
    "step_m",
    "scatter_m",
    "frozen_s",
    "moving_mps",
    "gap_s",
    "bound_mps",
    "heading_diff_deg",
    "alt_dev_m",
)


def _envelope_bound(asset_class: pd.Series) -> np.ndarray:
    env = pd.read_csv(config.REFERENCE / "envelopes.csv").set_index("category")
    on = env["kinematic_checks"].astype(str).str.lower() == "true"
    cap = env["max_ground_speed_mps"].where(on) * T.SPEED_FACTOR
    b = asset_class.astype("string").map(cap).astype("float64").to_numpy()
    return np.where(np.isnan(b), T.SPEED_ABS_MPS, b)


def step_innovation(k: Kin) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(|innovation|, ix, iy) of the step i-1 -> i against the step predicted from
    the >= RATE_BASE_S velocity before i-1 or after i, whichever fits better."""
    n = k.n
    i = np.arange(n)
    prev = np.where(k.first, -1, i - 1)
    dx, dy, dt = k.disp(prev, i)
    prev0 = np.maximum(prev, 0)
    a = np.where(prev >= 0, k.back(T.RATE_BASE_S)[prev0], -1)
    lx, ly, lt = k.disp(a, prev)
    rx, ry, rt = k.disp(i, k.fwd(T.RATE_BASE_S))
    ilx, ily = dx - lx / lt * dt, dy - ly / lt * dt
    irx, iry = dx - rx / rt * dt, dy - ry / rt * dt
    sl, sr = np.hypot(ilx, ily), np.hypot(irx, iry)
    use_r = np.isnan(sl) | (sr < sl)
    s = np.where(use_r, sr, sl)
    return s, np.where(use_r, irx, ilx), np.where(use_r, iry, ily)


def detect(p: pd.DataFrame) -> pd.DataFrame:
    """`p` sorted by (track_id, t) with t, lat, lon, gs_mps, heading_deg, alt_geom_m,
    asset_class. Returns one bool column per label, `signal_label` and the raw values."""
    k = kinematics(p)
    n = k.n
    out = {lab: np.zeros(n, dtype=bool) for lab in T.SIGNAL_LABELS}
    val = {c: np.full(n, np.nan) for c in VALUE_COLUMNS}
    gs = p["gs_mps"].to_numpy(dtype="float64", na_value=np.nan)
    lat = p["lat"].to_numpy(dtype="float64")
    lon = p["lon"].to_numpy(dtype="float64")

    cdx, cdy, cdt, ca, cb = k.centered()
    v5 = np.hypot(cdx, cdy) / cdt
    val["v5_mps"] = v5

    # --- fix_loss: samples around a pause in the stream ---------------------------
    gap = np.flatnonzero(np.isfinite(k.dt_prev) & (k.dt_prev > T.GAP_S))
    for g in gap:
        lo, hi = max(g - T.FIX_LOSS_PAD_BEFORE, 0), g + T.FIX_LOSS_PAD_AFTER
        same = k.code[lo:hi] == k.code[g]
        idx = np.arange(lo, hi)[same]
        out["fix_loss"][idx] = True
        val["gap_s"][idx] = k.dt_prev[g]

    # --- frozen_position ------------------------------------------------------------
    same_pos = np.r_[False, (lat[1:] == lat[:-1]) & (lon[1:] == lon[:-1])]
    same_pos &= ~k.first
    explained = np.zeros(n, dtype=bool)  # steps caused by a freeze, not jumps
    s_run, e_run = runs(same_pos, k.seg)
    fwd5 = k.fwd(T.RATE_BASE_S)
    back5 = k.back(T.RATE_BASE_S)
    for a, b in zip(s_run, e_run, strict=True):
        anchor = a - 1  # last valid fix, repeated by the rows a..b-1
        dur = k.t[b - 1] - k.t[anchor]
        if dur < T.FROZEN_MIN_S:
            continue
        ev = [np.nanmax(gs[a:b]) if b > a else np.nan]
        j = back5[anchor]
        if j >= 0:
            ev.append(
                np.hypot(k.x[anchor] - k.x[j], k.y[anchor] - k.y[j])
                / (k.t[anchor] - k.t[j])
            )
        if b < n and k.seg[b] == k.seg[anchor]:
            f = fwd5[b] if fwd5[b] >= 0 else b
            span = k.t[f] - k.t[anchor]
            ev.append(np.hypot(k.x[f] - k.x[anchor], k.y[f] - k.y[anchor]) / span)
            explained[b] = True
        moving = np.nanmax(ev) if np.isfinite(ev).any() else np.nan
        if moving >= T.MOVING_MPS:
            out["frozen_position"][a:b] = True
            val["frozen_s"][a:b] = dur
            val["moving_mps"][a:b] = moving
            explained[a] = True

    # --- step innovation: multipath first, then jumps -----------------------------
    s, sx, sy = step_innovation(k)
    s_ok = np.where(explained | out["frozen_position"], np.nan, s)
    med = (
        pd.Series(s_ok)
        .groupby(k.seg)
        .rolling(T.MULTIPATH_WIN, center=True, min_periods=T.MULTIPATH_WIN // 2 + 1)
        .median()
        .reset_index(level=0, drop=True)
        .sort_index()
        .to_numpy()
    )
    mp = (med > T.MULTIPATH_M) & ~out["frozen_position"]
    mp = keep_long_runs(mp, k.seg, T.MULTIPATH_MIN_S)
    out["multipath_noise"] = mp
    val["scatter_m"] = np.where(mp, med, np.nan)

    cand = np.flatnonzero((s_ok > T.JUMP_M) & ~mp)
    used = np.zeros(n, dtype=bool)
    for ci, c in enumerate(cand):
        if used[c]:
            continue
        used[c] = True
        end = c + 1
        for r in cand[ci + 1 :]:
            if k.seg[r] != k.seg[c] or k.t[r] - k.t[c] > T.JUMP_MAX_S:
                break
            if used[r]:
                continue
            if np.hypot(sx[c] + sx[r], sy[c] + sy[r]) < T.JUMP_RETURN_FRAC * s[c]:
                used[r] = True
                end = r
                break
        out["position_jump"][c:end] = True
        val["step_m"][c:end] = s[c]

    pos_wrong = np.zeros(n, dtype=bool)
    for lab in T.POSITION_WRONG:
        pos_wrong |= out[lab]
    smooth = count_in(pos_wrong | explained, ca, cb) == 0

    # --- implausible_speed ----------------------------------------------------------
    bound = _envelope_bound(p["asset_class"])
    over = (gs > bound) & (v5 > bound)
    contra = np.abs(gs - v5) > np.maximum(T.SPEED_RESID_MPS, T.SPEED_RESID_REL * v5)
    imp = smooth & (over | contra)
    out["implausible_speed"] = keep_long_runs(imp, k.seg, T.IMPLAUSIBLE_MIN_S)
    val["bound_mps"] = bound

    # --- heading_incoherent -----------------------------------------------------------
    hdg = p["heading_deg"].to_numpy(dtype="float64", na_value=np.nan)
    bearing = np.degrees(np.arctan2(cdx, cdy)) % 360
    d = np.abs((hdg - bearing + 180) % 360 - 180)
    folded = np.minimum(d, 180 - d)
    moving = np.hypot(cdx, cdy) >= T.HEADING_MIN_DISP_M
    inc = smooth & moving & (folded > T.HEADING_MAX_DEG)
    out["heading_incoherent"] = keep_long_runs(inc, k.seg, T.HEADING_MIN_S)
    val["heading_diff_deg"] = np.where(moving, folded, np.nan)

    # --- altitude_spike ---------------------------------------------------------------
    alt = p["alt_geom_m"].to_numpy(dtype="float64", na_value=np.nan)
    med_alt = pd.Series(alt).groupby(k.code).transform("median").to_numpy()
    dev = np.abs(alt - med_alt)
    out["altitude_spike"] = dev > T.ALT_SPIKE_M
    val["alt_dev_m"] = dev

    # gnss_drift: no detector (see docs/ADR_DATASET.md): stays all False

    df = pd.DataFrame(out, index=p.index)
    label = np.full(n, "", dtype=object)
    for lab in reversed(T.SIGNAL_LABELS):
        label[out[lab]] = lab
    df["signal_label"] = label
    df["position_wrong"] = pos_wrong
    for c in VALUE_COLUMNS:
        df[c] = val[c]
    return df
