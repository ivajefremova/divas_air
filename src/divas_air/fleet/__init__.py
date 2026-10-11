"""Fleet layer (specs/05_fleet.md): area degradation from many tracks at once.

Two profiles (params.FleetProfile):

- regional: the GPSJam reproduction (`scripts/gpsjam_repro.py`). H3 cell x UTC
  day; an aircraft is degraded in a cell-day if the majority of its readings
  there are degraded.
- apron: online and causal. At every grid time each present track sits in the
  H3 cell of its latest window and counts as degraded if that window is
  degraded. Leave-one-out features let the model tell "one track alone" from
  "many tracks together".
"""

from __future__ import annotations

import h3
import numpy as np
import pandas as pd
import shapely
from scipy.stats import binom

from divas_air import config, params, registry, schema
from divas_air.degradation import is_degraded_reading
from divas_air.params import FleetProfile

KEYS = list(schema.WINDOW_KEYS)
MAJORITY = 0.5  # degraded in a cell if MORE than this share of its readings are


def cells_of(lat, lon, res: int) -> np.ndarray:
    """H3 cell id (string) of each position; None where the position is missing."""
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    ok = np.isfinite(lat) & np.isfinite(lon)
    out = np.full(len(lat), None, dtype=object)
    out[ok] = [
        h3.latlng_to_cell(a, b, res) for a, b in zip(lat[ok], lon[ok], strict=True)
    ]
    return out


def cell_polygon(cells) -> shapely.Geometry:
    """Union of H3 cells as a WGS84 (lon, lat) shapely geometry."""
    polys = [
        shapely.Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)])
        for c in cells
    ]
    return shapely.union_all(polys)


# --- regional profile ----------------------------------------------------------------


def cells_from_points(
    points: pd.DataFrame, profile: FleetProfile = params.REGIONAL
) -> pd.DataFrame:
    """Qualifying cell-bins: cell, bin_start, n_tracks, n_degraded, share, level, flagged.

    Follows the reference script: airborne readings only; when no `degraded`
    column is given, readings without NACp are dropped and only aircraft that
    reported NACp >= 8 at some point that day are eligible. Counts are aircraft
    (`asset_id`), not track segments.
    """
    p = points
    if "on_ground" in p:
        p = p[~p["on_ground"].astype("boolean").fillna(False).to_numpy(dtype=bool)]
    if "degraded" in p:
        degraded = p["degraded"].astype(bool).to_numpy()
    else:
        # NACp is sent only when it changes: the reference forward-fills it per
        # aircraft over the day, across track segments (offline, so not causal)
        p = p.sort_values(["asset_id", "t"], kind="stable")
        nacp = (
            pd.to_numeric(p["nacp"], errors="coerce")
            .groupby(p["asset_id"].to_numpy())
            .ffill()
        )
        p = p.assign(nacp=nacp)
        good_ever = nacp.groupby(p["asset_id"].to_numpy()).transform("max")
        keep = (nacp.notna() & (good_ever >= params.DEGRADED_ELIGIBLE_NACP)).to_numpy()
        p = p[keep]
        degraded = is_degraded_reading(p).to_numpy()
    r = pd.DataFrame(
        {
            "cell": cells_of(p["lat"], p["lon"], profile.h3_res),
            "bin_start": np.floor(p["t"].to_numpy(dtype="float64") / profile.bin_s)
            * profile.bin_s,
            "asset_id": p["asset_id"].astype(str).to_numpy(),
            "low": degraded,
        }
    )
    frac = r.groupby(["cell", "bin_start", "asset_id"], sort=True)["low"].mean()
    per = (frac > MAJORITY).rename("bad").reset_index()
    out = (
        per.groupby(["cell", "bin_start"], sort=True)["bad"]
        .agg(n_degraded="sum", n_tracks="size")
        .reset_index()
    )
    out = out[out["n_tracks"] >= profile.min_tracks].reset_index(drop=True)
    out["n_tracks"] = out["n_tracks"].astype("int64")
    out["n_degraded"] = out["n_degraded"].astype("int64")
    out["share"] = out["n_degraded"] / out["n_tracks"]
    out["level"] = np.select(
        [out["share"] > profile.cell_share_min, out["share"] > profile.warn_share],
        ["red", "yellow"],
        default="green",
    ).astype(object)
    out["flagged"] = out["level"] == "red"
    return out[
        ["cell", "bin_start", "n_tracks", "n_degraded", "share", "level", "flagged"]
    ]


