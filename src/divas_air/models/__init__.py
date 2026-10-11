"""Learned models (specs/04_models.md part B): integrity passes 1 and 2, cause.

The bundle reads LightGBM text models and calibration.json (no pickle). It
selects its inputs by name from whatever table it is given; absent columns
(fleet columns on a plain feature table) are NaN.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from divas_air import schema
from divas_air.models.splits import MODELS_DIR

MODEL_FILES = {
    "integrity_p1": "integrity_p1.txt",
    "integrity_p2": "integrity_p2.txt",
    "cause": "cause.txt",
}
CALIBRATION_FILE = "calibration.json"
P_COLUMNS = [f"p_{c}" for c in schema.CAUSES]


def matrix(features: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """float64 matrix of `cols`; a column absent from `features` is all NaN."""
    out = np.full((len(features), len(cols)), np.nan)
    for j, c in enumerate(cols):
        if c in features.columns:
            out[:, j] = features[c].to_numpy(dtype="float64", na_value=np.nan)
    return out


def isotonic_apply(p: np.ndarray, iso: dict) -> np.ndarray:
    """Piecewise-linear isotonic map stored as thresholds (x, y); clipped at the ends."""
    return np.clip(np.interp(p, iso["x"], iso["y"]), 0.0, 1.0)


def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class ModelBundle:
    def __init__(self, boosters: dict[str, lgb.Booster], calibration: dict):
        self.boosters = boosters
        self.calibration = calibration
        self.inputs: dict[str, list[str]] = {
            k: list(b.feature_name()) for k, b in boosters.items()
        }

    def _raw_p(self, features: pd.DataFrame, pass_: int) -> np.ndarray:
        name = f"integrity_p{pass_}"
        return self.boosters[name].predict(matrix(features, self.inputs[name]))

    def p_unsound(
        self, features: pd.DataFrame, pass_: int = 2, calibrated: bool = True
    ) -> np.ndarray:
        if len(features) == 0:
            return np.empty(0)
        p = self._raw_p(features, pass_)
        if calibrated:
            p = isotonic_apply(p, self.calibration[f"integrity_p{pass_}"])
        return p

    def cause_logits(self, features: pd.DataFrame) -> np.ndarray:
        return self.boosters["cause"].predict(
            matrix(features, self.inputs["cause"]), raw_score=True
        )

    def cause_probs(self, features: pd.DataFrame) -> pd.DataFrame:
        if len(features) == 0:
            return pd.DataFrame(columns=P_COLUMNS, dtype="float64")
        z = self.cause_logits(features) / self.calibration["cause"]["temperature"]
        return pd.DataFrame(softmax(z), columns=P_COLUMNS, index=features.index)

    def contributions(self, features: pd.DataFrame, pass_: int = 2) -> pd.DataFrame:
        """TreeSHAP contribution of each input toward unsound (log-odds); bias dropped."""
        name = f"integrity_p{pass_}"
        cols = self.inputs[name]
        c = self.boosters[name].predict(matrix(features, cols), pred_contrib=True)
        return pd.DataFrame(c[:, :-1], columns=cols, index=features.index)


def load_bundle(path: Path | None = None) -> ModelBundle:
    d = Path(path) if path is not None else MODELS_DIR
    boosters = {k: lgb.Booster(model_file=str(d / f)) for k, f in MODEL_FILES.items()}
    calibration = json.loads((d / CALIBRATION_FILE).read_text())
    return ModelBundle(boosters, calibration)
