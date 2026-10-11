"""CLI: python -m divas_air.fleet --source <name> --profile <apron|regional> | --static-halos."""

from __future__ import annotations

import argparse
import json
import time

import pandas as pd

from divas_air import config, params
from divas_air.fleet import cells_from_points

FLEET_DIR = config.PROCESSED / "fleet"
POINT_COLUMNS = ["track_id", "asset_id", "t", "lat", "lon", "on_ground", "nacp"]


def cells_path(source: str, profile: str):
    return FLEET_DIR / f"{source}_{profile}_cells.parquet"


def run_regional(source: str) -> None:
    pts = pd.read_parquet(
        config.PROCESSED / "points" / f"{source}.parquet", columns=POINT_COLUMNS
    )
    cells = cells_from_points(pts, params.REGIONAL)
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(cells_path(source, "regional"), index=False)
    n = len(cells)
    counts = cells["level"].value_counts().to_dict()
    above_warn = int((cells["share"] > params.REGIONAL.warn_share).sum())
    print(
        f"{source} regional: {n} qualifying cells, levels {counts}, above {params.REGIONAL.warn_share:.0%}: {above_warn}"
    )


def run_apron(source: str) -> None:
    from divas_air.pipeline import fleet_tables

    feats = pd.read_parquet(config.PROCESSED / "features" / f"{source}.parquet")
    cells = fleet_tables(feats).cells
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(cells_path(source, "apron"), index=False)
    print(
        f"{source} apron: {len(cells)} cell-steps, flagged {int(cells['flagged'].sum())}"
    )


def run_static_halos() -> None:
    from divas_air.geo import MapLayers
    from divas_air.halos import STATIC_HALOS_PATH, static_halos

    fc = static_halos(MapLayers.load())
    STATIC_HALOS_PATH.write_text(json.dumps(fc) + "\n")
    print(f"static halos: {len(fc['features'])} features -> {STATIC_HALOS_PATH}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m divas_air.fleet")
    ap.add_argument("--source")
    ap.add_argument(
        "--profile", choices=sorted(params.FLEET_PROFILES), default="regional"
    )
    ap.add_argument("--static-halos", action="store_true")
    a = ap.parse_args(argv)
    if not a.static_halos and not a.source:
        ap.error("give --source or --static-halos")
    t0 = time.time()
    if a.static_halos:
        run_static_halos()
    if a.source:
        (run_regional if a.profile == "regional" else run_apron)(a.source)
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