# --- apron profile -------------------------------------------------------------------


def _state(windows: pd.DataFrame, profile: FleetProfile) -> pd.DataFrame:
    """Per grid time, the latest window of every present track: track_id, t_end, cell, degraded.

    A window stays a track's latest state until its next window, for at most
    `bin_s` (presence span): a track is present at T if it has a window in
    (T - bin_s, T].
    """
    step = float(config.STRIDE_S)
    w = windows[["track_id", "t_end", "aux_lat", "aux_lon", "degraded"]].sort_values(
        KEYS, kind="stable"
    )
    w = w.drop_duplicates(KEYS, keep="last").reset_index(drop=True)
    tid = w["track_id"].to_numpy()
    t = w["t_end"].to_numpy(dtype="float64")
    same_next = np.r_[tid[1:] == tid[:-1], False]
    nxt = np.where(same_next, np.r_[t[1:], np.inf], np.inf)
    until = np.minimum(nxt, t + profile.bin_s)  # exclusive
    reps = np.maximum(np.ceil((until - t) / step - 1e-9).astype(np.int64), 1)
    idx = np.repeat(np.arange(len(w)), reps)
    k = np.arange(len(idx)) - np.repeat(np.cumsum(reps) - reps, reps)
    cell = cells_of(w["aux_lat"], w["aux_lon"], profile.h3_res)
    s = pd.DataFrame(
        {
            "track_id": tid[idx],
            "t_end": t[idx] + k * step,
            "cell": cell[idx],
            "degraded": w["degraded"].fillna(False).astype(bool).to_numpy()[idx],
            "own": k == 0,  # the input window itself, not a carried-forward state
        }
    )
    return s[s["cell"].notna()].reset_index(drop=True)


def _baseline_of(
    cells: pd.Series, baseline: pd.DataFrame | None, profile: FleetProfile
) -> np.ndarray:
    if baseline is None or len(baseline) == 0:
        return np.full(len(cells), profile.baseline_floor)
    b = cells.map(baseline.drop_duplicates("cell").set_index("cell")["baseline"])
    return np.maximum(
        b.fillna(profile.baseline_floor).to_numpy(dtype="float64"),
        profile.baseline_floor,
    )


def _flag(n, n_deg, base, profile: FleetProfile) -> tuple[np.ndarray, np.ndarray]:
    """(p_value, flagged) of the apron rule for counts n (tracks) and n_deg (degraded)."""
    n = np.asarray(n, dtype="int64")
    n_deg = np.asarray(n_deg, dtype="int64")
    share = np.divide(n_deg, n, out=np.zeros(len(n)), where=n > 0)
    p = binom.sf(n_deg - 1, n, base)  # P(X >= n_deg)
    flagged = (n >= profile.min_tracks) & (share > profile.cell_share_min)
    if profile.use_baseline_test:
        flagged &= p < profile.alpha
    return p, flagged


def _cell_counts(
    state: pd.DataFrame, profile: FleetProfile, baseline: pd.DataFrame | None
) -> pd.DataFrame:
    c = (
        state.groupby(["cell", "t_end"], sort=True)["degraded"]
        .agg(n_tracks="size", n_degraded="sum")
        .reset_index()
    )
    c["n_tracks"] = c["n_tracks"].astype("int64")
    c["n_degraded"] = c["n_degraded"].astype("int64")
    c["share"] = c["n_degraded"] / c["n_tracks"]
    c["baseline"] = _baseline_of(c["cell"], baseline, profile)
    c["p_value"], c["flagged"] = _flag(
        c["n_tracks"], c["n_degraded"], c["baseline"], profile
    )
    return c


