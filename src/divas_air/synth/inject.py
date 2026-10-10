"""Anomaly injection: one physical mechanism per cause (specs/02_generator.md section 3).

`inject` is pure and works on any frame in the unified schema. Offsets are
applied in meters on the WGS84 ellipsoid, so no map layers are needed except to
find a runway for an incursion without an explicit target.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import shapely
from pyproj import Geod

from divas_air import params, schema
from divas_air.geo import gnss, to_metric, to_wgs84

_GEOD = Geod(ellps="WGS84")
SIGMA0 = params.GNSS_OPEN_SIGMA_M
TECH_MODES = ("freeze", "jump", "duplicate_t", "out_of_order", "loss")
BEHAVIOR_MODES = ("deviate", "incursion")


def _offset(lat, lon, north, east):
    """Move points by (north, east) meters. Returns (lat, lon)."""
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    north = np.broadcast_to(np.asarray(north, dtype="float64"), lat.shape)
    east = np.broadcast_to(np.asarray(east, dtype="float64"), lat.shape)
    lon2, lat2, _ = _GEOD.fwd(
        lon, lat, np.degrees(np.arctan2(east, north)), np.hypot(north, east)
    )
    return np.asarray(lat2), np.asarray(lon2)


def _smoothstep(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def add_labels(points: pd.DataFrame, params_: dict | None = None) -> pd.DataFrame:
    """Add missing label columns: clean labels, truth = the input position."""
    out = points.copy()
    p = params_ or {}
    if "label_cause" not in out.columns:
        out["label_cause"] = "plausible"
    if "label_onset_t" not in out.columns:
        out["label_onset_t"] = np.nan
    if "label_event_id" not in out.columns:
        out["label_event_id"] = pd.Series(pd.NA, index=out.index, dtype="string")
    if "label_true_lat" not in out.columns:
        out["label_true_lat"] = out["lat"]
    if "label_true_lon" not in out.columns:
        out["label_true_lon"] = out["lon"]
    if "scene_id" not in out.columns:
        out["scene_id"] = p.get("scene_id", out["track_id"])
    if "base_track_id" not in out.columns:
        out["base_track_id"] = p.get("base_track_id", out["track_id"])
    return out


def _class_speed(asset_class: str) -> float:
    from divas_air.synth.motion import envelopes

    return float(envelopes().loc[asset_class, "max_ground_speed_mps"])


def _recompute_motion(t, lat, lon, rng):
    """Reported speed and course from a (true) path, central differences, plus sensor noise."""
    n = len(t)
    i0 = np.clip(np.arange(n) - 1, 0, n - 1)
    i1 = np.clip(np.arange(n) + 1, 0, n - 1)
    az, _, d = _GEOD.inv(lon[i0], lat[i0], lon[i1], lat[i1])
    dt = np.maximum(t[i1] - t[i0], 1e-3)
    gs = d / dt + rng.normal(0, params.SPEED_NOISE_MPS, n)
    crs = np.mod(az + rng.normal(0, params.COURSE_NOISE_DEG, n), 360.0)
    return np.maximum(gs, 0.0), crs


class _Track:
    """Mutable column arrays of one track, sorted by time."""

    COLS = (
        "t",
        "seq",
        "lat",
        "lon",
        "label_true_lat",
        "label_true_lon",
        "nacp",
        "nic",
        "gs_mps",
        "track_deg",
        "heading_deg",
        "alt_geom_m",
    )

    def __init__(self, df: pd.DataFrame):
        self.index = df.index.to_numpy()
        for c in self.COLS:
            setattr(
                self,
                c,
                df[c].to_numpy(dtype="float64" if c != "seq" else "int64").copy(),
            )
        self.asset_class = str(df["asset_class"].iloc[0])
        self.drop = np.zeros(len(df), dtype=bool)
        self.label = np.zeros(len(df), dtype=bool)

    def noise(self):
        """(north, east) meters of reported minus true position."""
        az, _, d = _GEOD.inv(
            self.label_true_lon, self.label_true_lat, self.lon, self.lat
        )
        a = np.radians(az)
        return d * np.cos(a), d * np.sin(a)


# --- one function per cause -------------------------------------------------
# Each takes (track, mask of active points, onset, t_end, rng, p) and records draws in p.


def _degraded(tr, m, onset, t_end, rng, p):
    k = p.setdefault("noise_factor", float(rng.uniform(3, 10)))
    drop = p.setdefault("integrity_drop", int(rng.integers(1, 4)))
    miss = p.setdefault("miss_prob", float(rng.uniform(0.02, 0.15)))
    tau = float(rng.uniform(5, 15))
    s = SIGMA0 * np.sqrt(k**2 - 1)
    t = tr.t[m]
    n_ = s * gnss.gauss_markov(t, tau, rng) + 0.3 * s * rng.standard_normal(m.sum())
    e_ = s * gnss.gauss_markov(t, tau, rng) + 0.3 * s * rng.standard_normal(m.sum())
    tr.lat[m], tr.lon[m] = _offset(tr.lat[m], tr.lon[m], n_, e_)
    tr.nacp[m] = np.maximum(tr.nacp[m] - drop, 0)
    tr.nic[m] = np.maximum(tr.nic[m] - drop, 0)
    tr.drop |= m & (rng.random(len(m)) < miss)
    tr.label |= m


def _technical_error(tr, m, onset, t_end, rng, p):
    mode = p.setdefault("mode", str(rng.choice(TECH_MODES)))
    idx = np.flatnonzero(m)
    if mode == "freeze":
        # position stuck at the first active fix while speed is still reported
        tr.lat[idx] = tr.lat[idx[0]]
        tr.lon[idx] = tr.lon[idx[0]]
    elif mode == "jump":
        if "target_lat" in p:
            # placed at a fixed point (e.g. on a runway), keeping the receiver noise
            nn, ee = tr.noise()
            tr.lat[idx], tr.lon[idx] = _offset(
                np.full(len(idx), p["target_lat"]),
                np.full(len(idx), p["target_lon"]),
                nn[idx],
                ee[idx],
            )
        else:
            dist = p.setdefault("jump_m", float(rng.uniform(50, 2000)))
            az = np.radians(p.setdefault("jump_az_deg", float(rng.uniform(0, 360))))
            tr.lat[idx], tr.lon[idx] = _offset(
                tr.lat[idx], tr.lon[idx], dist * np.cos(az), dist * np.sin(az)
            )
    elif mode == "duplicate_t":
        prob = p.setdefault("fault_prob", float(rng.uniform(0.2, 0.5)))
        hit = idx[1:][rng.random(len(idx) - 1) < prob]
        tr.t[hit] = tr.t[hit - 1]
    elif mode == "out_of_order":
        prob = p.setdefault("fault_prob", float(rng.uniform(0.2, 0.5)))
        cand = idx[:-1][rng.random(len(idx) - 1) < prob]
        cand = cand[np.concatenate([[True], np.diff(cand) > 1])] if len(cand) else cand
        tr.seq[cand], tr.seq[cand + 1] = tr.seq[cand + 1].copy(), tr.seq[cand].copy()
    elif mode == "loss":
        # no fix in the middle of the event; the fixes at both edges carry the label
        gap = p.setdefault(
            "loss_s", float(min(rng.uniform(10, 60), max(t_end - onset - 6.0, 1.0)))
        )
        mid = 0.5 * (onset + t_end)
        tr.drop |= m & (np.abs(tr.t - mid) < gap / 2)
    else:
        raise ValueError(f"unknown technical_error mode {mode!r}")
    tr.label |= m


def _gnss_anomaly(tr, m, onset, t_end, rng, p):
    rate = p.setdefault("drift_mps", float(rng.uniform(0.5, 5)))
    az = np.radians(p.setdefault("drift_az_deg", float(rng.uniform(0, 360))))
    e = tr.t[m] - onset
    bias = rate * e
    s = 0.05 * bias + 0.5 * SIGMA0
    tau = float(rng.uniform(5, 15))
    n_ = bias * np.cos(az) + s * gnss.gauss_markov(tr.t[m], tau, rng)
    e_ = bias * np.sin(az) + s * gnss.gauss_markov(tr.t[m], tau, rng)
    tr.lat[m], tr.lon[m] = _offset(tr.lat[m], tr.lon[m], n_, e_)
    # the receiver sees part of its own error: accuracy degrades as the bias grows
    nacp, nic = gnss.integrity_from_sigma(SIGMA0 + 0.5 * bias)
    tr.nacp[m] = np.minimum(tr.nacp[m], nacp)  # NaN stays NaN: nothing was reported
    tr.nic[m] = np.minimum(tr.nic[m], nic)
    vrate = p.setdefault(
        "alt_drift_mps", float(rng.uniform(0.2, 1.0) * rng.choice([-1, 1]))
    )
    tr.alt_geom_m[m] = tr.alt_geom_m[m] + vrate * e  # NaN stays NaN (no GNSS altitude)
    tr.label |= m


def _possible_interference(tr, m, onset, t_end, rng, p, severity=None):
    k = p.setdefault("noise_factor", float(rng.uniform(5, 20)))
    collapse = p.setdefault("collapse", float(rng.uniform(0.6, 1.0)))
    sev = np.ones(m.sum()) if severity is None else severity
    s = SIGMA0 * np.sqrt((1 + (k - 1) * sev) ** 2 - 1)
    tau = float(rng.uniform(3, 10))
    t = tr.t[m]
    n_ = s * (gnss.gauss_markov(t, tau, rng) + 0.5 * rng.standard_normal(len(t)))
    e_ = s * (gnss.gauss_markov(t, tau, rng) + 0.5 * rng.standard_normal(len(t)))
    tr.lat[m], tr.lon[m] = _offset(tr.lat[m], tr.lon[m], n_, e_)
    keep = 1.0 - collapse * sev
    tr.nacp[m] = np.floor(tr.nacp[m] * keep)
    tr.nic[m] = np.floor(tr.nic[m] * keep)
    idx = np.flatnonzero(m)
    tr.drop[idx] |= rng.random(len(idx)) < 0.3 * sev
    if len(idx) > 10 and rng.random() < 0.3:  # a loss of fix inside the event
        gap = rng.uniform(8, 25)
        start = rng.uniform(t[0], max(t[-1] - gap, t[0]))
        tr.drop[idx] |= (t >= start) & (t < start + gap)
    if len(idx):
        tr.drop[idx[0]] = False  # the track keeps at least one fix inside the event
    tr.label |= m


def _possible_spoofing(tr, m, onset, t_end, rng, p):
    rate = p.setdefault("drift_mps", float(rng.uniform(0.5, 3)))
    az = np.radians(p.setdefault("drift_az_deg", float(rng.uniform(0, 360))))
    ramp = 10.0
    e = tr.t[m] - onset
    d = np.where(e < ramp, rate * e**2 / (2 * ramp), rate * (e - ramp / 2))
    # the false position carries the receiver's own nominal noise: no extra jitter, NACp untouched
    tr.lat[m], tr.lon[m] = _offset(tr.lat[m], tr.lon[m], d * np.cos(az), d * np.sin(az))
    vrate = p.setdefault(
        "alt_drift_mps", float(rng.uniform(0.3, 1.5) * rng.choice([-1, 1]))
    )
    tr.alt_geom_m[m] = tr.alt_geom_m[m] + vrate * e
    tr.label |= m


def _behavioral_anomaly(tr, m, onset, t_end, rng, p, layers=None):
    mode = p.setdefault("mode", "incursion" if "target_lat" in p else "deviate")
    nn, ee = tr.noise()
    idx = np.flatnonzero(m)
    t = tr.t[idx]
    lat0, lon0 = tr.label_true_lat[idx[0]], tr.label_true_lon[idx[0]]
    if mode == "deviate":
        # the asset really leaves its route: a smooth lateral excursion and back
        dur = t_end - onset
        lateral = p.setdefault("lateral_mps", 1.5)
        ramp = min(
            p.setdefault("offset_m", float(rng.uniform(30, 120))) / lateral, dur / 3
        )
        p["offset_m"] = ramp * lateral
        if "course_deg" not in p:
            _, crs = _recompute_motion(
                tr.t, tr.label_true_lat, tr.label_true_lon, np.random.default_rng(0)
            )
            p["course_deg"] = float(crs[idx[0]])
        az = np.radians(
            p["course_deg"] + p.setdefault("side", float(rng.choice([-90.0, 90.0])))
        )
        w = _smoothstep((t - onset) / ramp) * _smoothstep((t_end - t) / ramp)
        north, east = p["offset_m"] * w * np.cos(az), p["offset_m"] * w * np.sin(az)
        new_lat, new_lon = _offset(
            tr.label_true_lat[idx], tr.label_true_lon[idx], north, east
        )
    elif mode == "incursion":
        if "target_lat" not in p:
            if layers is None:
                raise ValueError("incursion needs target_lat/target_lon or layers")
            x, y = to_metric([lon0], [lat0])
            pt = shapely.points(x[0], y[0])
            lines = layers.runway_lines.geometry
            near = lines.iloc[int(np.argmin(lines.distance(pt)))]
            q = near.interpolate(near.project(pt))
            tlon, tlat = to_wgs84([q.x], [q.y])
            p["target_lat"], p["target_lon"] = float(tlat[0]), float(tlon[0])
        v = p.setdefault("speed_mps", 0.7 * _class_speed(tr.asset_class))
        after = np.searchsorted(tr.t, t_end)
        j = min(after, len(tr.t) - 1)
        lat1, lon1 = tr.label_true_lat[j], tr.label_true_lon[j]
        _, _, d_in = _GEOD.inv(lon0, lat0, p["target_lon"], p["target_lat"])
        _, _, d_out = _GEOD.inv(p["target_lon"], p["target_lat"], lon1, lat1)
        # smoothstep peaks at 1.5 x mean speed: travel time keeps the peak at v
        t_in, t_out = 1.5 * d_in / v, 1.5 * d_out / v
        scale = min(1.0, (t_end - onset) / max(t_in + t_out, 1e-9))
        t_in, t_out = t_in * scale, t_out * scale
        u_in = _smoothstep((t - onset) / max(t_in, 1e-9))
        u_out = _smoothstep((t - (t_end - t_out)) / max(t_out, 1e-9))
        new_lat = (
            lat0 + (p["target_lat"] - lat0) * u_in + (lat1 - p["target_lat"]) * u_out
        )
        new_lon = (
            lon0 + (p["target_lon"] - lon0) * u_in + (lon1 - p["target_lon"]) * u_out
        )
    else:
        raise ValueError(f"unknown behavioral_anomaly mode {mode!r}")
    tr.label_true_lat[idx], tr.label_true_lon[idx] = new_lat, new_lon
    tr.lat[idx], tr.lon[idx] = _offset(new_lat, new_lon, nn[idx], ee[idx])
    gs, crs = _recompute_motion(tr.t, tr.label_true_lat, tr.label_true_lon, rng)
    upd = np.clip(np.concatenate([idx, [idx[-1] + 1]]), 0, len(tr.t) - 1)
    moving = gs[upd] >= params.MOVING_MPS
    tr.gs_mps[upd] = gs[upd]
    tr.track_deg[upd] = np.where(moving, crs[upd], tr.track_deg[upd])
    tr.heading_deg[upd] = np.where(
        moving & ~np.isnan(tr.heading_deg[upd]), crs[upd], tr.heading_deg[upd]
    )
    if "zone_wkt" in p:
        # labeled from the moment the true position enters the zone
        zone = shapely.from_wkt(p["zone_wkt"])
        inside = shapely.contains_xy(
            zone, tr.label_true_lon[idx], tr.label_true_lat[idx]
        )
        first = np.flatnonzero(inside)
        p["entry_t"] = float(t[first[0]]) if len(first) else float(onset)
        m = m & (tr.t >= p["entry_t"])
    tr.label |= m


_HANDLERS = {
    "degraded": _degraded,
    "technical_error": _technical_error,
    "gnss_anomaly": _gnss_anomaly,
    "possible_interference": _possible_interference,
    "possible_spoofing": _possible_spoofing,
    "behavioral_anomaly": _behavioral_anomaly,
}


def _region_metric(region):
    return shapely.transform(
        region, lambda c: np.column_stack(to_metric(c[:, 0], c[:, 1]))
    )


def apply_event(
    points: pd.DataFrame,
    cause: str,
    *,
    onset_t: float,
    duration_s: float,
    track_ids: list[str] | None = None,
    region=None,
    params: dict | None = None,
    seed: int = 0,
    event_id: str | None = None,
    layers=None,
) -> tuple[pd.DataFrame, dict]:
    """`inject` plus an events-table row describing what was applied."""
    if cause not in _HANDLERS:
        raise ValueError(f"cannot inject {cause!r}; choose from {sorted(_HANDLERS)}")
    p = dict(params or {})
    out = add_labels(points.reset_index(drop=True), p)
    for k in ("scene_id", "base_track_id"):
        p.pop(k, None)
    rng = np.random.default_rng([seed, schema.CAUSES.index(cause)])
    t_end = onset_t + duration_s
    event_id = event_id or f"ev_{cause}_{seed}_{int(onset_t)}"

    t_all = out["t"].to_numpy()
    active = (t_all >= onset_t) & (t_all < t_end)
    inside = np.ones(len(out), dtype=bool)
    sev_all = np.ones(len(out))
    if region is not None:
        rm = _region_metric(region)
        x, y = to_metric(
            out["label_true_lon"].to_numpy(), out["label_true_lat"].to_numpy()
        )
        inside = shapely.contains_xy(rm, x, y)
        radius = np.sqrt(rm.area / np.pi)
        c = rm.centroid
        d = np.hypot(x - c.x, y - c.y)
        sev_all = np.clip(1.0 - (d / radius) ** 2, 0.2, 1.0)  # fades toward the edge
    sel = active & inside
    if track_ids is not None:
        sel &= out["track_id"].isin(track_ids).to_numpy()
    elif region is None:
        raise ValueError("give track_ids or region")
    hit = list(dict.fromkeys(out.loc[sel, "track_id"]))  # stable order

    tracks_out = []
    drop_rows = []
    for tid in hit:
        rows = out.index[out["track_id"].to_numpy() == tid]
        g = out.loc[rows].sort_values(["t", "seq"], kind="stable")
        tr = _Track(g)
        pos = out.index.get_indexer(g.index)
        m = sel[pos]
        if cause == "possible_interference":
            _possible_interference(
                tr, m, onset_t, t_end, rng, p, severity=sev_all[pos][m]
            )
        elif cause == "behavioral_anomaly":
            _behavioral_anomaly(tr, m, onset_t, t_end, rng, p, layers=layers)
        else:
            _HANDLERS[cause](tr, m, onset_t, t_end, rng, p)
        tracks_out.append(tr)
        drop_rows.extend(tr.index[tr.drop])

    onset_label = p.get("entry_t", onset_t)
    for tr in tracks_out:
        for c in _Track.COLS:
            out.loc[tr.index, c] = getattr(tr, c)
        lab = tr.label & ~tr.drop
        out.loc[tr.index[lab], "label_cause"] = cause
        out.loc[tr.index[lab], "label_event_id"] = event_id
        out.loc[tr.index[tr.t >= onset_label], "label_onset_t"] = onset_label
    out = schema.coerce_points(out.drop(index=drop_rows), labeled=True)

    labeled = out["label_event_id"] == event_id
    affected = list(dict.fromkeys(out.loc[labeled.fillna(False), "track_id"]))
    info = {
        "event_id": event_id,
        "cause": cause,
        "t_onset": float(onset_label),
        "t_end": float(t_end),
        "track_ids": affected,
        "region_wkt": None if region is None else region.wkt,
        "params_json": json.dumps(p, sort_keys=True, default=float),
    }
    return out, info


def inject(
    points: pd.DataFrame,
    cause: str,
    *,
    onset_t: float,
    duration_s: float,
    track_ids: list[str] | None = None,
    region=None,
    params: dict | None = None,
    seed: int = 0,
    event_id: str | None = None,
    layers=None,
) -> pd.DataFrame:
    """Pure: returns a new frame with the anomaly applied and labels set. Never mutates its input."""
    out, _ = apply_event(
        points,
        cause,
        onset_t=onset_t,
        duration_s=duration_s,
        track_ids=track_ids,
        region=region,
        params=params,
        seed=seed,
        event_id=event_id,
        layers=layers,
    )
    return out
