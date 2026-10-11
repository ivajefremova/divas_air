"""Training (specs/04_models.md part B). CLI: python -m divas_air.models.train.

Order: splits -> pass 1 -> (fleet features from out-of-fold pass 1) -> pass 2
-> cause -> calibration on the calib split -> test metrics -> model card.
Labels and scene ids select rows and targets only; every fit is preceded by
schema.assert_no_leakage on its input list.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from types import ModuleType

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

from divas_air import config, params, registry, schema
from divas_air.models import (
    CALIBRATION_FILE,
    MODEL_FILES,
    isotonic_apply,
    load_bundle,
    matrix,
    softmax,
)
from divas_air.models.splits import MODELS_DIR, SPLITS, load_or_make_splits, split_of
from divas_air.scoring import dimension_scores, normality_score
from divas_air.scoring.baseline import naive_score

KEYS = list(schema.WINDOW_KEYS)
CAUSE_INDEX = {c: i for i, c in enumerate(schema.CAUSES)}
FEATURES_PATH = config.PROCESSED / "features" / "synthetic.parquet"
POINTS_PATH = config.PROCESSED / "points" / "synthetic.parquet"
BASELINE_APRON_PATH = config.PROCESSED / "fleet" / "baseline_apron.parquet"


# --- fitting -----------------------------------------------------------------


def balanced_weights(y: np.ndarray) -> np.ndarray:
    """n / (n_classes x n_class) per row: every class weighs the same in total."""
    classes, inv, counts = np.unique(y, return_inverse=True, return_counts=True)
    return (len(y) / (len(classes) * counts))[inv]


def fit_lgb(
    x: pd.DataFrame,
    y: np.ndarray,
    groups: np.ndarray,
    cols: list[str],
    objective: dict,
    monotone: list[int] | None = None,
) -> lgb.Booster:
    """Early stopping on a grouped validation fold of the train scenes, then a refit
    on all train rows with the early-stopped tree count."""
    schema.assert_no_leakage(cols)
    p = {**params.LGB_PARAMS, **objective, "seed": params.SEED}
    if monotone is not None:
        p["monotone_constraints"] = monotone
    X = matrix(x, cols)
    w = balanced_weights(y)
    gss = GroupShuffleSplit(
        n_splits=1, test_size=params.LGB_VALID_FRAC, random_state=params.SEED
    )
    tr, va = next(gss.split(X, y, groups))
    d_tr = lgb.Dataset(
        X[tr], y[tr], weight=w[tr], feature_name=cols, free_raw_data=False
    )
    d_va = lgb.Dataset(X[va], y[va], weight=w[va], reference=d_tr)
    probe = lgb.train(
        p,
        d_tr,
        num_boost_round=params.LGB_MAX_TREES,
        valid_sets=[d_va],
        callbacks=[lgb.early_stopping(params.LGB_EARLY_STOP, verbose=False)],
    )
    n_trees = max(
        int(probe.best_iteration or params.LGB_MAX_TREES), params.LGB_MIN_TREES
    )
    schema.assert_no_leakage(cols)
    return lgb.train(
        p, lgb.Dataset(X, y, weight=w, feature_name=cols), num_boost_round=n_trees
    )


def fit_integrity(x: pd.DataFrame, y: np.ndarray, groups: np.ndarray, cols: list[str]):
    return fit_lgb(
        x,
        y,
        groups,
        cols,
        {"objective": "binary"},
        monotone=registry.monotone_constraints(cols),
    )


def fit_cause(x: pd.DataFrame, y: np.ndarray, groups: np.ndarray, cols: list[str]):
    obj = {"objective": "multiclass", "num_class": len(schema.CAUSES)}
    return fit_lgb(x, y, groups, cols, obj)


def fit_isotonic(p: np.ndarray, y: np.ndarray) -> dict:
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p, y)
    return {"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()}


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    """Single temperature minimizing the multiclass log loss on the calib split."""
    idx = np.arange(len(y))

    def nll(log_t: float) -> float:
        p = softmax(logits / np.exp(log_t))
        return float(-np.log(np.clip(p[idx, y], 1e-12, 1)).mean())

    r = minimize_scalar(nll, bounds=(np.log(0.05), np.log(20.0)), method="bounded")
    return float(np.exp(r.x))


# --- metrics -------------------------------------------------------------------


def ece(p: np.ndarray, y: np.ndarray, bins: int = params.ECE_BINS) -> float:
    """Expected calibration error, equal-width bins on P(unsound)."""
    b = np.minimum((p * bins).astype(int), bins - 1)
    n = np.bincount(b, minlength=bins)
    conf = np.bincount(b, weights=p, minlength=bins)
    acc = np.bincount(b, weights=y, minlength=bins)
    m = n > 0
    return float(np.sum(np.abs(acc[m] - conf[m])) / len(p))


def binary_metrics(y: np.ndarray, score: np.ndarray) -> dict:
    return {
        "auroc": float(roc_auc_score(y, score)),
        "auprc": float(average_precision_score(y, score)),
    }


# --- fleet (module 5) -----------------------------------------------------------


def fleet_module() -> ModuleType | None:
    try:
        from divas_air import fleet
    except ImportError:
        return None
    return fleet


def add_fleet_features(
    windows: pd.DataFrame,
    p1_integrity: np.ndarray,
    train_clean: np.ndarray,
    fleet: ModuleType,
) -> pd.DataFrame:
    """Fleet columns from pass-1 integrity (out-of-fold on train scenes).

    `train_clean` marks windows of train scenes without any event; the apron
    baseline is fitted on them and written before the fleet features are computed.
    """
    profile = params.APRON
    w = windows[KEYS + ["aux_lat", "aux_lon"]].copy()
    w["degraded"] = (p1_integrity < params.UNTRUSTED_EXIT) | (
        windows["sig_degraded_majority"].to_numpy(dtype="float64", na_value=0.0) == 1
    )
    baseline = fleet.apron_baseline(w[train_clean], profile)
    BASELINE_APRON_PATH.parent.mkdir(parents=True, exist_ok=True)
    baseline.to_parquet(BASELINE_APRON_PATH, index=False)
    # per scene: approach scenes share real clocks, so pooling would mix scenes and splits
    scene = windows["scene_id"].astype(str).to_numpy()
    ff = pd.concat(
        [
            fleet.fleet_features(
                w[scene == s].reset_index(drop=True), profile, baseline
            )
            for s in pd.unique(scene)
        ],
        ignore_index=True,
    )
    out = windows.drop(columns=[c for c in registry.FLEET_COLUMNS if c in windows])
    return out.merge(ff[KEYS + registry.FLEET_COLUMNS], on=KEYS, how="left")


# --- training --------------------------------------------------------------------


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=config.ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def train(
    windows: pd.DataFrame,
    splits: dict[str, list[str]],
    out_dir: Path = MODELS_DIR,
    points: pd.DataFrame | None = None,
    fleet: ModuleType | None = None,
) -> dict:
    """Train, calibrate and evaluate; write the models, calibration.json and model_card.json.

    `windows`: labeled feature table. `points`: the labeled points of the test
    scenes, for the naive baseline (None: baseline metrics are NaN).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    windows = windows.reset_index(drop=True)
    split = split_of(windows, splits).to_numpy()
    usable = ~windows["label_transition"].astype(bool).to_numpy()
    cause = windows["label_cause"].astype(str)
    y_int = schema.integrity_label(cause).to_numpy()
    y_cause = cause.map(CAUSE_INDEX).to_numpy()
    groups = windows["scene_id"].astype(str).to_numpy()
    rows = {k: usable & (split == k) for k in SPLITS}

    p1_cols = registry.MODEL_INPUTS_INTEGRITY_P1
    p2_cols = registry.MODEL_INPUTS_INTEGRITY_P2
    c_cols = registry.MODEL_INPUTS_CAUSE
    tr, ca, te = rows["train"], rows["calib"], rows["test"]

    # pass 1
    m1 = fit_integrity(windows[tr], y_int[tr], groups[tr], p1_cols)
    iso1 = fit_isotonic(m1.predict(matrix(windows[ca], p1_cols)), y_int[ca])

    # fleet features: out-of-fold pass 1 on train scenes, final pass 1 elsewhere
    use_fleet = fleet is not None
    if use_fleet:
        p1_all = m1.predict(matrix(windows, p1_cols))
        in_train = split == "train"
        tr_idx = np.flatnonzero(in_train)
        for fit_i, pred_i in GroupKFold(n_splits=params.N_FOLDS).split(
            tr_idx, groups=groups[tr_idx]
        ):
            fit_rows = tr_idx[fit_i][usable[tr_idx[fit_i]]]
            m = fit_integrity(
                windows.iloc[fit_rows], y_int[fit_rows], groups[fit_rows], p1_cols
            )
            p1_all[tr_idx[pred_i]] = m.predict(
                matrix(windows.iloc[tr_idx[pred_i]], p1_cols)
            )
        integrity1 = 100.0 * (1.0 - isotonic_apply(p1_all, iso1))
        dirty = pd.Series(cause != "plausible").groupby(groups).transform("any")
        train_clean = in_train & ~dirty.to_numpy()
        windows = add_fleet_features(windows, integrity1, train_clean, fleet)
    else:
        for c in registry.FLEET_COLUMNS:
            windows[c] = np.nan

    # pass 2 and cause
    m2 = fit_integrity(windows[tr], y_int[tr], groups[tr], p2_cols)
    iso2 = fit_isotonic(m2.predict(matrix(windows[ca], p2_cols)), y_int[ca])
    mc = fit_cause(windows[tr], y_cause[tr], groups[tr], c_cols)
    temp = fit_temperature(
        mc.predict(matrix(windows[ca], c_cols), raw_score=True), y_cause[ca]
    )

    for name, m in (("integrity_p1", m1), ("integrity_p2", m2), ("cause", mc)):
        m.save_model(str(out_dir / MODEL_FILES[name]))
    calibration = {
        "integrity_p1": iso1,
        "integrity_p2": iso2,
        "cause": {"temperature": temp},
    }
    (out_dir / CALIBRATION_FILE).write_text(json.dumps(calibration) + "\n")

    # test metrics, through the saved bundle
    bundle = load_bundle(out_dir)
    t = windows[te].reset_index(drop=True)
    yt = y_int[te]
    p1 = bundle.p_unsound(t, pass_=1)
    p2 = bundle.p_unsound(t, pass_=2)
    p2_raw = bundle.p_unsound(t, pass_=2, calibrated=False)
    cp = bundle.cause_probs(t).to_numpy()
    pred = np.asarray(schema.CAUSES)[cp.argmax(axis=1)]
    truth = cause[te].to_numpy()
    majority = pd.Series(truth).mode().iloc[0]
    labels = list(schema.CAUSES)

    if points is not None:
        b = naive_score(points)
        base = t[KEYS].merge(b, on=KEYS, how="left")["baseline_score"].fillna(0.0)
        baseline = binary_metrics(yt, base.to_numpy())
    else:
        baseline = {"auroc": float("nan"), "auprc": float("nan")}

    integrity2 = 100.0 * (1.0 - p2)
    normality = normality_score(dimension_scores(t)).to_numpy()
    behav = truth == "behavioral_anomaly"
    spoof = truth == "possible_spoofing"
    test_metrics = {
        "integrity_p1": binary_metrics(yt, p1),
        "integrity_p2": binary_metrics(yt, p2),
        "baseline": baseline,
        "calibration": {"ece_before": ece(p2_raw, yt), "ece_after": ece(p2, yt)},
        "cause": {
            "macro_f1": float(f1_score(truth, pred, labels=labels, average="macro")),
            "majority_macro_f1": float(
                f1_score(
                    truth,
                    np.full(len(truth), majority),
                    labels=labels,
                    average="macro",
                    zero_division=0,
                )
            ),
            "labels": labels,
            "confusion_matrix": confusion_matrix(truth, pred, labels=labels).tolist(),
        },
        "axes": {
            "behavioral_median_integrity": float(np.median(integrity2[behav])),
            "behavioral_abnormal_share": float(
                np.mean(normality[behav] < params.ABNORMAL_ENTER)
            ),
            "spoofing_median_normality": float(np.median(normality[spoof])),
        },
    }
    card = {
        "git_sha": git_sha(),
        "seed": params.SEED,
        "fleet": use_fleet,
        "inputs": dict(bundle.inputs),
        "counts": {
            k: {
                "scenes": len(splits[k]),
                "rows": int(rows[k].sum()),
            }
            for k in SPLITS
        },
        "trees": {k: b.num_trees() for k, b in bundle.boosters.items()},
        "test": test_metrics,
    }
    (out_dir / "model_card.json").write_text(json.dumps(card, indent=1) + "\n")
    return card


def load_test_points(test_scenes: list[str]) -> pd.DataFrame:
    cols = ["track_id", "t", "lat", "lon", "domain", "on_ground", "scene_id"]
    return pd.read_parquet(
        POINTS_PATH, columns=cols, filters=[("scene_id", "in", list(test_scenes))]
    )


def main(argv=None) -> None:
    argparse.ArgumentParser(prog="python -m divas_air.models.train").parse_args(argv)
    t0 = time.time()
    windows = pd.read_parquet(FEATURES_PATH)
    splits = load_or_make_splits(windows)
    points = load_test_points(splits["test"]) if POINTS_PATH.exists() else None
    card = train(windows, splits, points=points, fleet=fleet_module())
    print(json.dumps(card["test"], indent=1))
    print(f"fleet={card['fleet']} trees={card['trees']} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
