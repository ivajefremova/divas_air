"""Module 1: raw track sources -> unified point schema (specs/01_ingest.md).

The real sources exist as flattened adsb.lol parquet files written by
`scripts/filter_adsblol.py` (see docs/DATA_INVENTORY.md section 1). Those files
are already in SI units, so ingest maps columns, filters the area, cuts
segments, forward-fills the integrity fields and applies type overrides.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from divas_air import config, params, schema

POINTS_DIR = config.PROCESSED / "points"

# source -> glob of flattened adsb.lol files under data/processed/
SOURCE_FILES = {
    "fco": "adsblol_fco_*.parquet",
    "baltic": "adsblol_jam_*.parquet",
    "control": "adsblol_control_*.parquet",
}
ALL_SOURCES = ("fco", "baltic", "control", "adr_mock", "lira")
# (lat_min, lon_min, lat_max, lon_max); sources not listed keep their full region
AREA_BOX = {"fco": config.APPROACH_BOX}

# flattened adsb.lol column -> unified column (units already SI in the files)
FLAT_COLUMNS = {
    "icao24": "asset_id",
    "ts": "t",
    "lat": "lat",
    "lon": "lon",
    "on_ground": "on_ground",
    "alt_m": "alt_baro_m",
    "speed_mps": "gs_mps",
    "track_deg": "track_deg",
    "vrate_mps": "vrate_mps",
    "nic": "nic",
    "nac_p": "nacp",
    "sil": "sil",
    "callsign": "callsign",
    "type": "typecode_raw",
}
INTEGRITY_FIELDS = ("nacp", "nic", "sil")
# Altitudes above schema's sanity bound are not physical; treated as unparseable.
ALT_MAX_M = schema._ALT_MAX_M

OUTPUT_COLUMNS = (
    "track_id",
    "asset_id",
    "source",
    "domain",
    "seq",
    "t",
    "lat",
    "lon",
    "asset_class",
    "type_overridden",
    "alt_baro_m",
    "alt_geom_m",
    "gs_mps",
    "track_deg",
    "heading_deg",
    "vrate_mps",
    "on_ground",
    "nacp",
    "nic",
    "sil",
    "callsign",
    "typecode",
    "typecode_raw",
)


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _type_table() -> dict[str, str]:
    t = pd.read_csv(config.REFERENCE / "aircraft_types.csv")
    return dict(
        zip(t["typecode"].str.strip().str.upper(), t["size_class"], strict=True)
    )


@lru_cache(maxsize=1)
def _overrides() -> dict[str, str]:
    ov = pd.read_csv(config.REFERENCE / "type_overrides.csv")
    return dict(
        zip(
            ov["icao24"].str.strip().str.lower(),
            ov["typecode"].str.strip(),
            strict=True,
        )
    )


def asset_class_for(typecode: str | None) -> str:
    """aircraft_types.csv lookup; unknown or missing type -> "other"."""
    if typecode is None or not isinstance(typecode, str) or not typecode.strip():
        return "other"
    return _type_table().get(typecode.strip().upper(), "other")


def apply_type_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Set typecode, type_overridden and asset_class from typecode_raw and type_overrides.csv."""
    out = df.copy()
    if "typecode_raw" not in out.columns:
        out["typecode_raw"] = out["typecode"] if "typecode" in out.columns else pd.NA
    raw = out["typecode_raw"].astype("string").str.strip().replace("", pd.NA)
    out["typecode_raw"] = raw
    override = out["asset_id"].astype("string").str.lower().map(_overrides())
    out["type_overridden"] = override.notna().to_numpy()
    out["typecode"] = override.astype("string").fillna(raw)
    table = _type_table()
    out["asset_class"] = (
        out["typecode"].str.upper().map(table).fillna("other").astype("string")
    )
    return out


# ---------------------------------------------------------------------------
# flattened adsb.lol -> points
# ---------------------------------------------------------------------------


