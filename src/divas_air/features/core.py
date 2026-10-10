"""Kinetic, temporal and signal features (specs/03_features.md requirements 3 to 7).

`fix_level` turns sorted fixes into per-fix quantities (pairs over at least
RATE_BASE_S, run lengths, degradation flags); `window_level` reduces them over
the window and baseline slices of a `Grid`.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from pyproj import Geod

from divas_air import config, params, registry
from divas_air.degradation import is_degraded_reading
from divas_air.features.windows import Grid, Slices

GEOD = Geod(ellps="WGS84")
MIN_JITTER_POINTS = 5
MIN_HISTORY_S = 30.0  # baselines are NaN until the track has this much history
TURN_MIN_DPS = 1.0  # turn radius only where the turn rate exceeds this


@lru_cache(maxsize=1)
def envelopes() -> pd.DataFrame:
    env = pd.read_csv(config.REFERENCE / "envelopes.csv").set_index("category")
    env["kinematic_checks"] = env["kinematic_checks"].astype(str).str.lower().eq("true")
    return env


def wrap180(a):
    """Signed angle difference folded into [-180, 180)."""
    return (np.asarray(a, dtype="float64") + 180.0) % 360.0 - 180.0


def _prev(x: np.ndarray, same: np.ndarray, fill=np.nan) -> np.ndarray:
    """x of the previous fix of the same track."""
    out = np.full(len(x), fill, dtype="float64")
    out[1:] = x[:-1]
    out[~same] = fill
    return out


def _at(x: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """x[idx], NaN where idx < 0."""
    x = np.asarray(x, dtype="float64")
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def fix_level(
    a: dict[str, np.ndarray], track_start: np.ndarray
) -> dict[str, np.ndarray]:
    """Per-fix quantities. `a` holds sorted per-fix columns; `track_start` the index of each fix's track start."""
    n = len(a["t"])
    t = a["t"]
    idx = np.arange(n)
    same = np.r_[False, a["code"][1:] == a["code"][:-1]]
    f: dict[str, np.ndarray] = {}

    env = envelopes().reindex(a["asset_class"])
    gmax = env["max_ground_speed_mps"].to_numpy(dtype="float64")
    amax = env["max_air_speed_mps"].to_numpy(dtype="float64")
    accmax = env["max_accel_mps2"].to_numpy(dtype="float64")
    turnmax = env["max_turn_rate_dps"].to_numpy(dtype="float64")
    radmin = env["min_turn_radius_m"].to_numpy(dtype="float64")
    vmax = env["max_vrate_mps"].to_numpy(dtype="float64")
    f["kin_checks"] = env["kinematic_checks"].fillna(True).to_numpy(dtype=bool)

    limit = np.where(a["taxi"], gmax, amax)
    f["limit"] = limit

    # --- consecutive-fix quantities (intervals, duplicates, frozen runs) ---
    f["dt_prev"] = t - _prev(t, same)
    f["dup"] = (f["dt_prev"] == 0).astype("float64")
    gs = a["gs"]
    same_pos = (
        same & (a["lat"] == _prev(a["lat"], same)) & (a["lon"] == _prev(a["lon"], same))
    )
    frozen = same_pos & (gs > params.MOVING_MPS)
    run = np.cumsum(
        ~frozen
    )  # a run starts at its anchor (the first fix of the repeated position)
    anchor_t = t[np.flatnonzero(~frozen)][run - 1]
    f["frozen"] = frozen.astype("float64")
    f["frozen_s"] = np.minimum(np.where(frozen, t - anchor_t, 0.0), params.BASELINE_S)

    # --- pairs over at least RATE_BASE_S ---
    j = np.empty(n, np.int64)
    for s, e in zip(*_bounds(track_start), strict=True):
        j[s:e] = (
            s + np.searchsorted(t[s:e], t[s:e] - params.RATE_BASE_S, side="right") - 1
        )
    j[j < track_start] = -1
    has = j >= 0
    jj = np.maximum(j, 0)
    pdt = np.where(has, t - t[jj], np.nan)
    az, _, dist = GEOD.inv(a["lon"][jj], a["lat"][jj], a["lon"], a["lat"])
    dist = np.where(has, dist, np.nan)
    az = np.where(has & (dist > 0), np.asarray(az) % 360.0, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        v_imp = dist / pdt
    # reported speed: mean of gs over fixes j..i
    gs0 = np.where(np.isnan(gs), 0.0, gs)
    cs = np.r_[0.0, np.cumsum(gs0)]
    cn = np.r_[0.0, np.cumsum(~np.isnan(gs))]
    with np.errstate(invalid="ignore", divide="ignore"):
        cnt = cn[idx + 1] - cn[jj]
        v_rep = np.where(has & (cnt > 0), (cs[idx + 1] - cs[jj]) / cnt, np.nan)
    resid = np.abs(v_imp - v_rep)
    f["v_imp"], f["v_rep"], f["resid"] = v_imp, v_rep, resid
    f["resid_rel"] = resid / np.maximum(v_rep, params.COURSE_MIN_MPS)

    with np.errstate(invalid="ignore", divide="ignore"):
        # reported speed of a pair is its mean gs (requirement 4); a fix without a pair has gs alone
        f["speed_ratio"] = np.where(has, np.fmax(v_imp, v_rep), gs) / limit
        f["accel_ratio"] = np.abs(gs - _at(gs, j)) / pdt / accmax

        # implied acceleration and turn: this pair against the pair ending at j
        mid = np.where(has, 0.5 * (t + t[jj]), np.nan)
        dmid = mid - _at(mid, j)
        f["accel_imp_ratio"] = np.abs(v_imp - _at(v_imp, j)) / dmid / accmax
        disp_ok = (dist >= params.COURSE_MIN_DISP_M) & (
            _at(dist, j) >= params.COURSE_MIN_DISP_M
        )
        turn_imp = np.abs(wrap180(az - _at(az, j))) / dmid
        # an aircraft's max turn rate is an airborne figure; on the ground its turn is
        # bounded by the minimum radius (kin_turn_radius_ratio_max)
        air_turn = ~(a["ground"] & (a["domain"] == "aircraft"))
        f["turn_imp_ratio"] = np.where(disp_ok & air_turn, turn_imp, np.nan) / turnmax

        # reported turn rate, only where moving at both ends
        trk = a["trk"]
        trk_j = _at(trk, j)
        moving_both = (gs > params.COURSE_MIN_MPS) & (
            _at(gs, j) > params.COURSE_MIN_MPS
        )
        turn = np.where(moving_both, np.abs(wrap180(trk - trk_j)) / pdt, np.nan)
        f["turn_ratio"] = np.where(air_turn, turn, np.nan) / turnmax
        omega = np.radians(turn)
        f["radius_ratio"] = np.where(
            turn > TURN_MIN_DPS, radmin * omega / v_rep, np.nan
        )

        # vertical
        f["vrate_ratio"] = np.abs(a["vrate"]) / vmax
        f["vrate_imp_ratio"] = (
            np.abs(a["alt_baro"] - _at(a["alt_baro"], j)) / pdt / vmax
        )

        # course: implied chord direction vs the mean of the reported courses at both ends
        mean_trk = (trk_j + 0.5 * wrap180(trk - trk_j)) % 360.0
        course_ok = moving_both & (dist >= params.COURSE_MIN_DISP_M)
        f["course_resid"] = np.where(course_ok, np.abs(wrap180(az - mean_trk)), np.nan)
        f["heading_diff"] = np.where(
            gs > params.COURSE_MIN_MPS, np.abs(wrap180(a["hdg"] - trk)), np.nan
        )

        # GNSS - baro altitude divergence
        div = a["alt_geom"] - a["alt_baro"]
        f["alt_div"] = div
        f["alt_div_rate"] = np.abs(div - _at(div, j)) / pdt

    # a fix with no velocity, no NACp and no integrity claim (NIC missing or 0, "Rc unknown"),
    # as MLAT and TIS-B positions are, is not a GNSS report: implied motion there
    # measures the ground network's noise, not the asset
    pos_only = (
        np.isnan(a["gs_raw"])
        & np.isnan(a["trk"])
        & np.isnan(a["nacp"])
        & ~(a["nic"] > 0)
    )
    for k in ENVELOPE_FIX:
        f[k] = np.where(pos_only, np.nan, f[k])

    f["degraded"] = (
        is_degraded_reading(pd.DataFrame({"nacp": a["nacp"]}))
        .to_numpy()
        .astype("float64")
    )
    f["degraded"][np.isnan(a["nacp"])] = np.nan
    return f


WITHHELD = ("kin_accel_imp_ratio_max",)
ENVELOPE_FIX = (  # per-fix arrays behind registry.ENVELOPE_RATIO_COLUMNS
    "speed_ratio",
    "accel_ratio",
    "accel_imp_ratio",
    "turn_ratio",
    "turn_imp_ratio",
    "radius_ratio",
    "vrate_ratio",
    "vrate_imp_ratio",
)


def _bounds(track_start: np.ndarray):
    s = np.unique(track_start)
    return s, np.r_[s[1:], len(track_start)]


def jitter(a: dict[str, np.ndarray], w: Slices) -> np.ndarray:
    """RMS residual distance (m) around a quadratic-in-time fit of local x(t), y(t); NaN below 5 fixes."""
    out = np.full(len(w.lo), np.nan)
    m = w.members
    if not len(m):
        return out
    first = np.repeat(
        w.lo[w.nonempty], w.length[w.nonempty]
    )  # first fix of the member's window
    lat0, lon0 = np.radians(a["lat"][first]), a["lon"][first]
    # local tangent plane on the WGS84 ellipsoid (window spans at most ~10 km)
    a_, e2 = 6378137.0, 6.69437999014e-3
    s2 = np.sin(lat0) ** 2
    r_n = a_ / np.sqrt(1 - e2 * s2)
    r_m = r_n * (1 - e2) / (1 - e2 * s2)
    y = np.radians(a["lat"][m] - a["lat"][first]) * r_m
    x = np.radians(wrap180(a["lon"][m] - lon0)) * r_n * np.cos(lat0)
    starts = w.starts
    cnt = w.length[w.nonempty].astype("float64")
    tm = np.add.reduceat(a["t"][m], starts) / cnt
    tau = (a["t"][m] - np.repeat(tm, w.length[w.nonempty])) / config.WINDOW_S
    sk = [np.add.reduceat(tau**k, starts) for k in range(5)]
    mat = np.stack(
        [
            np.stack([sk[0], sk[1], sk[2]], -1),
            np.stack([sk[1], sk[2], sk[3]], -1),
            np.stack([sk[2], sk[3], sk[4]], -1),
        ],
        -2,
    )
    ok = (cnt >= MIN_JITTER_POINTS) & (
        np.abs(np.linalg.det(mat)) > 1e-12 * np.maximum(sk[0], 1.0) ** 3
    )
    mat[~ok] = np.eye(3)
    res2 = np.zeros(len(m))
    for v in (x, y):
        rhs = np.stack([np.add.reduceat(v * tau**k, starts) for k in range(3)], -1)
        coef = np.linalg.solve(mat, rhs[..., None])[..., 0]
        c = coef[mw_index(w)]
        res2 += (v - (c[:, 0] + c[:, 1] * tau + c[:, 2] * tau**2)) ** 2
    rms = np.sqrt(np.add.reduceat(res2, starts) / cnt)
    vals = np.where(ok, rms, np.nan)
    out[w.nonempty] = vals
    return out


def mw_index(w: Slices) -> np.ndarray:
    """Position of each member's window among the non-empty windows."""
    return np.repeat(np.arange(int(w.nonempty.sum())), w.length[w.nonempty])


def window_level(a, f, g: Grid, w: Slices, b: Slices) -> dict[str, np.ndarray]:
    """Kinetic, temporal and signal features plus their aux columns, one value per window."""
    o: dict[str, np.ndarray] = {}
    last = g.hi - 1  # last fix at or before t_end (always exists)
    n_pts = w.count()
    empty = n_pts == 0

    # --- kinetic ---
    o["kin_speed_resid_max"] = w.max(f["resid"])
    o["kin_speed_resid_rel_max"] = w.max(f["resid_rel"])
    o["kin_speed_resid_mean"] = w.mean(f["resid"])
    o["kin_speed_ratio_max"] = w.max(f["speed_ratio"])
    o["kin_accel_ratio_max"] = w.max(f["accel_ratio"])
    o["kin_accel_imp_ratio_max"] = w.max(f["accel_imp_ratio"])
    o["kin_turn_rate_ratio_max"] = w.max(f["turn_ratio"])
    o["kin_turn_rate_imp_ratio_max"] = w.max(f["turn_imp_ratio"])
    o["kin_turn_radius_ratio_max"] = w.max(f["radius_ratio"])
    o["kin_vrate_ratio_max"] = w.max(f["vrate_ratio"])
    o["kin_vrate_imp_ratio_max"] = w.max(f["vrate_imp_ratio"])
    o["kin_course_resid_max"] = w.max(f["course_resid"])
    o["kin_course_resid_mean"] = w.mean(f["course_resid"])
    o["kin_heading_course_diff_max"] = w.max(f["heading_diff"])
    o["kin_pos_jitter_m"] = jitter(a, w)

    # --- temporal ---
    stale = g.t_end - a["t"][last]
    o["tmp_n_points"] = n_pts
    o["tmp_gap_max_s"] = np.fmax(w.max(f["dt_prev"]), stale)
    o["tmp_staleness_s"] = stale
    # baselines need fixes at least MIN_HISTORY_S before the window start
    t_first_base = a["t"][np.minimum(g.blo, len(a["t"]) - 1)]
    history_ok = (g.lo > g.blo) & (
        g.t_end - config.WINDOW_S - t_first_base >= MIN_HISTORY_S
    )
    dt_w = w.median(f["dt_prev"])
    dt_b = np.where(history_ok, b.median(f["dt_prev"]), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        o["tmp_dt_dev_ratio"] = np.where(dt_b > 0, np.abs(dt_w - dt_b) / dt_b, np.nan)
    o["tmp_dup_count"] = w.sum(f["dup"])
    o["tmp_nonmono_count"] = w.sum(a["nonmono"])
    o["tmp_frozen_run_s"] = np.where(empty, np.nan, w.max(f["frozen_s"]))
    o["tmp_frozen_frac"] = np.where(empty, np.nan, w.mean(f["frozen"]))

    # --- signal ---
    nacp_med = w.median(a["nacp"])
    nic_med = w.median(a["nic"])
    o["sig_nacp_median"] = nacp_med
    o["sig_nacp_min"] = w.min(a["nacp"])
    o["sig_nacp_drop"] = np.clip(
        np.where(history_ok, b.median(a["nacp"]), np.nan) - nacp_med, 0, None
    )
    o["sig_nic_median"] = nic_med
    o["sig_nic_drop"] = np.clip(
        np.where(history_ok, b.median(a["nic"]), np.nan) - nic_med, 0, None
    )
    o["sig_sil_min"] = w.min(a["sil"])
    deg = w.mean(f["degraded"])
    o["sig_degraded_frac"] = deg
    o["sig_degraded_majority"] = np.where(
        np.isnan(deg), np.nan, (deg > 0.5).astype("float64")
    )
    div_b = np.where(history_ok, b.median(f["alt_div"]), np.nan)
    o["sig_alt_div_dev_max_m"] = _dev_max(f["alt_div"], div_b, w)
    o["sig_alt_div_rate_max"] = w.max(f["alt_div_rate"])

    # Emitted as NaN (P1, see docs/STATUS.md): over 5 s pairs the change of implied speed is
    # dominated by ADS-B position and timestamp noise (0.21 % of clean fco windows over the
    # limit). The per-fix value stays in `f` so a longer base can switch it back on.
    for c in WITHHELD:
        o[c] = np.full(g.n, np.nan)

    # helicopters and other classes without kinematic checks: no envelope ratios
    no_env = ~f["kin_checks"][last]
    for c in registry.ENVELOPE_RATIO_COLUMNS:
        o[c] = np.where(no_env, np.nan, o[c])

    # --- aux ---
    i_res = w.argmax(f["resid"])
    o["aux_speed_implied_mps"] = _at(f["v_imp"], i_res)
    o["aux_speed_reported_mps"] = _at(f["v_rep"], i_res)
    i_spd = w.argmax(f["speed_ratio"])
    o["aux_class_max_speed_mps"] = np.where(
        i_spd >= 0, _at(f["limit"], i_spd), f["limit"][last]
    )
    o["aux_lat"] = a["lat"][last]
    o["aux_lon"] = a["lon"][last]
    o["aux_alt_m"] = np.where(
        np.isnan(a["alt_baro"][last]), a["alt_geom"][last], a["alt_baro"][last]
    )
    o["aux_gs_mps"] = a["gs_raw"][last]
    o["aux_track_deg"] = a["trk"][last]
    o["aux_airborne"] = ~a["ground"][last]
    return o


def _dev_max(v: np.ndarray, base: np.ndarray, w: Slices) -> np.ndarray:
    """max over window fixes of |v - window baseline|."""
    out = np.full(len(w.lo), np.nan)
    if not len(w.members):
        return out
    d = np.abs(v[w.members] - base[w.member_window])
    out[w.nonempty] = np.fmax.reduceat(d, w.starts)
    return out
