"""Spatial and contextual features (specs/03_features.md requirement 5).

Ground fixes (vehicles, aircraft with on_ground) are placed on the LIRF zones,
routes and buildings; airborne fixes are matched against the runway ends for
the approach and phase features. The layers describe LIRF only: ground fixes
get map features inside `config.AIRPORT_BOX`, airborne fixes inside
`config.APPROACH_BOX`. Elsewhere (Ciampino, Baltic, control) they are NaN,
not "off every zone".
"""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
import pandas as pd
import shapely

from divas_air import config, params
from divas_air.features.core import GEOD, wrap180
from divas_air.features.windows import Grid, Slices

AIRLINE_CALLSIGN = re.compile(r"^[A-Z]{3}[0-9]")


@lru_cache(maxsize=1)
def zone_access() -> pd.DataFrame:
    za = pd.read_csv(config.REFERENCE / "zone_access.csv")
    za["allowed"] = za["allowed"].astype(str).str.lower().eq("true")
    return za.set_index(["zone_type", "asset_class"])


@lru_cache(maxsize=4)
def _trees(layers):
    return (
        shapely.STRtree(layers.zones.geometry.to_numpy()),
        shapely.STRtree(layers.buildings.geometry.to_numpy()),
    )


def _in_box(lat: np.ndarray, lon: np.ndarray, box=config.APPROACH_BOX) -> np.ndarray:
    lat0, lon0, lat1, lon1 = box
    return (lat >= lat0) & (lat <= lat1) & (lon >= lon0) & (lon <= lon1)


TAXI_ZONES = ("taxiway", "apron", "stand", "holding_point")


@lru_cache(maxsize=4)
def _taxi_area(layers):
    """Taxi surfaces (with ZONE_BUFFER_M) minus the runways (with ZONE_BUFFER_M)."""
    z = layers.zones
    taxi = shapely.union_all(
        z[z["zone_type"].isin(TAXI_ZONES)]
        .geometry.buffer(params.ZONE_BUFFER_M)
        .to_numpy()
    )
    rw = shapely.union_all(
        z[z["zone_type"] == "runway"].geometry.buffer(params.ZONE_BUFFER_M).to_numpy()
    )
    area = shapely.difference(taxi, rw)
    shapely.prepare(area)
    return area