def cells_from_windows(
    windows: pd.DataFrame,
    profile: FleetProfile = params.APRON,
    baseline: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apron cell table: cell, t_end, n_tracks, n_degraded, share, baseline, p_value, flagged."""
    return _cell_counts(_state(windows, profile), profile, baseline)


def apron_baseline(
    windows: pd.DataFrame, profile: FleetProfile = params.APRON
) -> pd.DataFrame:
    """Per-cell degraded rate over the given (clean) windows: cell, baseline (not floored)."""
    s = _state(windows, profile)
    s = s[s["own"]]
    b = s.groupby("cell", sort=True)["degraded"].mean().rename("baseline").reset_index()
    b["baseline"] = b["baseline"].astype("float64")
    return b


def _ring_table(cells, k: int, include_self: bool) -> pd.DataFrame:
    rows = []
    for c in cells:
        ring = h3.grid_disk(c, k) if include_self else h3.grid_ring(c, k)
        rows += [(c, n) for n in ring]
    return pd.DataFrame(rows, columns=["cell", "nbr"])


def fleet_features(
    windows: pd.DataFrame,
    profile: FleetProfile = params.APRON,
    baseline: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Keys + registry.FLEET_COLUMNS, one row per input row (input order).

    Leave-one-out: a track's own degradation never enters its own features.
    Rows without a position get NaN.
    """
    keys = windows[KEYS].reset_index(drop=True)
    out = keys.copy()
    for c in registry.FLEET_COLUMNS:
        out[c] = np.nan
    state = _state(windows, profile)
    if len(state) == 0:
        return out
    counts = _cell_counts(state, profile, baseline)
    ct = counts.set_index(["cell", "t_end"])
    pairs = counts[["cell", "t_end"]]
    ucells = pairs["cell"].unique()

    # totals over the cell and its k-ring, per (cell, t_end)
    disk = _ring_table(ucells, profile.k_ring, include_self=True)
    d = pairs.merge(disk, on="cell").merge(
        counts[["cell", "t_end", "n_tracks", "n_degraded"]].rename(
            columns={"cell": "nbr"}
        ),
        on=["nbr", "t_end"],
        how="inner",
    )
    disk_tot = d.groupby(["cell", "t_end"])[["n_tracks", "n_degraded"]].sum()

    # share of ring-1 neighbor cells flagged (the track is not in them)
    ring = _ring_table(ucells, 1, include_self=False)
    n_ring = ring.groupby("cell").size()
    r = pairs.merge(ring, on="cell").merge(
        counts.loc[counts["flagged"], ["cell", "t_end"]]
        .rename(columns={"cell": "nbr"})
        .assign(f=1),
        on=["nbr", "t_end"],
        how="inner",
    )
    nbr_flagged = r.groupby(["cell", "t_end"])["f"].sum()

    own = state[state["own"]].reset_index(drop=True)
    ix = pd.MultiIndex.from_arrays([own["cell"], own["t_end"]])
    deg_i = own["degraded"].to_numpy().astype("int64")
    n_others = disk_tot["n_tracks"].reindex(ix).to_numpy() - 1
    deg_others = disk_tot["n_degraded"].reindex(ix).to_numpy() - deg_i
    cell_n = ct["n_tracks"].reindex(ix).to_numpy() - 1
    cell_deg = ct["n_degraded"].reindex(ix).to_numpy() - deg_i
    _, cell_flag = _flag(
        cell_n, cell_deg, ct["baseline"].reindex(ix).to_numpy(), profile
    )
    nf = nbr_flagged.reindex(ix).fillna(0).to_numpy()
    feats = pd.DataFrame(
        {
            "track_id": own["track_id"].to_numpy(),
            "t_end": own["t_end"].to_numpy(),
            "flt_n_others": n_others.astype("float64"),
            "flt_deg_count_loo": deg_others.astype("float64"),
            "flt_deg_rate_loo": np.divide(
                deg_others, n_others, out=np.zeros(len(own)), where=n_others > 0
            ),
            "flt_cell_flagged_loo": cell_flag.astype("float64"),
            "flt_nbr_flagged_frac": nf / n_ring.reindex(own["cell"]).to_numpy(),
        }
    )
    merged = keys.merge(feats, on=KEYS, how="left")
    return merged[KEYS + registry.FLEET_COLUMNS]


# --- area alerts ---------------------------------------------------------------------


def _components(cells: list[str]) -> list[set[str]]:
    """Connected components of H3 cells (edge neighbors)."""
    left = set(cells)
    comps = []
    while left:
        seed = left.pop()
        comp, stack = {seed}, [seed]
        while stack:
            c = stack.pop()
            for n in h3.grid_ring(c, 1):
                if n in left:
                    left.remove(n)
                    comp.add(n)
                    stack.append(n)
        comps.append(comp)
    return sorted(comps, key=lambda s: (-len(s), min(s)))


def area_alerts(
    cells: pd.DataFrame, profile: FleetProfile = params.APRON
) -> pd.DataFrame:
    """One row per alert per grid time: area_alert_id, t_end, cells, share, n_tracks,
    n_degraded, flagged, geometry_wkt (WGS84).

    An alert is a connected component of flagged cells. It keeps its id while it
    overlaps the cells of an alert alive at the previous step, and is held (with
    its last cells, `flagged` False) for `bin_s` after its last flagged step.
    """
    cols = [
        "area_alert_id",
        "t_end",
        "cells",
        "share",
        "n_tracks",
        "n_degraded",
        "flagged",
        "geometry_wkt",
    ]
    f = cells[cells["flagged"].astype(bool)]
    if len(f) == 0:
        return pd.DataFrame(columns=cols)
    step = float(config.STRIDE_S)
    by_t = {t: list(g["cell"]) for t, g in f.groupby("t_end", sort=True)}
    counts = cells.set_index(["cell", "t_end"])[["n_tracks", "n_degraded"]]
    times = sorted(
        {t + k * step for t in by_t for k in range(int(np.ceil(profile.bin_s / step)))}
    )
    alive: dict[str, dict] = {}  # id -> {"cells": set, "last": t of last flag}
    rows = []
    for t in times:
        seen: dict[str, dict] = {}
        for comp in _components(by_t.get(t, [])):
            hits = sorted(a for a, s in alive.items() if s["cells"] & comp)
            aid = hits[0] if hits else f"area_{round(t)}_{min(comp)}"
            if aid in seen:  # two components overlap one alert: the larger keeps the id
                aid = f"area_{round(t)}_{min(comp)}"
            seen[aid] = {"cells": comp, "last": t, "flagged": True}
            for a in hits[1:]:
                alive.pop(a, None)  # merged into aid
        for a, s in alive.items():
            if a not in seen and t - s["last"] < profile.bin_s - 1e-9:
                seen[a] = {"cells": s["cells"], "last": s["last"], "flagged": False}
        alive = seen
        for a, s in sorted(alive.items()):
            ix = pd.MultiIndex.from_arrays([sorted(s["cells"]), [t] * len(s["cells"])])
            c = counts.reindex(ix)
            n = float(c["n_tracks"].sum())
            nd = float(c["n_degraded"].sum())
            rows.append(
                (
                    a,
                    t,
                    sorted(s["cells"]),
                    nd / n if n > 0 else 0.0,
                    n,
                    nd,
                    s["flagged"],
                    cell_polygon(s["cells"]).wkt,
                )
            )
    out = pd.DataFrame(rows, columns=cols)
    out["n_tracks"] = out["n_tracks"].astype("int64")
    out["n_degraded"] = out["n_degraded"].astype("int64")
    return out


def alert_members(
    windows: pd.DataFrame, alerts: pd.DataFrame, profile: FleetProfile = params.APRON
) -> pd.DataFrame:
    """Keys + area_alert_id for the input windows whose track sits in an alert's cells at t_end."""
    if len(alerts) == 0 or len(windows) == 0:
        return pd.DataFrame(
            {
                "track_id": pd.Series(dtype=object),
                "t_end": pd.Series(dtype="float64"),
                "area_alert_id": pd.Series(dtype=object),
            }
        )
    state = _state(windows, profile)
    own = state[state["own"]][["track_id", "t_end", "cell"]]
    a = (
        alerts[["area_alert_id", "t_end", "cells"]]
        .explode("cells")
        .rename(columns={"cells": "cell"})
    )
    m = own.merge(a, on=["cell", "t_end"], how="inner")
    return m.sort_values(KEYS + ["area_alert_id"]).drop_duplicates(KEYS)[
        KEYS + ["area_alert_id"]
    ]
