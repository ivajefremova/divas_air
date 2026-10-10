"""Tiny in-code fixtures for tests. No files, no network, no map layers.

`make_track` builds a schema-valid straight-line track. Tests then corrupt it
(jump, freeze, gap) and assert on the features. Keep fixtures this small:
real data belongs in acceptance tests only.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pyproj import Geod

from divas_air import config, schema

T0 = 1_791_900_000.0  # on the STRIDE_S grid, mid-day UTC
# Open ground near Fiumicino's apron; only used for geometry.
LAT0, LON0 = 41.80, 12.25
_GEOD = Geod(ellps="WGS84")


def offset(lat, lon, *, north: float | np.ndarray = 0.0, east: float | np.ndarray = 0.0):
    """Move points by (north, east) meters on the WGS84 ellipsoid. Returns (lat, lon)."""
    lat = np.asarray(lat, dtype="float64")
    lon = np.asarray(lon, dtype="float64")
    north = np.broadcast_to(np.asarray(north, dtype="float64"), lat.shape)
    east = np.broadcast_to(np.asarray(east, dtype="float64"), lat.shape)
    dist = np.hypot(north, east)
    az = np.degrees(np.arctan2(east, north))
    lon2, lat2, _ = _GEOD.fwd(lon, lat, az, dist)
    return np.asarray(lat2), np.asarray(lon2)


def make_track(
    *,
    track_id: str = "test:veh_001:0",
    domain: str = "vehicle",
    asset_class: str = "bus",
    n: int = 120,
    dt: float = 1.0,
    speed_mps: float = 5.0,
    course_deg: float = 90.0,
    t0: float = T0,
    lat0: float = LAT0,
    lon0: float = LON0,
    alt_m: float | None = None,
    nacp: float | None = 10.0,
    labeled: bool = False,
) -> pd.DataFrame:
    """Constant-velocity geodesic track, noise-free, sampled every `dt` seconds."""
    t = t0 + dt * np.arange(n)
    dist = speed_mps * (t - t0)
    lon, lat, _ = _GEOD.fwd(np.full(n, lon0), np.full(n, lat0), np.full(n, course_deg), dist)
    asset_id = track_id.split(":")[1]
    df = pd.DataFrame(
        {
            "track_id": track_id,
            "asset_id": asset_id,
            "source": "test",
            "domain": domain,
            "seq": np.arange(n, dtype="int64"),
            "t": t.astype("float64"),
            "lat": np.asarray(lat),
            "lon": np.asarray(lon),
            "asset_class": asset_class,
            "type_overridden": False,
            "alt_baro_m": np.nan if alt_m is None else float(alt_m),
            "alt_geom_m": np.nan if alt_m is None else float(alt_m),
            "gs_mps": float(speed_mps),
            "track_deg": float(course_deg % 360),
            "heading_deg": float(course_deg % 360),
            "vrate_mps": np.nan if alt_m is None else 0.0,
            "on_ground": domain == "vehicle" or alt_m is None,
            "nacp": np.nan if nacp is None else float(nacp),
            "nic": np.nan if nacp is None else 8.0,
            "sil": np.nan if nacp is None else 3.0,
            "callsign": None,
            "typecode": None,
            "typecode_raw": None,
        }
    )
    if labeled:
        df["label_cause"] = "plausible"
        df["label_onset_t"] = np.nan
        df["label_event_id"] = None
        df["label_true_lat"] = df["lat"]
        df["label_true_lon"] = df["lon"]
        df["scene_id"] = "scene_test"
        df["base_track_id"] = track_id
    out = schema.coerce_points(df, labeled=labeled)
    schema.validate(out, labeled=labeled)
    return out


def shift_m(df: pd.DataFrame, mask, *, north: float = 0.0, east: float = 0.0) -> pd.DataFrame:
    """Return a copy with the masked fixes displaced by (north, east) meters."""
    out = df.copy()
    mask = np.asarray(mask, dtype=bool)
    lat, lon = offset(out.loc[mask, "lat"], out.loc[mask, "lon"], north=north, east=east)
    out.loc[mask, "lat"] = lat
    out.loc[mask, "lon"] = lon
    return out


def renumber(df: pd.DataFrame) -> pd.DataFrame:
    """Reassign seq = row order within each track (after inserting or dropping rows)."""
    out = df.reset_index(drop=True).copy()
    out["seq"] = out.groupby("track_id", sort=False).cumcount().astype("int64")
    return out


def error_m(df: pd.DataFrame) -> np.ndarray:
    """Distance in meters between reported and true position (labeled frames)."""
    _, _, d = _GEOD.inv(
        df["label_true_lon"].to_numpy(),
        df["label_true_lat"].to_numpy(),
        df["lon"].to_numpy(),
        df["lat"].to_numpy(),
    )
    return np.asarray(d)


def need(path: Path) -> Path:
    """Acceptance tests fail when a required artifact is missing.

    Set DIVAS_ALLOW_MISSING_DATA=1 to skip instead (machines without the raw
    data, e.g. a cloud session). On the build machine a skip is not a pass.
    """
    path = Path(path)
    if path.exists():
        return path
    msg = f"missing artifact: {path.relative_to(config.ROOT) if path.is_absolute() else path}"
    if os.environ.get("DIVAS_ALLOW_MISSING_DATA") == "1":
        pytest.skip(msg)
    pytest.fail(msg + " (build the module that produces it; see specs/00_contracts.md section 6)")


def points_path(source: str) -> Path:
    return config.PROCESSED / "points" / f"{source}.parquet"


def features_path(source: str) -> Path:
    return config.PROCESSED / "features" / f"{source}.parquet"


def verdicts_path(source: str) -> Path:
    return config.PROCESSED / "verdicts" / f"{source}.parquet"


MODELS = config.ROOT / "artifacts" / "models"
REPLAY = config.PROCESSED / "demo" / "replay"
REPORTS = config.ROOT / "reports"