def taxi_surface_mask(layers, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """True on a mapped taxi surface (taxiway, apron, stand, holding point, within ZONE_BUFFER_M) off the runways."""
    out = np.zeros(len(lat), dtype=bool)
    m = _in_box(lat, lon)
    if m.any():
        x, y = layers.to_metric(lon[m], lat[m])
        out[m] = shapely.contains_xy(_taxi_area(layers), x, y)
    return out


def _ground(
    a, layers, idx: np.ndarray, x: np.ndarray, y: np.ndarray
) -> dict[str, np.ndarray]:
    """Per-fix ground quantities for the fixes `idx` (metric x, y)."""
    n = len(idx)
    out = {}
    pts = shapely.points(x, y)
    route = np.full(n, np.nan)
    dom = a["domain"][idx]
    for d in ("aircraft", "vehicle"):
        m = dom == d
        if m.any():
            route[m] = layers.route_distance_m(x[m], y[m], d)
    out["route"] = route

    ztree, btree = _trees(layers)
    bi, _ = btree.query(pts, predicate="intersects")
    in_b = np.zeros(n)
    in_b[bi] = 1.0
    out["in_building"] = in_b
    out["outside"] = (~shapely.contains_xy(layers.boundary, x, y)).astype("float64")

    zones = layers.zones
    pi, zi = ztree.query(pts, predicate="dwithin", distance=params.ZONE_BUFFER_M)
    dist = shapely.distance(pts[pi], zones.geometry.to_numpy()[zi])
    occ = dist == 0
    near = dist <= params.ZONE_OCCUPANCY_MARGIN_M  # in the zone up to GNSS noise
    crit = zones["criticality"].to_numpy(dtype="float64")[zi]
    ztype = zones["zone_type"].to_numpy(dtype=object)[zi]
    limit = zones["speed_limit_mps"].to_numpy(dtype="float64")[zi]

    # zone behind the criticality: highest criticality, then nearest, then lowest index
    order = np.lexsort((zi, dist, -crit, pi))
    first = order[np.r_[True, pi[order][1:] != pi[order][:-1]]] if len(order) else order
    out["crit"] = np.zeros(n)
    out["crit"][pi[first]] = crit[first]
    out["zone"] = np.full(n, -1, np.int64)
    out["zone"][pi[first]] = zi[first]

    lim = np.full(n, np.nan)
    sel = near & ~np.isnan(limit)
    np.fmin.at(lim, pi[sel], limit[sel])
    lim_zone = np.full(n, -1, np.int64)
    hit = sel & (limit == lim[pi])
    lim_zone[pi[hit]] = zi[hit]
    out["limit"] = lim
    out["limit_zone"] = lim_zone
    with np.errstate(invalid="ignore", divide="ignore"):
        out["speed_ratio"] = a["gs"][idx] / lim

    za = zone_access()
    cls = a["asset_class"][idx][pi]
    key = pd.MultiIndex.from_arrays([ztype, cls])
    acc = za.reindex(key)
    allowed = acc["allowed"].fillna(True).to_numpy(dtype=bool)
    max_dwell = acc["max_dwell_s"].to_numpy(dtype="float64")
    any_allowed = np.zeros(n, dtype=bool)
    any_allowed[pi[near & allowed]] = True
    # crossing another zone type from a place the asset may be is fine, except a runway
    viol = occ & ~allowed & ((ztype == "runway") | ~any_allowed[pi])
    out["violation"] = np.zeros(n)
    np.maximum.at(out["violation"], pi[viol], crit[viol])
    out["offzone"] = ((out["outside"] == 0) & ~np.isin(np.arange(n), pi[near])).astype(
        "float64"
    )

    # dwell limit of the most critical occupied zone that has one
    dl = occ & ~np.isnan(max_dwell)
    o2 = np.lexsort((-crit[dl], pi[dl]))
    f2 = o2[np.r_[True, pi[dl][o2][1:] != pi[dl][o2][:-1]]] if dl.any() else o2
    out["max_dwell"] = np.full(n, np.nan)
    out["max_dwell"][pi[dl][f2]] = max_dwell[dl][f2]
    return out


def dwell_seconds(
    code: np.ndarray, t: np.ndarray, x: np.ndarray, y: np.ndarray, ok: np.ndarray
) -> np.ndarray:
    """Time since the asset last moved more than DWELL_MOVE_M from its anchor: one causal pass.

    `ok` marks the fixes the timer runs on (ground fixes inside the map); any other
    fix resets it. Explicit per-track state, so the online engine can carry it.
    """
    out = np.full(len(t), np.nan)
    lim2 = params.DWELL_MOVE_M**2
    prev_code, ax, ay, at = -1, 0.0, 0.0, 0.0
    tl, xl, yl, cl, okl = t.tolist(), x.tolist(), y.tolist(), code.tolist(), ok.tolist()
    for i in range(len(tl)):
        if not okl[i]:
            prev_code = -1
            continue
        if cl[i] != prev_code or (xl[i] - ax) ** 2 + (yl[i] - ay) ** 2 > lim2:
            prev_code, ax, ay, at = cl[i], xl[i], yl[i], tl[i]
        out[i] = tl[i] - at
    return out


def _airborne(
    a, layers, idx: np.ndarray, x: np.ndarray, y: np.ndarray
) -> dict[str, np.ndarray]:
    """Per-fix approach quantities for airborne fixes `idx`."""
    n = len(idx)
    rw = layers.runways
    lat, lon = a["lat"][idx], a["lon"][idx]
    trk = a["trk"][idx]
    alt = np.where(np.isnan(a["alt_geom"][idx]), a["alt_baro"][idx], a["alt_geom"][idx])
    best_lat = np.full(n, np.inf)
    best_d = np.full(n, np.inf)
    out = {k: np.full(n, np.nan) for k in ("lateral", "glide", "descent")}
    out["end"] = np.full(n, -1, np.int64)
    tan_gs = np.tan(np.radians(params.GLIDESLOPE_DEG))
    tan_cone = np.tan(np.radians(params.APPROACH_CONE_DEG))
    # the runway is the aligned end with the nearest extended centerline; the distance
    # and height gates apply to that end only
    for e, r in enumerate(rw.itertuples(index=False)):
        az, _, d = GEOD.inv(
            lon, lat, np.full(n, r.threshold_lon), np.full(n, r.threshold_lat)
        )
        ang = np.abs(wrap180(np.asarray(az) - r.bearing_deg))
        aligned = (
            np.abs(wrap180(trk - r.bearing_deg)) <= params.APPROACH_ALIGN_DEG
        ) & (ang < 90.0)
        lat_m = d * np.sin(np.radians(ang))
        take = aligned & (lat_m < best_lat)
        best_lat = np.where(take, lat_m, best_lat)
        best_d = np.where(take, d, best_d)
        out["end"] = np.where(take, e, out["end"])
        out["lateral"] = np.where(take, ang, out["lateral"])
        with np.errstate(invalid="ignore", divide="ignore"):
            height = alt - r.elevation_m
            glide = np.degrees(np.arctan2(height, d))
            out["glide"] = np.where(
                take, np.abs(glide - params.GLIDESLOPE_DEG), out["glide"]
            )
            out["height_ok"] = np.where(
                take,
                ~(height > tan_cone * d + params.APPROACH_CONE_FLOOR_M),
                out.get("height_ok", np.zeros(n, dtype=bool)),
            )
            ref = a["gs"][idx] * tan_gs
            desc = np.abs(-a["vrate"][idx] - ref) / ref
            out["descent"] = np.where(take, desc, out["descent"])
    on_final = (
        (out["end"] >= 0)
        & (best_d <= params.APPROACH_FINAL_KM * 1000.0)
        & out.get("height_ok", np.zeros(n, dtype=bool)).astype(bool)
    )
    out["end"] = np.where(on_final, out["end"], -1)
    for k in ("lateral", "glide", "descent"):
        out[k] = np.where(on_final, out[k], np.nan)
    out["final"] = out["end"] >= 0

    # distance to the nearest runway axis (infinite line through both thresholds)
    axis = np.full(n, np.inf)
    ex, ey = layers.to_metric(
        rw["threshold_lon"].to_numpy(), rw["threshold_lat"].to_numpy()
    )
    for grp in rw.groupby("runway").groups.values():
        i0, i1 = grp[0], grp[-1]
        dx, dy = ex[i1] - ex[i0], ey[i1] - ey[i0]
        norm = np.hypot(dx, dy)
        axis = np.minimum(axis, np.abs((x - ex[i0]) * dy - (y - ey[i0]) * dx) / norm)
    elev = float(rw["elevation_m"].iloc[0])
    with np.errstate(invalid="ignore"):
        out["phase"] = np.where(
            np.isnan(alt),
            np.nan,
            ((alt - elev < params.PHASE_LOW_M) & (axis > params.PHASE_AXIS_M)).astype(
                "float64"
            ),
        )
    return out


def _raw_class(typecode_raw: pd.Series) -> np.ndarray:
    from divas_air.ingest import asset_class_for

    raw = typecode_raw.astype("string")
    return np.array(
        [
            asset_class_for(v) if isinstance(v, str) else None
            for v in raw.fillna(pd.NA).astype(object)
        ],
        dtype=object,
    )


def window_level(
    p: pd.DataFrame, a, f, g: Grid, w: Slices, layers
) -> dict[str, np.ndarray]:
    """Spatial and contextual features and the aux_zone_* columns, one value per window."""
    from divas_air.features.core import envelopes

    n = len(a["t"])
    inmap = _in_box(a["lat"], a["lon"])
    at_airport = _in_box(a["lat"], a["lon"], config.AIRPORT_BOX)
    x, y = layers.to_metric(a["lon"], a["lat"])
    aircraft = a["domain"] == "aircraft"
    gmask = a["ground"] & at_airport
    amask = ~a["ground"] & inmap & aircraft
    heli = ~f["kin_checks"]

    def full(fill=np.nan, dtype="float64"):
        return np.full(n, fill, dtype=dtype)

    route, in_b, outside, crit, offzone, viol, sratio, dwell_lim = (
        full() for _ in range(8)
    )
    zone = full(-1, np.int64)
    lim, lim_zone = full(), full(-1, np.int64)
    gi = np.flatnonzero(gmask)
    if len(gi):
        gq = _ground(a, layers, gi, x[gi], y[gi])
        route[gi], in_b[gi], outside[gi] = gq["route"], gq["in_building"], gq["outside"]
        crit[gi], zone[gi], offzone[gi], viol[gi] = (
            gq["crit"],
            gq["zone"],
            gq["offzone"],
            gq["violation"],
        )
        sratio[gi], lim[gi], lim_zone[gi], dwell_lim[gi] = (
            gq["speed_ratio"],
            gq["limit"],
            gq["limit_zone"],
            gq["max_dwell"],
        )
        offzone[gi] = np.where(outside[gi] == 1, np.nan, offzone[gi])
    dwell = dwell_seconds(a["code"], a["t"], x, y, gmask)
    with np.errstate(invalid="ignore", divide="ignore"):
        dwell_ratio = np.where(
            gmask, np.where(np.isnan(dwell_lim), 0.0, dwell / dwell_lim), np.nan
        )

    lateral, glide, descent, phase = full(), full(), full(), full()
    app_end = full(-1, np.int64)
    ai = np.flatnonzero(amask)
    if len(ai):
        aq = _airborne(a, layers, ai, x[ai], y[ai])
        crit[ai] = np.where(
            aq["final"],
            params.CRITICALITY_AIRBORNE_FINAL,
            params.CRITICALITY_AIRBORNE_OTHER,
        )
        app_end[ai] = aq["end"]
        fixed_wing = ~heli[ai]
        lateral[ai] = np.where(fixed_wing, aq["lateral"], np.nan)
        glide[ai] = np.where(fixed_wing, aq["glide"], np.nan)
        descent[ai] = np.where(fixed_wing, aq["descent"], np.nan)
        phase[ai] = np.where(fixed_wing, aq["phase"], np.nan)

    # on-ground flag against height and speed (aircraft)
    og = a["on_ground"]
    known = aircraft & at_airport & og.notna().to_numpy()
    ogb = og.fillna(False).to_numpy(dtype=bool)
    elev = float(layers.runways["elevation_m"].iloc[0])
    with np.errstate(invalid="ignore"):
        c_ground = ogb & (a["alt_baro"] - elev > params.GROUND_ALT_CONFLICT_M)
        c_air = ~ogb & ~heli & (a["gs"] < params.AIRBORNE_MIN_MPS)
    ground_conflict = np.where(known, (c_ground | c_air).astype("float64"), np.nan)

    # identity rules on the declared (raw) type
    raw_cls = (
        _raw_class(p["typecode_raw"])
        if "typecode_raw" in p.columns
        else np.full(n, None, dtype=object)
    )
    declared = aircraft & inmap & (raw_cls != None)
    env = envelopes().reindex(np.where(declared, raw_cls, "other"))
    # callsigns arrive in a minority of messages: carry the last one forward (causal)
    callsign = (
        p["callsign"].astype("string").groupby(a["code"]).ffill().fillna("")
        if "callsign" in p.columns
        else pd.Series("", index=p.index)
    )
    airline = callsign.str.match(AIRLINE_CALLSIGN.pattern).to_numpy(dtype=bool)
    # a light or unknown declared type under an airline callsign
    small = np.isin(raw_cls, ["light", "other"])
    r1 = np.where(declared, (airline & small).astype("float64"), np.nan)
    with np.errstate(invalid="ignore"):
        fast = (~a["ground"]) & (
            a["gs"] > env["max_air_speed_mps"].to_numpy(dtype="float64")
        )
    r2 = np.where(declared, fast.astype("float64"), np.nan)

    o: dict[str, np.ndarray] = {}
    o["spa_route_dist_max_m"] = w.max(route)
    o["spa_route_dist_mean_m"] = w.mean(route)
    o["spa_offzone_frac"] = w.mean(offzone)
    o["spa_in_building_frac"] = w.mean(in_b)
    off = w.mean(outside)
    o["spa_off_airport"] = np.where(
        np.isnan(off), np.nan, (off > 0.5).astype("float64")
    )
    o["spa_zone_crit_max"] = w.max(crit)
    o["ctx_zone_speed_ratio_max"] = w.max(sratio)
    o["ctx_type_violation_crit_max"] = w.max(viol)
    o["ctx_dwell_ratio"] = w.max(dwell_ratio)
    o["ctx_ground_alt_conflict"] = w.mean(ground_conflict)
    o["ctx_phase_conflict_frac"] = w.mean(phase)
    o["ctx_app_lateral_dev_deg"] = w.max(lateral)
    o["ctx_app_glide_dev_deg"] = w.max(glide)
    o["ctx_app_descent_dev_ratio"] = w.mean(descent)
    o["ctx_identity_mismatch"] = w.max(r1) + w.max(r2)

    # aux_zone_*: the zone behind spa_zone_crit_max (ground) or the approach end (airborne final)
    i_crit = w.argmax(crit)
    zones = layers.zones
    zid = np.full(g.n, None, dtype=object)
    zname = np.full(g.n, None, dtype=object)
    ztype = np.full(g.n, None, dtype=object)
    zlim = np.full(g.n, np.nan)
    has = i_crit >= 0
    k = np.where(has, zone[np.maximum(i_crit, 0)], -1)
    gz = k >= 0
    zid[gz] = zones["zone_id"].to_numpy(dtype=object)[k[gz]]
    zname[gz] = zones["zone_name"].to_numpy(dtype=object)[k[gz]]
    ztype[gz] = zones["zone_type"].to_numpy(dtype=object)[k[gz]]
    zlim[gz] = zones["speed_limit_mps"].to_numpy(dtype="float64")[k[gz]]
    e = np.where(has, app_end[np.maximum(i_crit, 0)], -1)
    az = e >= 0
    ends = layers.runways["end"].to_numpy(dtype=object)
    zid[az] = np.array([f"approach_{x}" for x in ends[e[az]]], dtype=object)
    zname[az] = np.array([f"final {x}" for x in ends[e[az]]], dtype=object)
    ztype[az] = "approach"
    # the speed limit (and its zone name) behind ctx_zone_speed_ratio_max takes precedence
    i_spd = w.argmax(sratio)
    sz = np.where(i_spd >= 0, lim_zone[np.maximum(i_spd, 0)], -1) >= 0
    zlim[sz] = lim[i_spd[sz]]
    o["aux_zone_id"], o["aux_zone_name"], o["aux_zone_type"] = zid, zname, ztype
    o["aux_zone_speed_limit_mps"] = zlim
    return o
