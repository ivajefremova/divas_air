"""CLI: python -m divas_air.features --source <name|all> [--calibrate]."""

from __future__ import annotations

import argparse
import time

import pandas as pd

from divas_air import config, params, registry
from divas_air.features import compute_features
from divas_air.features.calibrate import THRESHOLDS_PATH, calibrate, features_path

SOURCES = ("fco", "baltic", "control", "synthetic", "demo")


def points_path(source: str):
    return config.PROCESSED / "points" / f"{source}.parquet"


def run(source: str, layers) -> None:
    t0 = time.time()
    pts = pd.read_parquet(points_path(source))
    f = compute_features(pts, layers)
    out = features_path(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    f.to_parquet(out, index=False)
    scored = f[f["tmp_n_points"] >= params.MIN_POINTS]
    over = (
        (scored[registry.ENVELOPE_RATIO_COLUMNS] > params.LIMIT_MARGIN)
        .any(axis=1)
        .mean()
    )
    nan_cols = [c for c in registry.FEATURE_COLUMNS if f[c].isna().all()]
    print(
        f"{source}: {len(pts):,} points -> {len(f):,} windows ({f['track_id'].nunique():,} tracks) "
        f"in {time.time() - t0:.1f} s; envelope over-limit share {over:.4%}; all-NaN: {nan_cols}"
    )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m divas_air.features")
    ap.add_argument("--source", help="source name or 'all'")
    ap.add_argument(
        "--calibrate",
        action="store_true",
        help="fit dimension thresholds from existing tables",
    )
    args = ap.parse_args(argv)
    if not args.source and not args.calibrate:
        ap.error("give --source and/or --calibrate")
    if args.source:
        from divas_air.geo import MapLayers

        layers = MapLayers.load()
        sources = (
            [s for s in SOURCES if points_path(s).exists()]
            if args.source == "all"
            else [args.source]
        )
        for s in sources:
            run(s, layers)
    if args.calibrate:
        th = calibrate()
        fitted = th[th["n"] > 0]
        print(
            f"wrote {THRESHOLDS_PATH.relative_to(config.ROOT)}: {len(th)} rows, {len(fitted)} fitted"
        )


if __name__ == "__main__":
    main()