def from_flat(raw: pd.DataFrame, source: str, *, box=None) -> tuple[pd.DataFrame, dict]:
    """Convert flattened adsb.lol rows (in arrival order) to unified points.

    Returns (points, drop counts). Rows are grouped by track, arrival order
    kept inside each track; nothing is sorted by time or de-duplicated.
    """
    df = raw.rename(columns=FLAT_COLUMNS)[list(FLAT_COLUMNS.values())].copy()
    for c in ("t", "lat", "lon"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df[["t", "lat", "lon"]].isna().any(axis=1)
    drops = {"missing_t_lat_lon": int(bad.sum())}
    df = df[~bad]

    # area filter first, then segments
    if box is not None:
        lat_min, lon_min, lat_max, lon_max = box
        inside = df["lat"].between(lat_min, lat_max) & df["lon"].between(
            lon_min, lon_max
        )
        drops["outside_area"] = int((~inside).sum())
        df = df[inside]
    df = df.reset_index(drop=True)

    df["asset_id"] = df["asset_id"].astype("string").str.strip().str.lower()
    for c in ("alt_baro_m", "gs_mps", "track_deg", "vrate_mps", *INTEGRITY_FIELDS):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")

    # filter_adsblol.py writes on_ground=False when the baro altitude was absent;
    # only "ground" or a number tells us anything.
    on_ground = df["on_ground"].astype("boolean")
    on_ground[~on_ground.fillna(False) & df["alt_baro_m"].isna()] = pd.NA
    df["on_ground"] = on_ground

    too_high = df["alt_baro_m"] > ALT_MAX_M
    drops["alt_baro_nulled_above_max"] = int(too_high.sum())
    df.loc[too_high, "alt_baro_m"] = np.nan

    df["track_deg"] = np.mod(df["track_deg"], 360.0)
    df.loc[df["track_deg"] >= 360.0, "track_deg"] = 0.0
    df["alt_geom_m"] = np.nan
    df["heading_deg"] = np.nan
    df["callsign"] = df["callsign"].astype("string").str.strip().replace("", pd.NA)

    # segments: a silence longer than TRACK_GAP_SPLIT_S since the latest fix so far
    by_asset = df.groupby("asset_id", sort=False)["t"]
    latest = by_asset.cummax().groupby(df["asset_id"], sort=False).shift()
    new_seg = (df["t"] - latest) > params.TRACK_GAP_SPLIT_S
    df["_seg"] = new_seg.groupby(df["asset_id"], sort=False).cumsum().astype("int64")
    df = df.sort_values(["asset_id", "_seg"], kind="stable").reset_index(drop=True)

    df["source"] = source
    df["domain"] = "aircraft"
    df["track_id"] = source + ":" + df["asset_id"] + ":" + df["_seg"].astype(str)
    by_track = df.groupby("track_id", sort=False)
    df["seq"] = by_track.cumcount().astype("int64")
    df[list(INTEGRITY_FIELDS)] = by_track[list(INTEGRITY_FIELDS)].ffill()

    df = apply_type_overrides(df)
    out = schema.coerce_points(df[list(OUTPUT_COLUMNS)])
    schema.validate(out)
    return out, drops


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


def source_files(source: str) -> list[Path]:
    pattern = SOURCE_FILES.get(source)
    return sorted(config.PROCESSED.glob(pattern)) if pattern else []


def points_path(source: str) -> Path:
    return POINTS_DIR / f"{source}.parquet"


def _read(source: str) -> tuple[pd.DataFrame, dict]:
    files = source_files(source)
    if not files:
        raise FileNotFoundError(
            f"no input data for source {source!r} (see docs/DATA_INVENTORY.md)"
        )
    raw = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    points, drops = from_flat(raw, source, box=AREA_BOX.get(source))
    drops["files"] = len(files)
    return points, drops


def ingest_source(source: str) -> Path:
    """Raw -> canonical parquet; returns its path."""
    return _ingest(source)[0]


def _ingest(source: str) -> tuple[Path, pd.DataFrame, dict]:
    points, drops = _read(source)
    path = points_path(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    points.to_parquet(path, index=False)
    return path, points, drops


def load_points(source: str) -> pd.DataFrame:
    """Read the canonical parquet, validated."""
    return schema.validate(pd.read_parquet(points_path(source)))


def summary(source: str, points: pd.DataFrame, drops: dict) -> str:
    t0 = pd.to_datetime(points["t"].min(), unit="s", utc=True)
    t1 = pd.to_datetime(points["t"].max(), unit="s", utc=True)
    days = pd.to_datetime(points["t"], unit="s", utc=True).dt.date.nunique()
    typed = (points.groupby("asset_id")["asset_class"].first() != "other").mean()
    nulls = " ".join(
        f"{c}={points[c].isna().mean():.1%}" for c in ("gs_mps", "nacp", "alt_geom_m")
    )
    dropped = " ".join(f"{k}={v}" for k, v in drops.items() if k != "files")
    return (
        f"{source}: rows={len(points)} tracks={points['track_id'].nunique()} "
        f"aircraft={points['asset_id'].nunique()} days={days} "
        f"span={t0:%Y-%m-%d %H:%M}..{t1:%Y-%m-%d %H:%M} typed={typed:.1%} "
        f"null[{nulls}] dropped[{dropped}]"
    )
