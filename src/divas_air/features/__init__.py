"""Feature layer (specs/03_features.md): one row per (track, t_end) window.

Real and synthetic tracks go through the same code. Rows are causal: a row at
t_end reads fixes with t <= t_end of its track, at most BUFFER_S back, plus
the dwell timer.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from divas_air import config, params, registry, schema
from divas_air.features import core, labels
from divas_air.features.windows import Slices, build_grid

if TYPE_CHECKING:
    from divas_air.geo import MapLayers

KEYS = list(schema.WINDOW_KEYS)
MAP_FEATURES = registry.columns("spatial", "contextual")
OUTPUT_COLUMNS = (
    KEYS + ["t_start"] + registry.FEATURE_COLUMNS + list(registry.AUX_COLUMNS)
)
CHUNK_FIXES = 400_000  # tracks are processed in chunks of about this many fixes


def compute_features(
    points: pd.DataFrame, layers: MapLayers | None = None
) -> pd.DataFrame:
    """Per-window features for every track in `points`. layers=None: spatial and
    contextual features and the aux_zone_* columns are NaN/None; everything else is computed."""
    labeled = set(schema.LABEL_COLUMNS) <= set(points.columns)
    pts = _prepare(points)
    if pts.empty:
        cols = OUTPUT_COLUMNS + (list(schema.WINDOW_LABEL_COLUMNS) if labeled else [])
        return pd.DataFrame(columns=cols)
    parts = [_chunk_features(c, layers, labeled) for c in _chunks(pts)]
    return pd.concat(parts, ignore_index=True)


def _prepare(points: pd.DataFrame) -> pd.DataFrame:
    """Count out-of-order arrivals in seq order, then sort each track by t (stable)."""
    p = points.sort_values(["track_id", "seq"], kind="stable").reset_index(drop=True)
    t = p["t"].to_numpy(dtype="float64")
    same = np.r_[False, p["track_id"].to_numpy()[1:] == p["track_id"].to_numpy()[:-1]]
    prev_t = np.r_[np.nan, t[:-1]]
    p["_nonmono"] = (same & (t < prev_t)).astype("float64")
    p = p.sort_values(["track_id", "t"], kind="stable").reset_index(drop=True)
    return p


def _chunks(p: pd.DataFrame):
    code = pd.factorize(p["track_id"])[0]
    starts = np.flatnonzero(np.r_[True, code[1:] != code[:-1]])
    cut = [0]
    for s in starts[1:]:
        if s - cut[-1] >= CHUNK_FIXES:
            cut.append(s)
    cut.append(len(p))
    for a, b in pairwise(cut):
        yield p.iloc[a:b].reset_index(drop=True)


def _num(p: pd.DataFrame, col: str) -> np.ndarray:
    if col not in p.columns:
        return np.full(len(p), np.nan)
    return pd.to_numeric(p[col], errors="coerce").astype("float64").to_numpy()


def _reported_gs(p: pd.DataFrame) -> np.ndarray:
    """Ground speed as a velocity report: a moving speed without a course is an incomplete
    (stale) report in readsb traces and is not used. Below COURSE_MIN_MPS course is undefined."""
    gs, trk = _num(p, "gs_mps"), _num(p, "track_deg")
    return np.where(np.isnan(trk) & (gs > params.COURSE_MIN_MPS), np.nan, gs)


def _arrays(p: pd.DataFrame, layers=None) -> dict[str, np.ndarray]:
    code = pd.factorize(p["track_id"])[0].astype(np.int64)
    domain = p["domain"].astype("string").to_numpy(dtype=object)
    on_ground = (
        p["on_ground"].astype("boolean")
        if "on_ground" in p.columns
        else pd.Series(pd.NA, index=p.index)
    )
    # ground: vehicles and aircraft reporting on_ground; unknown on_ground counts as airborne
    ground = (domain == "vehicle") | on_ground.fillna(False).to_numpy(dtype=bool)
    lat, lon = _num(p, "lat"), _num(p, "lon")
    # taxi limit: vehicles always; aircraft on the ground only where the map shows a
    # taxi surface (inside the LIRF boundary, off the runways). A ground fix on a runway
    # or at an unmapped airport may be a take-off or landing roll: air limit.
    taxi = ground.copy()
    if layers is not None:
        from divas_air.features.mapfeat import taxi_surface_mask

        taxi = ground & ((domain == "vehicle") | taxi_surface_mask(layers, lat, lon))
    return {
        "code": code,
        "t": _num(p, "t"),
        "lat": lat,
        "lon": lon,
        "gs": _reported_gs(p),
        "gs_raw": _num(p, "gs_mps"),
        "trk": _num(p, "track_deg"),
        "hdg": _num(p, "heading_deg"),
        "vrate": _num(p, "vrate_mps"),
        "alt_baro": _num(p, "alt_baro_m"),
        "alt_geom": _num(p, "alt_geom_m"),
        "nacp": _num(p, "nacp"),
        "nic": _num(p, "nic"),
        "sil": _num(p, "sil"),
        "nonmono": p["_nonmono"].to_numpy(dtype="float64"),
        "domain": domain,
        "asset_class": p["asset_class"].astype("string").to_numpy(dtype=object),
        "ground": ground,
        "taxi": taxi,
        "on_ground": on_ground,
    }


def _chunk_features(p: pd.DataFrame, layers, labeled: bool) -> pd.DataFrame:
    a = _arrays(p, layers)
    g = build_grid(a["code"], a["t"])
    track_start = np.repeat(
        np.flatnonzero(np.r_[True, a["code"][1:] != a["code"][:-1]]),
        np.bincount(a["code"]),
    )
    w = Slices(g.lo, g.hi)
    b = Slices(g.blo, g.lo)
    f = core.fix_level(a, track_start)
    o = core.window_level(a, f, g, w, b)

    last = g.hi - 1
    if layers is not None:
        from divas_air.features import mapfeat

        o.update(mapfeat.window_level(p, a, f, g, w, layers))
    else:
        for c in MAP_FEATURES:
            o[c] = np.full(g.n, np.nan)
        for c in ("aux_zone_id", "aux_zone_name", "aux_zone_type"):
            o[c] = np.full(g.n, None, dtype=object)
        o["aux_zone_speed_limit_mps"] = np.full(g.n, np.nan)

    callsign = (
        p["callsign"].astype("string").groupby(a["code"]).ffill()
        if "callsign" in p.columns
        else None
    )
    o["aux_asset_id"] = p["asset_id"].astype("string").to_numpy(dtype=object)[last]
    o["aux_domain"] = a["domain"][last]
    o["aux_asset_class"] = a["asset_class"][last]
    o["aux_callsign"] = (
        callsign.to_numpy(dtype=object)[last]
        if callsign is not None
        else np.full(g.n, None, dtype=object)
    )

    df = pd.DataFrame(
        {
            "track_id": p["track_id"].astype("string").to_numpy(dtype=object)[last],
            "t_end": g.t_end,
            "t_start": g.t_end - config.WINDOW_S,
        }
    )
    feats = pd.DataFrame(
        {c: np.asarray(o[c], dtype="float64") for c in registry.FEATURE_COLUMNS}
    )
    aux = pd.DataFrame({c: o[c] for c in registry.AUX_COLUMNS})
    parts = [df, feats, aux]
    if labeled:
        parts.append(pd.DataFrame(labels.window_labels(p, a["code"], g, w)))
    out = pd.concat(parts, axis=1)
    return _types(out)


def _types(df: pd.DataFrame) -> pd.DataFrame:
    for c in (
        "track_id",
        "aux_asset_id",
        "aux_domain",
        "aux_asset_class",
        "aux_callsign",
        "aux_zone_id",
        "aux_zone_name",
        "aux_zone_type",
    ):
        df[c] = df[c].astype("string")
    df["aux_airborne"] = df["aux_airborne"].astype(bool)
    if "label_cause" in df.columns:
        for c in ("label_cause", "label_event_id", "scene_id", "base_track_id"):
            df[c] = df[c].astype("string")
        df["label_transition"] = df["label_transition"].astype(bool)
    return df
