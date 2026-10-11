"""Window grid and slice aggregation (specs/00_contracts.md section 4).

Fixes are sorted by (track, t). A window (t_end - WINDOW_S, t_end] of one
track is then a contiguous slice [lo, hi) of that order, and so is the
trailing baseline (t_start - BASELINE_S, t_start]. Every window aggregate is
a reduction over such slices: sums through prefix sums, max/min through the
exploded member list, medians through pandas' rolling median with explicit
(monotone) bounds. No Python loop over windows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.api.indexers import BaseIndexer

from divas_air import config, params


@dataclass
class Grid:
    """Windows of a set of sorted tracks.

    `w_track` is the track code of each window, `t_end` its grid time,
    [lo, hi) its fixes, [blo, lo) its baseline fixes.
    """

    w_track: np.ndarray
    t_end: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    blo: np.ndarray
    first_window: np.ndarray  # per track: index of its first window
    n_windows: np.ndarray  # per track
    g_first: np.ndarray  # per track: first grid time

    @property
    def n(self) -> int:
        return len(self.t_end)


def build_grid(code: np.ndarray, t: np.ndarray, until: float | None = None) -> Grid:
    """`code` (track code, 0..K-1, non-decreasing) and `t` sorted within each track.

    `until`: extend every track's grid to the first grid time at or after it (the
    online engine's clock), so a track silent for more than a stride still gets
    its window at the current time. None: grid ends at each track's last fix."""
    stride, width = float(config.STRIDE_S), float(config.WINDOW_S)
    starts = np.flatnonzero(np.r_[True, code[1:] != code[:-1]])
    ends = np.r_[starts[1:], len(code)]
    g_first = np.ceil(t[starts] / stride) * stride
    g_last = np.ceil(t[ends - 1] / stride) * stride
    if until is not None:
        g_last = np.maximum(g_last, np.ceil(until / stride) * stride)
    n_w = np.rint((g_last - g_first) / stride).astype(np.int64) + 1
    first = np.r_[0, np.cumsum(n_w)[:-1]]
    w_track = np.repeat(np.arange(len(starts)), n_w)
    k = np.arange(n_w.sum()) - np.repeat(first, n_w)
    t_end = np.repeat(g_first, n_w) + stride * k

    lo = np.empty(len(t_end), np.int64)
    hi = np.empty(len(t_end), np.int64)
    blo = np.empty(len(t_end), np.int64)
    # one searchsorted per track (not per window): bounds stay inside the track
    for i, (s, e) in enumerate(zip(starts, ends, strict=True)):
        ws = slice(first[i], first[i] + n_w[i])
        tt = t[s:e]
        te = t_end[ws]
        lo[ws] = s + np.searchsorted(tt, te - width, side="right")
        hi[ws] = s + np.searchsorted(tt, te, side="right")
        blo[ws] = s + np.searchsorted(tt, te - width - params.BASELINE_S, side="right")
    return Grid(w_track, t_end, lo, hi, blo, first, n_w, g_first)


class _Bounds(BaseIndexer):
    def __init__(self, lo: np.ndarray, hi: np.ndarray):
        super().__init__()
        self.lo, self.hi = lo, hi

    def get_window_bounds(
        self, num_values=0, min_periods=None, center=None, closed=None, step=None
    ):
        lo = np.zeros(num_values, np.int64)
        hi = np.zeros(num_values, np.int64)
        lo[: len(self.lo)] = self.lo
        hi[: len(self.hi)] = self.hi
        return lo, hi


class Slices:
    """Aggregations of per-fix arrays over the slices [lo, hi) (lo and hi non-decreasing)."""

    def __init__(self, lo: np.ndarray, hi: np.ndarray):
        self.lo, self.hi = lo, hi
        self.length = hi - lo
        nz = self.length > 0
        self.nonempty = nz
        lens = self.length[nz]
        self.starts = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
        # members: the fix index of every (window, fix) membership, grouped by window
        self.members = np.repeat(lo[nz] - self.starts, lens) + np.arange(
            lens.sum(), dtype=np.int64
        )
        self.member_window = np.repeat(np.flatnonzero(nz), lens)

    def _reduce(self, ufunc, v: np.ndarray, empty=np.nan) -> np.ndarray:
        out = np.full(len(self.lo), empty, dtype="float64")
        if len(self.members):
            out[self.nonempty] = ufunc.reduceat(
                v[self.members].astype("float64"), self.starts
            )
        return out

    def max(self, v) -> np.ndarray:
        return self._reduce(np.fmax, np.asarray(v, dtype="float64"))

    def min(self, v) -> np.ndarray:
        return self._reduce(np.fmin, np.asarray(v, dtype="float64"))

    def count(self, v=None) -> np.ndarray:
        """Non-NaN values per slice (all fixes if v is None)."""
        if v is None:
            return self.length.astype("float64")
        return self._reduce(
            np.add, np.isfinite(np.asarray(v, dtype="float64")).astype("float64"), 0.0
        )

    def sum(self, v) -> np.ndarray:
        v = np.asarray(v, dtype="float64")
        return self._reduce(np.add, np.where(np.isnan(v), 0.0, v), 0.0)

    def mean(self, v) -> np.ndarray:
        n = self.count(v)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n > 0, self.sum(v) / n, np.nan)

    def median(self, v) -> np.ndarray:
        """NaN-skipping median per slice; NaN for an empty or all-NaN slice."""
        v = np.asarray(v, dtype="float64")
        n = max(len(v), len(self.lo))
        s = pd.Series(np.r_[v, np.full(n - len(v), np.nan)])
        out = s.rolling(_Bounds(self.lo, self.hi), min_periods=1).median().to_numpy()
        return out[: len(self.lo)]

    def argmax(self, v) -> np.ndarray:
        """Fix index of the largest non-NaN value per slice (latest on ties); -1 if none."""
        v = np.asarray(v, dtype="float64")
        m = self.max(v)
        out = np.full(len(self.lo), -1, dtype=np.int64)
        if not len(self.members):
            return out
        hit = v[self.members] == m[self.member_window]
        cand = np.where(hit, self.members, -1)
        out[self.nonempty] = np.maximum.reduceat(cand, self.starts)
        return out
