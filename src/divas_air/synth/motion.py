"""Base motion and nominal noise for ground assets (specs/02_generator.md sections 1-2).

A trajectory is a dense, time-stamped true path in CRS_METRIC built from route
graph legs (speed profile inside the class envelope) and dwells. Assets sample
it at their own reporting interval; reported = true + Gauss-Markov error whose
scale follows building obstruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from itertools import pairwise

import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Geod
from scipy.ndimage import uniform_filter1d

from divas_air import config, params
from divas_air.geo import gnss

_GEOD = Geod(ellps="WGS84")
RESAMPLE_M = 2.0  # spacing of the dense path
SMOOTH_PTS = 7  # moving average over the dense path (~12 m): rounds route corners
SPEED_FLOOR = 0.05


@lru_cache(maxsize=1)
def envelopes() -> pd.DataFrame:
    return pd.read_csv(config.REFERENCE / "envelopes.csv").set_index("category")


def not_held_out(t: pd.Series) -> np.ndarray:
    """False on the last REAL_HOLDOUT_DAYS UTC days present in `t` (real `fco` holdout)."""
    day = np.floor(t.to_numpy(dtype="float64") / 86400.0)
    return day <= day.max() - params.REAL_HOLDOUT_DAYS


@lru_cache(maxsize=1)
def fco_intervals() -> np.ndarray:
    """Empirical reporting intervals of real `fco` aircraft (non-held-out days), seconds.

    Falls back to a log-normal with median 2.7 s if `points/fco.parquet` does not exist.
    """
    path = config.PROCESSED / "points" / "fco.parquet"
    if not path.exists():
        rng = np.random.default_rng(params.SEED)
        return np.exp(rng.normal(np.log(2.7), 0.6, 20000))
    p = pd.read_parquet(path, columns=["track_id", "t"])
    p = p[not_held_out(p["t"])].sort_values(["track_id", "t"])
    d = p.groupby("track_id")["t"].diff().dropna().to_numpy()
    return np.sort(d[(d >= 0.5) & (d <= 20.0)])


# --- route graph -------------------------------------------------------------


@dataclass
class RouteNet:
    """One domain's drivable graph with per-edge geometry and speed cap."""

    graph: nx.MultiGraph
    xy: dict = field(default_factory=dict)  # node -> (x, y)

    @classmethod
    def build(cls, layers, domain: str) -> RouteNet:
        g = nx.MultiGraph(layers.routes[domain])
        zones = layers.zones
        if domain == "vehicle":
            # no plausible vehicle route crosses a runway; drop such edges
            rw = zones[zones["zone_type"] == "runway"].union_all()
            bad = [
                (u, v, k)
                for u, v, k, d in g.edges(keys=True, data=True)
                if d["geometry"].intersects(rw)
            ]
            g.remove_edges_from(bad)
            sr = zones[zones["zone_type"] == "service_road"].dropna(
                subset=["speed_limit_mps"]
            )
        for u, v, k, d in g.edges(keys=True, data=True):
            cap = np.inf
            kmh = pd.to_numeric(d.get("maxspeed_kmh"), errors="coerce")
            if pd.notna(kmh):
                cap = float(kmh) / 3.6
            if domain == "vehicle" and len(sr):
                mid = d["geometry"].interpolate(0.5, normalized=True)
                lim = sr.loc[sr.contains(mid), "speed_limit_mps"]
                if len(lim):
                    cap = min(cap, float(lim.min()))
            d["cap_mps"] = cap
        g.remove_nodes_from(list(nx.isolates(g)))
        main = max(nx.connected_components(g), key=lambda c: (len(c), min(c)))
        g = nx.MultiGraph(g.subgraph(sorted(main)))
        xy = {n: (d["x"], d["y"]) for n, d in g.nodes(data=True)}
        return cls(graph=g, xy=xy)

    def nodes_array(self) -> tuple[list, np.ndarray]:
        nodes = list(self.graph.nodes)
        return nodes, np.array([self.xy[n] for n in nodes])

    def nearest_node(self, x: float, y: float):
        nodes, arr = self.nodes_array()
        return nodes[int(np.argmin(np.hypot(arr[:, 0] - x, arr[:, 1] - y)))]

    def leg(self, a, b) -> tuple[np.ndarray, np.ndarray]:
        """Shortest path a->b: polyline (N, 2) and the speed cap of each vertex."""
        path = nx.shortest_path(self.graph, a, b, weight="length_m")
        pts, caps = [np.array([self.xy[a]])], [np.array([np.inf])]
        for u, v in pairwise(path):
            d = min(
                self.graph.get_edge_data(u, v).values(), key=lambda e: e["length_m"]
            )
            c = np.asarray(d["geometry"].coords)[:, :2]
            if np.hypot(*(c[0] - self.xy[u])) > np.hypot(*(c[-1] - self.xy[u])):
                c = c[::-1]
            pts.append(c[1:])
            caps.append(np.full(len(c) - 1, d["cap_mps"]))
        return np.vstack(pts), np.concatenate(caps)


