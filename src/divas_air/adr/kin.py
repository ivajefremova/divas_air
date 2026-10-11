"""Per-sample kinematics shared by the ADR detectors.

Rows are grouped by track and sorted by time. A segment is a run of a track
without a pause longer than `GAP_S`; every base window stays inside one
segment. Positions are a local east/north frame per track built with
`pyproj.Geod` (azimuthal equidistant around the track's first fix, so
distances between fixes are geodesic to well under a centimetre at airport scale).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pyproj import Geod

from divas_air.adr import tunables as T

GEOD = Geod(ellps="WGS84")


@dataclass
class Kin:
    t: np.ndarray
    x: np.ndarray  # east, m
    y: np.ndarray  # north, m
    code: np.ndarray  # track code
    seg: np.ndarray  # segment code (track split at gaps)
    first: np.ndarray  # True on the first row of a segment
    dt_prev: (
        np.ndarray
    )  # seconds since the previous row of the same track (inf at start)
    key: np.ndarray

    @property
    def n(self) -> int:
        return len(self.t)

    def back(self, b: float) -> np.ndarray:
        """Latest row j of the same segment with t_j <= t_i - b, else -1."""
        j = np.searchsorted(self.key, self.key - b, side="right") - 1
        j0 = np.maximum(j, 0)
        return np.where((j >= 0) & (self.seg[j0] == self.seg), j, -1)

    def fwd(self, b: float) -> np.ndarray:
        """Earliest row j of the same segment with t_j >= t_i + b, else -1."""
        j = np.searchsorted(self.key, self.key + b, side="left")
        j0 = np.minimum(j, self.n - 1)
        return np.where((j < self.n) & (self.seg[j0] == self.seg), j, -1)

    def disp(self, a: np.ndarray, b: np.ndarray):
        """(dx, dy, dt) from row a to row b; NaN where either is -1."""
        ok = (a >= 0) & (b >= 0)
        a0, b0 = np.where(ok, a, 0), np.where(ok, b, 0)
        nan = np.where(ok, 1.0, np.nan)
        return (
            (self.x[b0] - self.x[a0]) * nan,
            (self.y[b0] - self.y[a0]) * nan,
            (self.t[b0] - self.t[a0]) * nan,
        )

    def centered(self):
        """Displacement over the centered window [t - 2.5 s, t + 2.5 s] (>= RATE_BASE_S)."""
        h = T.RATE_BASE_S / 2
        a, b = self.back(h), self.fwd(h)
        dx, dy, dt = self.disp(a, b)
        dt = np.where(dt >= T.RATE_BASE_S - 1e-9, dt, np.nan)
        return dx, dy, dt, a, b


def kinematics(p: pd.DataFrame) -> Kin:
    """`p` sorted by (track_id, t)."""
    code = pd.factorize(p["track_id"])[0].astype(np.int64)
    t = p["t"].to_numpy(dtype="float64")
    lat = p["lat"].to_numpy(dtype="float64")
    lon = p["lon"].to_numpy(dtype="float64")
    n = len(p)
    start = np.r_[True, code[1:] != code[:-1]] if n else np.zeros(0, bool)
    first_idx = np.maximum.accumulate(np.where(start, np.arange(n), 0))
    az, _, d = GEOD.inv(lon[first_idx], lat[first_idx], lon, lat)
    az = np.radians(az)
    dt_prev = np.r_[np.inf, np.diff(t)] if n else np.zeros(0)
    dt_prev[start] = np.inf
    newseg = start | (dt_prev > T.GAP_S)
    seg = np.cumsum(newseg) - 1
    # t is < 1e10 (UNIX seconds), so seg * 1e10 + t is sorted and separates segments
    key = seg.astype("float64") * 1e10 + t
    return Kin(
        t=t,
        x=d * np.sin(az),
        y=d * np.cos(az),
        code=code,
        seg=seg,
        first=newseg,
        dt_prev=dt_prev,
        key=key,
    )


def runs(mask: np.ndarray, group: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(start, end) row indices (end exclusive) of runs of True inside each group."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return np.zeros(0, int), np.zeros(0, int)
    brk = np.r_[True, group[1:] != group[:-1]]
    starts = np.flatnonzero(m & (brk | ~np.r_[False, m[:-1]]))
    ends_mask = m & (np.r_[brk[1:], True] | ~np.r_[m[1:], False])
    ends = np.flatnonzero(ends_mask) + 1
    return starts, ends


def keep_long_runs(mask: np.ndarray, group: np.ndarray, min_len: int) -> np.ndarray:
    """mask restricted to runs of at least `min_len` rows."""
    s, e = runs(mask, group)
    out = np.zeros(len(mask), dtype=bool)
    for a, b in zip(s[(e - s) >= min_len], e[(e - s) >= min_len], strict=True):
        out[a:b] = True
    return out


def run_id(mask: np.ndarray, group: np.ndarray) -> np.ndarray:
    """Run number per row (-1 outside runs)."""
    s, e = runs(mask, group)
    out = np.full(len(mask), -1, dtype=np.int64)
    if len(s):
        lens = e - s
        idx = np.repeat(np.arange(len(s)), lens)
        pos = np.concatenate([np.arange(a, b) for a, b in zip(s, e, strict=True)])
        out[pos] = idx
    return out


def count_in(mask: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Number of True rows in [a, b] (inclusive); 0 where a or b is -1."""
    c = np.r_[0, np.cumsum(np.asarray(mask, dtype=np.int64))]
    ok = (a >= 0) & (b >= 0)
    a0, b0 = np.where(ok, a, 0), np.where(ok, b, 0)
    return np.where(ok, c[b0 + 1] - c[a0], 0)
