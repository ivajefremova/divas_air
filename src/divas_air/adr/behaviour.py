"""Per-sample behaviour detectors for ADR's `behaviour_anomaly_label`.

Rules come from ADR's geofences (`geo.adr`, profile "adr") and ADR's access
table read directly: each polygon's `allowed_assets` groups against the
asset's `adr_group` from `data/reference/adr_class_map.csv`. Speeds are
displacements over >= RATE_BASE_S (the signal module's centered `v5_mps`).

A position-based label is never raised on a sample whose position a signal
label says is wrong; the raw label is kept so the suppression can be counted.
`wrong_way` is not detected: no zone carries a direction (docs/ADR_DATASET.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import shapely
from pyproj import Geod

from divas_air.adr import tunables as T
from divas_air.adr.kin import keep_long_runs, runs
from divas_air.geo import to_metric

GEOD = Geod(ellps="WGS84")
AIRCRAFT_CLASS = "aircraft_taxi"
RUNWAY_CLASS = "runway_critical"


def zone_pairs(lat, lon, zones) -> pd.DataFrame:
    """(row, zone) pairs for every zone polygon containing the sample."""
    x, y = to_metric(lon, lat)
    tree = shapely.STRtree(zones.geometry.to_numpy())
    pi, zi = tree.query(shapely.points(x, y), predicate="within")
    z = zones.reset_index(drop=True)
    return pd.DataFrame(
        {
            "i": pi,
            "zone_id": z["zone_id"].to_numpy()[zi],
            "cls": z["adr_zone_class"].to_numpy()[zi],
            "groups": z["allowed_groups"].to_numpy()[zi],
            "limit": z["speed_limit_mps"].to_numpy()[zi],
            "area": z.geometry.area.to_numpy()[zi],
        }
    )


def overspeed_threshold(v5, limit, zone_class) -> np.ndarray:
    """limit x (1 + tol), raised to the zone class's bulk quantile where more than
    1 - OVERSPEED_BULK_Q of that class's samples exceed the posted limit."""
    thr = limit * (1 + T.OVERSPEED_TOL)
    df = pd.DataFrame({"v": v5, "lim": limit, "zc": zone_class}).dropna()
    for zc, g in df.groupby("zc"):
        if (g["v"] > g["lim"]).mean() > 1 - T.OVERSPEED_BULK_Q:
            m = zone_class == zc
            thr[m] = np.maximum(thr[m], g["v"].quantile(T.OVERSPEED_BULK_Q))
    return thr


def _min_runs(mask, seg, n_min):
    return keep_long_runs(mask, seg, n_min)