# --- speed profile -----------------------------------------------------------


def speed_profile(poly: np.ndarray, caps: np.ndarray, asset_class: str, v_max: float):
    """Dense path through `poly` with a speed profile inside the class envelope.

    Returns (t, x, y, v) with t starting at 0, v = 0 at both ends.
    """
    env = envelopes().loc[asset_class]
    seg = np.hypot(*np.diff(poly, axis=0).T)
    keep = np.concatenate([[True], seg > 1e-6])
    poly, caps = poly[keep], caps[keep]
    s_v = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(poly, axis=0).T))])
    total = s_v[-1]
    n = max(int(np.ceil(total / RESAMPLE_M)) + 1, 3)
    s = np.linspace(0.0, total, n)
    x = np.interp(s, s_v, poly[:, 0])
    y = np.interp(s, s_v, poly[:, 1])
    cap = caps[np.clip(np.searchsorted(s_v, s, side="right") - 1, 0, len(caps) - 1)]
    if n > SMOOTH_PTS:
        x[1:-1] = uniform_filter1d(x, SMOOTH_PTS, mode="nearest")[1:-1]
        y[1:-1] = uniform_filter1d(y, SMOOTH_PTS, mode="nearest")[1:-1]
    ds = np.maximum(np.hypot(np.diff(x), np.diff(y)), 1e-6)
    s = np.concatenate([[0.0], np.cumsum(ds)])

    a_max = 0.5 * float(env["max_accel_mps2"])
    heading = np.unwrap(np.arctan2(np.gradient(y), np.gradient(x)))
    kappa = uniform_filter1d(
        np.abs(np.gradient(heading) / np.gradient(s)), 5, mode="nearest"
    )
    kappa = np.maximum(kappa, 1e-6)
    turn = 0.6 * np.radians(float(env["max_turn_rate_dps"]))
    v_lim = np.minimum.reduce(
        [np.full(n, v_max), cap, turn / kappa, np.sqrt(a_max / kappa)]
    )
    v_lim[0] = v_lim[-1] = 0.0
    # acceleration limit, both directions: v^2[i] = min_j<=i (v_lim^2[j] + 2a (s_i - s_j))
    fwd = 2 * a_max * s + np.minimum.accumulate(v_lim**2 - 2 * a_max * s)
    sb = (s[-1] - s)[::-1]  # distance to the end, walking backwards
    bwd = (2 * a_max * sb + np.minimum.accumulate(v_lim[::-1] ** 2 - 2 * a_max * sb))[
        ::-1
    ]
    v = np.sqrt(np.maximum(np.minimum(fwd, bwd), 0.0))
    dt = 2 * ds / np.maximum(v[:-1] + v[1:], SPEED_FLOOR)
    t = np.concatenate([[0.0], np.cumsum(dt)])
    return t, x, y, v


