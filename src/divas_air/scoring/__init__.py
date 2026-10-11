"""Deterministic scores (specs/04_models.md part A).

Violation of a scored feature: v = clip((x - tau) / scale, 0, 1), with tau and
scale from data/reference/dimension_thresholds.csv for the row's domain
(registry defaults where a row is missing). NaN is no evidence: v = 0.
A dimension score is 100 x prod(1 - v) over that dimension's scored features.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from divas_air import config, registry

THRESHOLDS_PATH = config.REFERENCE / "dimension_thresholds.csv"
DIMENSIONS = registry.SCORED_DIMENSIONS
DIM_COLUMNS = [f"d_{d}" for d in DIMENSIONS]
SCORED = [s.name for s in registry.REGISTRY.values() if s.scored]


@lru_cache(maxsize=4)
def thresholds(path: Path = THRESHOLDS_PATH) -> pd.DataFrame:
    """tau and scale per (feature, domain), with registry defaults where missing.

    Index: feature name. Columns: tau_<domain>, scale_<domain> for aircraft and vehicle,
    and tau_default, scale_default for rows of any other domain.
    """
    reg = pd.DataFrame(
        {
            "tau_default": [registry.REGISTRY[n].tau for n in SCORED],
            "scale_default": [registry.REGISTRY[n].scale for n in SCORED],
        },
        index=SCORED,
        dtype="float64",
    )
    fitted = (
        pd.read_csv(path)
        if Path(path).exists()
        else pd.DataFrame(columns=["name", "domain", "tau", "scale"])
    )
    for domain in ("aircraft", "vehicle"):
        d = fitted[fitted["domain"] == domain].set_index("name")
        reg[f"tau_{domain}"] = (
            d["tau"].reindex(SCORED).fillna(reg["tau_default"]).astype("float64")
        )
        reg[f"scale_{domain}"] = (
            d["scale"].reindex(SCORED).fillna(reg["scale_default"]).astype("float64")
        )
    return reg


def tau_of(feature: str, domain: str) -> float | None:
    """The threshold that applies to `feature` for `domain`; None for an unscored feature."""
    th = thresholds()
    if feature not in th.index:
        return None
    col = f"tau_{domain}" if f"tau_{domain}" in th.columns else "tau_default"
    return float(th.at[feature, col])


def _per_row(features: pd.DataFrame, kind: str) -> np.ndarray:
    """(n_rows, n_scored) array of tau or scale, chosen by aux_domain."""
    th = thresholds()
    n = len(features)
    out = np.tile(th[f"{kind}_default"].to_numpy(), (n, 1))
    if "aux_domain" in features.columns:
        dom = features["aux_domain"].astype("string").fillna("").to_numpy()
        for domain in ("aircraft", "vehicle"):
            m = dom == domain
            out[m] = th[f"{kind}_{domain}"].to_numpy()
    return out


def violations(features: pd.DataFrame) -> pd.DataFrame:
    """One column per scored feature, values in [0, 1]; a missing column counts as NaN."""
    x = (
        np.column_stack(
            [
                features[c].to_numpy(dtype="float64", na_value=np.nan)
                if c in features.columns
                else np.full(len(features), np.nan)
                for c in SCORED
            ]
        )
        if SCORED
        else np.empty((len(features), 0))
    )
    with np.errstate(invalid="ignore"):
        v = np.clip(
            (x - _per_row(features, "tau")) / _per_row(features, "scale"), 0.0, 1.0
        )
    v = np.where(np.isnan(v), 0.0, v)
    return pd.DataFrame(v, columns=SCORED, index=features.index)


def dimension_scores(
    features: pd.DataFrame, viol: pd.DataFrame | None = None
) -> pd.DataFrame:
    """d_kinetic, d_temporal, d_spatial, d_contextual in [0, 100]."""
    v = violations(features) if viol is None else viol
    out = {}
    for d in DIMENSIONS:
        cols = [s.name for s in registry.scored_features(d)]
        out[f"d_{d}"] = 100.0 * np.prod(1.0 - v[cols].to_numpy(), axis=1)
    return pd.DataFrame(out, index=features.index)


def normality_score(dims: pd.DataFrame) -> pd.Series:
    """min(d_spatial, d_contextual): behavior only, never data quality."""
    return dims[["d_spatial", "d_contextual"]].min(axis=1).rename("normality")
