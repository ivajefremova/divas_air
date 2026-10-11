"""Scene-level train / calib / test split (specs/04_models.md requirement 5).

Every scene goes to exactly one split. Scenes are stratified by kind
(approach or ground) and by the rarest cause they contain, so each split gets
every cause. Written once to artifacts/models/splits.json and reused while it
covers every scene.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from divas_air import config, params, schema

MODELS_DIR = config.ROOT / "artifacts" / "models"
SPLITS_PATH = MODELS_DIR / "splits.json"
SPLITS = ("train", "calib", "test")


def scene_strata(windows: pd.DataFrame) -> pd.Series:
    """Stratum per scene_id: '<kind>|<rarest cause in the scene>'."""
    sc = windows[["scene_id", "label_cause"]].astype(str).drop_duplicates()
    n_scenes = sc.groupby("label_cause")["scene_id"].nunique()
    rank = {c: n_scenes.get(c, 0) for c in schema.CAUSES}
    rarest = sc.groupby("scene_id")["label_cause"].agg(
        lambda s: min(s, key=lambda c: (rank.get(c, 0), c))
    )
    kind = rarest.index.to_series().str.split("_").str[0]
    return (kind + "|" + rarest).sort_index()


def make_splits(strata: pd.Series, seed: int = params.SEED) -> dict[str, list[str]]:
    """Seeded, stratified assignment of scene ids by params.SPLIT_FRACTIONS."""
    rng = np.random.default_rng(seed)
    fr = np.array([params.SPLIT_FRACTIONS[k] for k in SPLITS], dtype="float64")
    cum = np.cumsum(fr / fr.sum())
    out: dict[str, list[str]] = {k: [] for k in SPLITS}
    for _, scenes in strata.groupby(strata, sort=True):
        ids = np.array(sorted(scenes.index), dtype=object)
        rng.shuffle(ids)
        n = len(ids)
        offset = rng.random()  # spreads the rounding of small strata over the splits
        # position of each scene in [0, 1): which split's interval it falls in
        pos = (offset + (np.arange(n) + 0.5) / n) % 1.0
        which = np.searchsorted(cum, pos, side="right")
        for i, k in enumerate(SPLITS):
            out[k].extend(str(s) for s in ids[which == i])
    return {k: sorted(v) for k, v in out.items()}


def check_splits(splits: dict[str, list[str]], windows: pd.DataFrame) -> None:
    """Raise if splits are not a partition of the scenes or a split lacks a cause."""
    sets = [set(splits[k]) for k in SPLITS]
    if any(a & b for i, a in enumerate(sets) for b in sets[i + 1 :]):
        raise ValueError("splits overlap")
    if set().union(*sets) != set(windows["scene_id"].astype(str).unique()):
        raise ValueError("splits do not cover exactly the scenes")
    which = split_of(windows, splits)
    for k in SPLITS:
        missing = set(schema.CAUSES) - set(
            windows.loc[which == k, "label_cause"].astype(str)
        )
        if missing:
            raise ValueError(f"split {k} lacks causes {sorted(missing)}")


def split_of(windows: pd.DataFrame, splits: dict[str, list[str]]) -> pd.Series:
    m = {s: k for k in SPLITS for s in splits[k]}
    return windows["scene_id"].astype(str).map(m)


def load_or_make_splits(
    windows: pd.DataFrame, path: Path = SPLITS_PATH
) -> dict[str, list[str]]:
    """Reuse `path` if it covers every scene of `windows`; write a split only if none exists.

    An existing split that misses scenes is an error, never a silent re-split:
    thresholds and models fitted on the old train scenes would leak into the new test.
    """
    scenes = set(windows["scene_id"].astype(str).unique())
    if path.exists():
        s = json.loads(path.read_text())
        missing = scenes - set().union(*(set(s[k]) for k in SPLITS))
        if missing:
            raise ValueError(
                f"{path} does not cover {len(missing)} scenes (e.g. {sorted(missing)[:3]}); "
                "delete it deliberately to re-split, then refit thresholds and retrain"
            )
        return {k: list(s[k]) for k in SPLITS}
    s = make_splits(scene_strata(windows))
    check_splits(s, windows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(s, indent=1) + "\n")
    return s
