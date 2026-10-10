"""Unified point schema, causes, and leakage guard.

FROZEN. Every module reads these constants. Change nothing without human
approval and a note in specs/00_contracts.md section 8.
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Causes
# ---------------------------------------------------------------------------

CAUSES: tuple[str, ...] = (
    "plausible",
    "degraded",
    "technical_error",
    "gnss_anomaly",
    "possible_interference",
    "possible_spoofing",
    "behavioral_anomaly",
)

SOUND_CAUSES: tuple[str, ...] = ("plausible", "behavioral_anomaly")
UNSOUND_CAUSES: tuple[str, ...] = tuple(c for c in CAUSES if c not in SOUND_CAUSES)

# ---------------------------------------------------------------------------
# Asset classes — must match envelopes.csv category column order exactly
# ---------------------------------------------------------------------------

ASSET_CLASSES: tuple[str, ...] = (
    "widebody",
    "narrowbody",
    "regional",
    "turboprop",
    "bizjet",
    "light",
    "helicopter",
    "other",
    "baggage_tractor",
    "bus",
    "fuel_truck",
    "catering_truck",
    "sar_vehicle",
    "follow_me",
)

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

SOURCES: tuple[str, ...] = ("fco", "baltic", "control", "synthetic", "demo", "live", "test")

# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

WINDOW_KEYS: tuple[str, ...] = ("track_id", "t_end")

WINDOW_LABEL_COLUMNS: tuple[str, ...] = (
    "label_frac",
    "label_cause",
    "label_transition",
    "label_onset_t",
    "label_event_id",
    "scene_id",
    "base_track_id",
)

# ---------------------------------------------------------------------------
# Schema columns
# ---------------------------------------------------------------------------

# Required non-nullable columns in every point row.
_REQUIRED_COLUMNS: tuple[str, ...] = (
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
)

# Optional columns (may be null).
_OPTIONAL_COLUMNS: tuple[str, ...] = (
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

_LABEL_COLUMNS: tuple[str, ...] = (
    "label_cause",
    "label_onset_t",
    "label_event_id",
    "label_true_lat",
    "label_true_lon",
    "scene_id",
    "base_track_id",
)
LABEL_COLUMNS: tuple[str, ...] = _LABEL_COLUMNS

# Columns that can never appear in a model feature list.
FORBIDDEN_FEATURE_COLUMNS: frozenset[str] = frozenset(
    _REQUIRED_COLUMNS + _OPTIONAL_COLUMNS + _LABEL_COLUMNS
    + ("t_end", "t_start")
)

_LEAKAGE_PREFIXES: tuple[str, ...] = ("label_", "aux_", "p_", "d_")

# Unit sanity bounds (SI units must be used after ingest).
_ALT_MAX_M = 20_000.0      # ~65,000 ft; higher means the value is still in feet
_T_MIN = 1_000_000_000.0   # 2001-09-09 UTC
_T_MAX = 2_000_000_000.0   # 2033-05-18 UTC

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchemaError(ValueError):
    """A DataFrame violates the unified point schema."""


class LeakageError(ValueError):
    """A feature list contains a forbidden column."""

# ---------------------------------------------------------------------------
# coerce_points
# ---------------------------------------------------------------------------


def coerce_points(df: pd.DataFrame, *, labeled: bool = False) -> pd.DataFrame:
    """Cast a points DataFrame to the expected pandas dtypes.

    Call before validate().  Columns not in the schema are passed through
    unchanged so callers can attach extra metadata without errors.
    """
    df = df.copy()

    str_cols = ["track_id", "asset_id", "source", "domain", "asset_class"]
    if labeled:
        str_cols += ["scene_id", "base_track_id"]
    for c in str_cols:
        if c in df.columns:
            df[c] = df[c].astype("string")

    if "type_overridden" in df.columns:
        df["type_overridden"] = df["type_overridden"].astype("boolean")
    if "on_ground" in df.columns:
        df["on_ground"] = df["on_ground"].astype("boolean")
    if "seq" in df.columns:
        df["seq"] = df["seq"].astype("int64")

    float_cols = ["t", "lat", "lon",
                  "alt_baro_m", "alt_geom_m", "gs_mps", "track_deg",
                  "heading_deg", "vrate_mps", "nacp", "nic", "sil"]
    if labeled:
        float_cols += ["label_onset_t", "label_true_lat", "label_true_lon"]
    for c in float_cols:
        if c in df.columns:
            df[c] = df[c].astype("float64")

    nullable_str = ["callsign", "typecode", "typecode_raw"]
    if labeled:
        nullable_str += ["label_cause", "label_event_id"]
    for c in nullable_str:
        if c in df.columns:
            df[c] = df[c].astype("string")

    return df


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def validate(df: pd.DataFrame, *, labeled: bool = False) -> pd.DataFrame:
    """Raise SchemaError if df violates the unified point schema.

    Checks structure and unit sanity only — not physical plausibility.
    Returns df unchanged so it can be used as a gate in a pipeline.
    """
    missing = set(_REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise SchemaError(f"missing required columns: {sorted(missing)}")

    if labeled:
        missing_lbl = set(_LABEL_COLUMNS) - set(df.columns)
        if missing_lbl:
            raise SchemaError(f"missing label columns: {sorted(missing_lbl)}")

    # seq must be unique within each track
    dup = df.groupby("track_id")["seq"].apply(lambda s: s.duplicated().any())
    if dup.any():
        bad = list(dup[dup].index)
        raise SchemaError(f"duplicate seq within tracks: {bad}")

    # altitude in meters (not feet)
    for col in ("alt_baro_m", "alt_geom_m"):
        if col in df.columns:
            vals = df[col].dropna()
            if (vals > _ALT_MAX_M).any():
                raise SchemaError(
                    f"{col} has values > {_ALT_MAX_M} m — data may still be in feet"
                )

    # timestamps in UNIX seconds (not milliseconds)
    t_vals = df["t"]
    if (t_vals < _T_MIN).any() or (t_vals > _T_MAX).any():
        raise SchemaError(
            f"t is outside [{_T_MIN:.0f}, {_T_MAX:.0f}] — data may be in milliseconds"
        )

    return df


# ---------------------------------------------------------------------------
# assert_no_leakage
# ---------------------------------------------------------------------------


def assert_no_leakage(features) -> None:
    """Raise LeakageError if any feature name is forbidden.

    `features` may be a list/iterable of strings or a dict (checked by keys).
    Forbidden: any name in FORBIDDEN_FEATURE_COLUMNS or that starts with a
    leakage prefix (label_, aux_, p_, d_).
    """
    names = features.keys() if isinstance(features, dict) else features
    for name in names:
        if name in FORBIDDEN_FEATURE_COLUMNS:
            raise LeakageError(f"forbidden feature column: {name!r}")
        if any(name.startswith(pfx) for pfx in _LEAKAGE_PREFIXES):
            raise LeakageError(f"feature name has leakage prefix: {name!r}")


# ---------------------------------------------------------------------------
# integrity_label
# ---------------------------------------------------------------------------


def integrity_label(cause_series: pd.Series) -> pd.Series:
    """Map a cause column to integer labels: 0 = sound, 1 = unsound."""
    return cause_series.map(lambda c: 0 if c in SOUND_CAUSES else 1).astype("int64")
