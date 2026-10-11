"""ADR Safe Mobility dataset -> `adr_mock` points (specs/01_ingest.md requirement 10).

Reads `asset_tracks` straight from ADR's tar in `data/raw/adr/` (or from an
extracted copy next to it), so nothing derived from it is written outside
`data/processed/`. See docs/ADR_DATASET.md for the inventory and the
assumptions. ADR forbids redistribution: outputs stay gitignored.
"""

from __future__ import annotations

import io
import tarfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from divas_air import config, schema

SOURCE = "adr_mock"
RAW_DIR = config.RAW / "adr"
PACKAGE = "safemobility-challenge-fco-dataset"
TAR_PATH = RAW_DIR / f"{PACKAGE}.tar"
CLASS_MAP_CSV = config.REFERENCE / "adr_class_map.csv"
SIDE_PATH = config.PROCESSED / "adr" / f"{SOURCE}_side.parquet"

KMH_TO_MPS = 1 / 3.6
AIRCRAFT_CLASS = "aircraft_taxi"
SIDE_COLUMNS = (
    "track_id",
    "seq",
    "adr_row",
    "asset_id",
    "timestamp_unix",
    "inside_aerodrome",
    "runway_critical_ref",
)


# ---------------------------------------------------------------------------
# raw access
# ---------------------------------------------------------------------------


def available() -> bool:
    return (RAW_DIR / PACKAGE).is_dir() or TAR_PATH.exists()


def raw_files() -> list[Path]:
    """The ADR package (extracted directory or tar), if present."""
    for p in (RAW_DIR / PACKAGE, TAR_PATH):
        if p.exists():
            return [p]
    return []


def read_member(relpath: str) -> bytes:
    """Bytes of a file of the ADR package, e.g. `tables/asset_tracks.parquet`."""
    extracted = RAW_DIR / PACKAGE / relpath
    if extracted.exists():
        return extracted.read_bytes()
    if not TAR_PATH.exists():
        raise FileNotFoundError(
            f"ADR package not found in {RAW_DIR} (see docs/ADR_DATASET.md)"
        )
    with tarfile.open(TAR_PATH) as tf:
        return tf.extractfile(f"{PACKAGE}/{relpath}").read()


def read_asset_tracks() -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(read_member("tables/asset_tracks.parquet")))


# ---------------------------------------------------------------------------
# class map
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def class_map() -> pd.DataFrame:
    """adr_class -> domain, asset_class (empty when no envelope fits), match, adr_group."""
    cm = pd.read_csv(CLASS_MAP_CSV, dtype="string", keep_default_na=False)
    return cm.set_index("adr_class")


def map_classes(adr_class: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(domain, asset_class) per row.

    A class with `match=none`, or missing from the map, keeps its ADR name as
    `asset_class`: it is in no envelope category, so the feature layer applies
    no envelope check to it instead of a wrong one.
    """
    cm = class_map()
    cls = adr_class.astype("string")
    mapped = cls.map(cm["asset_class"]).replace("", pd.NA)
    asset_class = mapped.fillna(cls)
    domain = cls.map(cm["domain"])
    domain = domain.fillna(
        pd.Series(
            np.where(cls == AIRCRAFT_CLASS, "aircraft", "vehicle"), index=cls.index
        )
    )
    return domain.astype("string"), asset_class.astype("string")


# ---------------------------------------------------------------------------
# asset_tracks -> points
# ---------------------------------------------------------------------------


def from_asset_tracks(
    raw: pd.DataFrame, source: str = SOURCE
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """ADR asset_tracks rows (file order = arrival order) -> (points, side table, counts).

    One track per asset_id. Nothing is cleaned: implausible speeds, jumps,
    altitude spikes and gaps are kept, they are what the engine must flag.
    """
    df = raw.reset_index(drop=True).copy()
    df["adr_row"] = np.arange(len(df), dtype="int64")
    for c in ("timestamp_unix", "lat", "lon"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df[["timestamp_unix", "lat", "lon"]].isna().any(axis=1)
    counts = {"missing_t_lat_lon": int(bad.sum())}
    df = df[~bad]

    df["asset_id"] = df["asset_id"].astype("string").str.strip()
    df = df.sort_values("asset_id", kind="stable").reset_index(drop=True)

    out = pd.DataFrame(
        {
            "track_id": source + ":" + df["asset_id"] + ":0",
            "asset_id": df["asset_id"],
            "source": source,
            "t": df["timestamp_unix"].astype("float64"),
            "lat": df["lat"].astype("float64"),
            "lon": df["lon"].astype("float64"),
        }
    )
    out["seq"] = out.groupby("track_id", sort=False).cumcount().astype("int64")
    out["domain"], out["asset_class"] = map_classes(df["asset_class"])
    out["type_overridden"] = False
    out["typecode_raw"] = df["asset_class"].astype("string")
    out["typecode"] = out["typecode_raw"]

    out["gs_mps"] = pd.to_numeric(df["speed_kmh"], errors="coerce") * KMH_TO_MPS
    hdg = np.mod(pd.to_numeric(df["heading_deg"], errors="coerce"), 360.0)
    out["heading_deg"] = np.where(hdg >= 360.0, 0.0, hdg)
    counts["heading_360_wrapped"] = int((df["heading_deg"] == 360).sum())

    alt = pd.to_numeric(df["alt_m"], errors="coerce").astype("float64")
    too_high = alt > schema._ALT_MAX_M
    counts["alt_geom_nulled_above_max"] = int(too_high.sum())
    out["alt_geom_m"] = alt.mask(too_high)

    # the table holds surface movements only (PDF 5.7: assets on the apron)
    out["on_ground"] = True
    for c in ("alt_baro_m", "track_deg", "vrate_mps", "nacp", "nic", "sil"):
        out[c] = np.nan
    out["callsign"] = pd.NA

    known = df["asset_class"].isin(class_map().index)
    counts["class_not_in_map"] = int((~known).sum())
    counts["class_no_envelope"] = int(
        (~out["asset_class"].isin(schema.ASSET_CLASSES)).sum()
    )

    from divas_air.ingest import OUTPUT_COLUMNS

    points = schema.coerce_points(out[list(OUTPUT_COLUMNS)])
    schema.validate(points)

    side = pd.DataFrame(
        {
            "track_id": out["track_id"].astype("string"),
            "seq": out["seq"],
            "adr_row": df["adr_row"],
            "asset_id": out["asset_id"].astype("string"),
            "timestamp_unix": out["t"],
            "inside_aerodrome": df["inside_aerodrome"].astype("boolean"),
            "runway_critical_ref": df["runway_critical_ref"].astype("string"),
        }
    )[list(SIDE_COLUMNS)]
    return points, side, counts


def read() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    return from_asset_tracks(read_asset_tracks())


def load_side() -> pd.DataFrame:
    """Side table keyed by (track_id, seq): inside_aerodrome, runway_critical_ref, ADR row."""
    return pd.read_parquet(SIDE_PATH)