def detect(
    p: pd.DataFrame,
    sig: pd.DataFrame,
    zones,
    group: np.ndarray,
    seg: np.ndarray,
    runway_ref: pd.Series | None = None,
) -> pd.DataFrame:
    """`p` sorted by (track_id, t) with t, lat, lon, domain, typecode_raw; `sig` from
    `signal.detect` on the same rows; `group` the ADR group per row ('' if unknown);
    `seg` the segment code per row. Returns raw and final labels plus raw values."""
    n = len(p)
    cls_adr = p["typecode_raw"].astype("string").fillna("").to_numpy(dtype=object)
    v5 = sig["v5_mps"].to_numpy(dtype="float64")
    pos_wrong = sig["position_wrong"].to_numpy(dtype=bool)
    speed_wrong = np.zeros(n, dtype=bool)
    for lab in T.SPEED_WRONG:
        speed_wrong |= sig[lab].to_numpy(dtype=bool)
    lat = p["lat"].to_numpy(dtype="float64")
    lon = p["lon"].to_numpy(dtype="float64")
    group = np.asarray(group, dtype=object)
    known = group != ""

    pairs = zone_pairs(lat, lon, zones)
    pairs["grp"] = group[pairs["i"].to_numpy()]
    pairs["acls"] = cls_adr[pairs["i"].to_numpy()]
    role = np.array(
        [
            c in T.ROLE_ZONES.get(a, ())
            for a, c in zip(pairs["acls"], pairs["cls"], strict=True)
        ],
        dtype=bool,
    )
    pairs["ok"] = role | np.array(
        [g in s.split(",") for g, s in zip(pairs["grp"], pairs["groups"], strict=True)],
        dtype=bool,
    )
    raw = {lab: np.zeros(n, dtype=bool) for lab in T.BEHAVIOUR_LABELS}
    val: dict[str, np.ndarray] = {
        "zone_id": np.full(n, "", dtype=object),
        "zone_class": np.full(n, "", dtype=object),
        "allowed": np.full(n, "", dtype=object),
        "limit_mps": np.full(n, np.nan),
        "stop_s": np.full(n, np.nan),
        "stop_limit_s": np.full(n, np.nan),
        "prox_m": np.full(n, np.nan),
        "other_id": np.full(n, "", dtype=object),
        "runway": np.full(n, "", dtype=object),
    }

    # smallest containing zone: speed limit and the zone named in evidence
    small = pairs.sort_values(["i", "area"], kind="stable").drop_duplicates("i")
    si = small["i"].to_numpy()
    val["zone_id"][si] = small["zone_id"].to_numpy()
    val["zone_class"][si] = small["cls"].to_numpy()
    val["limit_mps"][si] = small["limit"].to_numpy()

    # --- overspeed ----------------------------------------------------------------
    thr = overspeed_threshold(v5, val["limit_mps"], val["zone_class"])
    val["threshold_mps"] = thr
    over = v5 > thr
    raw["overspeed"] = _min_runs(over, seg, T.OVERSPEED_MIN_S)

    # --- runway_incursion ----------------------------------------------------------
    rwy = pairs[pairs["cls"] == RUNWAY_CLASS]
    if runway_ref is not None:
        ref = runway_ref.astype("string").fillna("").to_numpy(dtype=object)
        on_rwy = ref != ""
        val["runway"] = ref
    else:
        on_rwy = np.zeros(n, dtype=bool)
        on_rwy[rwy["i"].to_numpy()] = True
        val["runway"][rwy["i"].to_numpy()] = rwy["zone_id"].to_numpy()
    crit = zones.loc[zones["adr_zone_class"] == RUNWAY_CLASS, "allowed_groups"]
    rwy_allowed = (
        set.intersection(*(set(a.split(",")) for a in crit)) if len(crit) else set()
    )
    inc = on_rwy & known & ~np.isin(group, list(rwy_allowed))
    raw["runway_incursion"] = _min_runs(inc, seg, T.ZONE_MIN_S)

    # --- unauthorized_zone: no containing zone (runway critical aside) allows the group
    nr = pairs[pairs["cls"] != RUNWAY_CLASS]
    any_ok = nr.groupby("i")["ok"].any()
    bad_i = any_ok.index[~any_ok.to_numpy()].to_numpy()
    una = np.zeros(n, dtype=bool)
    una[bad_i] = True
    una &= known
    raw["unauthorized_zone"] = _min_runs(una, seg, T.ZONE_MIN_S)
    forb = nr[~nr["ok"]].sort_values(["i", "area"]).drop_duplicates("i")
    fi = forb["i"].to_numpy()
    val["zone_id"][fi] = forb["zone_id"].to_numpy()
    val["zone_class"][fi] = forb["cls"].to_numpy()
    val["allowed"][fi] = forb["groups"].to_numpy()

    # --- unexpected_stop --------------------------------------------------------------
    free_any = np.zeros(n, dtype=bool)
    free_any[pairs.loc[pairs["cls"].isin(T.STOP_FREE_ZONES), "i"].to_numpy()] = True
    is_ac = cls_adr == AIRCRAFT_CLASS
    ac_free = np.zeros(n, dtype=bool)
    ac_free[
        pairs.loc[pairs["cls"].isin(T.STOP_AIRCRAFT_FREE_ZONES), "i"].to_numpy()
    ] = True
    track = pd.factorize(p["track_id"])[0]
    first_row = np.r_[True, track[1:] != track[:-1]]
    last_row = np.r_[track[1:] != track[:-1], True]
    t = p["t"].to_numpy(dtype="float64")
    stopped = v5 < T.STOPPED_MPS
    s_run, e_run = runs(stopped, track)  # a gap does not end a stop
    for a, b in zip(s_run, e_run, strict=True):
        if first_row[a] or last_row[b - 1]:
            continue  # parked at the start or end of the mission
        dur = t[b - 1] - t[a]
        zc = pd.Series(val["zone_class"][a:b]).mode()
        zc = zc.iloc[0] if len(zc) else ""
        limit = T.STOP_LIMIT_S.get(zc)
        if limit is None or dur <= limit:
            continue
        if free_any[a:b].mean() >= 0.5 or (is_ac[a] and ac_free[a:b].mean() >= 0.5):
            continue
        raw["unexpected_stop"][a:b] = True
        val["stop_s"][a:b] = dur
        val["stop_limit_s"][a:b] = limit

    # --- aircraft_proximity -----------------------------------------------------------
    ac = np.flatnonzero(is_ac & (v5 >= T.MOVING_MPS) & ~pos_wrong)
    veh = np.flatnonzero(
        (p["domain"].astype("string").to_numpy(dtype=object) == "vehicle")
        & ~np.isin(cls_adr, list(T.PROXIMITY_EXEMPT))
    )
    if len(ac) and len(veh):
        sec = np.floor(t).astype(np.int64)
        a_df = pd.DataFrame({"sec": sec[ac], "j": ac})
        v_df = pd.DataFrame({"sec": sec[veh], "i": veh})
        m = v_df.merge(a_df, on="sec")
        if len(m):
            i, j = m["i"].to_numpy(), m["j"].to_numpy()
            _, _, d = GEOD.inv(lon[i], lat[i], lon[j], lat[j])
            m["d"] = d
            m = m.sort_values(["i", "d"]).drop_duplicates("i")
            close = m[m["d"] < T.PROXIMITY_M]
            prox = np.zeros(n, dtype=bool)
            prox[close["i"].to_numpy()] = True
            raw["aircraft_proximity"] = _min_runs(prox, seg, T.ZONE_MIN_S)
            val["prox_m"][m["i"].to_numpy()] = m["d"].to_numpy()
            ids = p["asset_id"].astype("string").to_numpy(dtype=object)
            val["other_id"][m["i"].to_numpy()] = ids[m["j"].to_numpy()]

    # --- suppression: never on a wrong position (or a wrong speed, for overspeed)
    final = {}
    for lab in T.BEHAVIOUR_LABELS:
        sup = pos_wrong | (speed_wrong if lab == "overspeed" else False)
        final[lab] = raw[lab] & ~sup
    df = pd.DataFrame({f"raw_{k}": v for k, v in raw.items()}, index=p.index)
    for k, v in final.items():
        df[k] = v
    label = np.full(n, "", dtype=object)
    for lab in reversed(T.BEHAVIOUR_LABELS):
        label[final[lab]] = lab
    df["behaviour_label"] = label
    df["group"] = group
    for k, v in val.items():
        df[k] = v
    return df