@dataclass
class Trajectory:
    """Dense true path: monotone t, metric x, y and speed v."""

    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    v: np.ndarray

    @classmethod
    def concat(cls, pieces: list[tuple]) -> Trajectory:
        t, x, y, v = (np.concatenate([p[i] for p in pieces]) for i in range(4))
        # drop non-increasing times at piece joints
        keep = np.concatenate([[True], np.diff(t) > 1e-9])
        return cls(t[keep], x[keep], y[keep], v[keep])

    def sample(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return (
            np.interp(ts, self.t, self.x),
            np.interp(ts, self.t, self.y),
            np.interp(ts, self.t, self.v),
        )


def drive(
    net: RouteNet,
    asset_class: str,
    rng,
    *,
    t_start: float,
    t_stop: float,
    start_node,
    pick_dest,
    dwell=(5.0, 60.0),
    v_frac=(0.5, 0.85),
    stops=None,
) -> Trajectory:
    """Chain legs and dwells from `start_node` until `t_stop`.

    `pick_dest(node, rng)` returns the next destination. `stops` optionally forces
    the first legs: a list of (node, dwell_s) visited in order.
    """
    v_max = float(envelopes().loc[asset_class, "max_ground_speed_mps"]) * rng.uniform(
        *v_frac
    )
    pieces = []
    t = t_start
    node = start_node
    x0, y0 = net.xy[node]
    queue = list(stops or [])
    while t < t_stop:
        if queue:
            dest, hold = queue.pop(0)
        else:
            dest, hold = pick_dest(node, rng), rng.uniform(*dwell)
        if dest != node:
            poly, caps = net.leg(node, dest)
            if len(poly) >= 2 and np.hypot(*(poly[-1] - poly[0])) > 1.0:
                lt, lx, ly, lv = speed_profile(poly, caps, asset_class, v_max)
                pieces.append((t + lt, lx, ly, lv))
                t += lt[-1]
                x0, y0 = lx[-1], ly[-1]
            node = dest
        pieces.append(
            (
                np.array([t, t + hold]),
                np.array([x0, x0]),
                np.array([y0, y0]),
                np.zeros(2),
            )
        )
        t += hold
    return Trajectory.concat(pieces)


# --- sampling and reported fields --------------------------------------------


def sample_times(
    rng, domain: str, t0: float, t1: float, *, full_span: bool = False
) -> np.ndarray:
    """Report times in [t0, t1]: vehicles every 1 or 2 s, aircraft at empirical fco intervals.

    full_span: the asset also reports at t0 and t1 (demo: every frame has every asset).
    """
    if domain == "vehicle":
        dt = float(rng.choice([1.0, 2.0]))
        ts = t0 + rng.uniform(0, dt) + dt * np.arange(int((t1 - t0) / dt) + 1)
        ts = ts + rng.uniform(-params.T_JITTER_S, params.T_JITTER_S, len(ts))
    else:
        iv = fco_intervals()
        n = int((t1 - t0) / 0.5) + 10
        ts = t0 + rng.uniform(0, 3.0) + np.cumsum(rng.choice(iv, n))
    ts = ts[(ts >= t0) & (ts <= t1)]
    if full_span:
        ts = np.concatenate([[t0], ts[(ts > t0 + 0.5) & (ts < t1 - 0.5)], [t1]])
    return np.sort(ts)


def report(traj: Trajectory, ts: np.ndarray, layers, rng) -> dict:
    """True and reported fields at times `ts`."""
    x, y, v = traj.sample(ts)
    lon, lat = layers.to_wgs84(x, y)
    # course from the dense path, true north (geodesic azimuth, not grid bearing)
    dlon, dlat = layers.to_wgs84(traj.x, traj.y)
    az, _, step = _GEOD.inv(dlon[:-1], dlat[:-1], dlon[1:], dlat[1:])
    az = np.where(step > 0.01, az, np.nan)
    az = (
        pd.Series(np.concatenate([az, [np.nan]])).ffill().bfill().fillna(0.0).to_numpy()
    )
    crs = np.mod(np.degrees(np.interp(ts, traj.t, np.unwrap(np.radians(az)))), 360.0)

    sigma = gnss.sigma_m(layers.building_elevation_deg(x, y))
    tau = rng.uniform(*params.GNSS_TAU_S)
    white = params.GNSS_WHITE_FRAC
    ex = sigma * (
        gnss.gauss_markov(ts, tau, rng) + white * rng.standard_normal(len(ts))
    )
    ey = sigma * (
        gnss.gauss_markov(ts, tau, rng) + white * rng.standard_normal(len(ts))
    )
    rlon, rlat = layers.to_wgs84(x + ex, y + ey)
    nacp, nic = gnss.integrity_from_sigma(sigma)

    gs = np.maximum(v + rng.normal(0, params.SPEED_NOISE_MPS, len(ts)), 0.0)
    gs[v < SPEED_FLOOR] = 0.0
    track = np.mod(crs + rng.normal(0, params.COURSE_NOISE_DEG, len(ts)), 360.0)
    track[track >= 360.0] = 0.0
    return {
        "t": ts,
        "lat": rlat,
        "lon": rlon,
        "label_true_lat": lat,
        "label_true_lon": lon,
        "gs_mps": gs,
        "track_deg": track,
        "heading_deg": track,
        "nacp": nacp,
        "nic": nic,
        "sil": np.full(len(ts), 3.0),
    }
