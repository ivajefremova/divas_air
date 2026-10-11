"""Batch pipeline (specs/05_fleet.md requirement 15).

features -> pass-1 integrity -> apron fleet layer (degraded flags, leave-one-out
features, area alerts) -> pass 2 + cause -> verdict.assemble -> flat verdict table.

CLI: python -m divas_air.pipeline --source <name|all>
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from divas_air import config, params, registry, schema
from divas_air.fleet import (
    alert_members,
    area_alerts,
    cells_from_windows,
    fleet_features,
)
from divas_air.models import load_bundle
from divas_air.verdict import assemble

KEYS = list(schema.WINDOW_KEYS)
FEATURES_DIR = config.PROCESSED / "features"
VERDICTS_DIR = config.PROCESSED / "verdicts"
FLEET_DIR = config.PROCESSED / "fleet"
BASELINE_APRON_PATH = FLEET_DIR / "baseline_apron.parquet"
CHUNK_ROWS = (
    300_000  # verdict assembly runs on whole tracks, about this many rows at a time
)


@dataclass
class FleetTables:
    cells: pd.DataFrame  # apron cell table
    features: pd.DataFrame  # keys + registry.FLEET_COLUMNS
    alerts: pd.DataFrame  # area_alerts output
    members: pd.DataFrame  # keys + area_alert_id


def load_baseline() -> pd.DataFrame | None:
    return (
        pd.read_parquet(BASELINE_APRON_PATH) if BASELINE_APRON_PATH.exists() else None
    )


def degraded_flags(features: pd.DataFrame, bundle) -> np.ndarray:
    """Requirement 4: pass-1 integrity_raw below UNTRUSTED_EXIT, or a degraded-majority window."""
    integrity1 = 100.0 * (1.0 - bundle.p_unsound(features, pass_=1))
    sig = features["sig_degraded_majority"].to_numpy(dtype="float64", na_value=0.0)
    return (integrity1 < params.UNTRUSTED_EXIT) | (sig == 1)


def _groups(features: pd.DataFrame) -> list[np.ndarray]:
    """Row indices per fleet group: one per scene on labeled sources (approach scenes
    share real clocks and must not see each other), else the whole source."""
    if "scene_id" not in features:
        return [np.arange(len(features))]
    codes, _ = pd.factorize(features["scene_id"].astype(str), sort=True)
    order = np.argsort(codes, kind="stable")
    bounds = np.flatnonzero(np.diff(codes[order])) + 1
    return np.split(order, bounds)


def fleet_tables(
    features: pd.DataFrame, bundle=None, baseline: pd.DataFrame | None = None
) -> FleetTables:
    """Apron fleet layer for a feature table, with the same functions the engine calls."""
    bundle = bundle if bundle is not None else load_bundle()
    profile = params.APRON
    w = features[KEYS + ["aux_lat", "aux_lon"]].copy()
    w["degraded"] = degraded_flags(features, bundle)
    cells, ff, alerts, members = [], [], [], []
    for idx in _groups(features):
        g = w.iloc[idx]
        c = cells_from_windows(g, profile, baseline)
        a = area_alerts(c, profile)
        cells.append(c)
        ff.append(fleet_features(g, profile, baseline))
        if len(a):
            alerts.append(a)
            members.append(alert_members(g, a, profile))
    empty_members = pd.DataFrame(
        {"track_id": [], "t_end": [], "area_alert_id": []}
    ).astype({"track_id": object, "t_end": "float64", "area_alert_id": object})
    return FleetTables(
        cells=pd.concat(cells, ignore_index=True),
        features=pd.concat(ff, ignore_index=True),
        alerts=pd.concat(alerts, ignore_index=True) if alerts else pd.DataFrame(),
        members=pd.concat(members, ignore_index=True) if members else empty_members,
    )


def _track_chunks(track_ids: pd.Series, rows: int) -> list[np.ndarray]:
    """Row indices in chunks of about `rows` that never split a track."""
    codes, _ = pd.factorize(track_ids.astype(str), sort=True)
    order = np.argsort(codes, kind="stable")
    sizes = np.bincount(codes)
    ends = np.cumsum(sizes)
    cut = np.searchsorted(ends, np.arange(rows, ends[-1], rows))
    bounds = np.unique(ends[cut]) if len(cut) else np.array([], int)
    return np.split(order, bounds[bounds < len(order)])


def verdicts(features: pd.DataFrame, bundle=None, baseline: pd.DataFrame | None = None):
    """(flat verdict table in input row order, FleetTables)."""
    bundle = bundle if bundle is not None else load_bundle()
    ft = fleet_tables(features, bundle, baseline)
    f = features.drop(
        columns=[c for c in [*registry.FLEET_COLUMNS, "area_alert_id"] if c in features]
    ).reset_index(drop=True)
    f = f.merge(ft.features[KEYS + registry.FLEET_COLUMNS], on=KEYS, how="left")
    f = f.merge(ft.members[KEYS + ["area_alert_id"]], on=KEYS, how="left")
    f["area_alert_id"] = (
        f["area_alert_id"].astype(object).where(f["area_alert_id"].notna(), None)
    )
    parts = []
    for idx in _track_chunks(f["track_id"], CHUNK_ROWS) if len(f) else []:
        v = assemble(f.iloc[np.sort(idx)], bundle)
        v.index = np.sort(idx)
        parts.append(v)
    out = (
        pd.concat(parts).sort_index().reset_index(drop=True)
        if parts
        else assemble(f, bundle)
    )
    return out, ft


def run(source: str) -> Path:
    """Write data/processed/verdicts/<source>.parquet and the apron cell table."""
    feats = pd.read_parquet(FEATURES_DIR / f"{source}.parquet")
    out, ft = verdicts(feats, load_bundle(), load_baseline())
    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    ft.cells.to_parquet(FLEET_DIR / f"{source}_apron_cells.parquet", index=False)
    path = VERDICTS_DIR / f"{source}.parquet"
    out.to_parquet(path, index=False)
    return path


def sources() -> list[str]:
    return sorted(p.stem for p in FEATURES_DIR.glob("*.parquet"))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m divas_air.pipeline")
    ap.add_argument("--source", required=True, help="source name or 'all'")
    a = ap.parse_args(argv)
    for s in sources() if a.source == "all" else [a.source]:
        t0 = time.time()
        path = run(s)
        v = pd.read_parquet(path, columns=["trust_state", "area_alert_id"])
        states = v["trust_state"].value_counts(normalize=True).round(4).to_dict()
        print(
            f"{s}: {len(v)} verdicts, states {states}, "
            f"with area alert {v['area_alert_id'].notna().mean():.2%}, {time.time() - t0:.0f} s -> {path}"
        )


if __name__ == "__main__":
    main()
