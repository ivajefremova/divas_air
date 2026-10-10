"""Module 4 acceptance: beats the baseline; calibration error reported.

Spec: specs/04_models.md. Frozen: do not edit to make it pass.
Part 1 tests pure functions and needs no data. Part 2 needs trained models.
"""

import json

import numpy as np
import pandas as pd
import pytest

from divas_air import contract, params, registry, schema
from tests.helpers import MODELS, features_path, need

P_COLS = [f"p_{c}" for c in schema.CAUSES]


def frame(n: int = 1, domain: str = "vehicle", **values) -> pd.DataFrame:
    """A feature table with every feature NaN except the ones given."""
    f = pd.DataFrame({c: np.full(n, np.nan) for c in registry.FEATURE_COLUMNS + registry.FLEET_COLUMNS})
    f["aux_domain"] = domain
    for k, v in values.items():
        assert k in f.columns, k
        f[k] = v
    return f


def probs(**kw: float) -> list[float]:
    rest = (1.0 - sum(kw.values())) / (len(schema.CAUSES) - len(kw))
    return [kw.get(c, rest) for c in schema.CAUSES]


# === Part 1: deterministic scores and verdict logic ===============================


def test_violation_formula():
    from divas_air.scoring import violations

    f = frame(6, kin_speed_ratio_max=[1.0, 1.5, 2.25, 3.0, 5.0, np.nan])  # tau 1.5, scale 1.5
    v = violations(f)
    assert np.allclose(v["kin_speed_ratio_max"], [0, 0, 0.5, 1, 1, 0])
    assert v.to_numpy().min() >= 0 and v.to_numpy().max() <= 1
    assert set(v.columns) == {s.name for s in registry.REGISTRY.values() if s.scored}


def test_dimension_scores_are_products():
    from divas_air.scoring import dimension_scores

    f = frame(3, kin_speed_ratio_max=[2.25, 2.25, 1.0], kin_accel_ratio_max=[1.0, 2.25, 1.0])
    d = dimension_scores(f)
    assert list(d.columns) == ["d_kinetic", "d_temporal", "d_spatial", "d_contextual"]
    assert np.allclose(d["d_kinetic"], [50, 25, 100])
    assert np.allclose(d[["d_temporal", "d_spatial", "d_contextual"]], 100)
    assert np.allclose(dimension_scores(frame(2)), 100), "no evidence is no violation"


def test_normality_is_independent_of_data_quality():
    from divas_air.scoring import dimension_scores, normality_score

    f = frame(
        4,
        kin_speed_ratio_max=[5.0, 1.0, 1.0, 1.0],  # impossible speed: an integrity matter
        ctx_type_violation_crit_max=[0.0, 1.0, 0.0, 0.0],  # unauthorized on a runway
        spa_in_building_frac=[0.0, 0.0, 0.5, 0.0],  # tau 0.2, scale 0.6 -> v 0.5
    )
    n = normality_score(dimension_scores(f))
    assert np.allclose(n, [100, 0, 50, 100])


def test_smoothing_reacts_at_once_and_does_not_flicker():
    from divas_air.verdict import smooth_and_state

    s, st = smooth_and_state(np.array([95.0, 95, 5, 5, 5]))
    assert s[0] == 95 and st[0] == "trusted"
    assert np.isclose(s[2], params.EMA_ALPHA_DOWN * 5 + (1 - params.EMA_ALPHA_DOWN) * 95)
    assert st[2] == "untrusted", "a hard drop must be felt in the same window"

    raw = np.array([95.0, 5, 5, 50, 45, 52, 48, 50])
    s, st = smooth_and_state(raw)
    assert (st[1:] == "untrusted").all(), "hovering between 40 and 55 must not flicker"
    assert s.min() >= raw.min() - 1e-9 and s.max() <= raw.max() + 1e-9


def test_recovery_passes_through_caution():
    from divas_air.verdict import smooth_and_state

    _, st = smooth_and_state(np.array([95.0, 5, 5] + [100.0] * 30))
    st = list(st)
    assert st[-1] == "trusted"
    last_untrusted = max(i for i, x in enumerate(st) if x == "untrusted")
    assert st[last_untrusted + 1] == "caution"

    _, st = smooth_and_state(np.array([100.0, 65, 65, 65, 65]))
    assert st[-1] == "caution" and "untrusted" not in set(st)


def test_normality_state_hysteresis():
    from divas_air.verdict import normality_state

    st = normality_state(np.array([100.0, 30, 45, 50, 60, 100]))
    assert list(st) == ["expected", "abnormal", "abnormal", "abnormal", "expected", "expected"]


def test_reported_cause_never_contradicts_the_state():
    from divas_air.verdict import reported_cause

    cp = pd.DataFrame(
        [
            probs(possible_spoofing=0.6, plausible=0.3),  # trusted + expected
            probs(possible_spoofing=0.6, plausible=0.3),  # trusted + abnormal
            probs(plausible=0.5, technical_error=0.3),  # untrusted
            probs(behavioral_anomaly=0.5, gnss_anomaly=0.3),  # untrusted
            probs(degraded=0.5, plausible=0.3),  # caution
        ],
        columns=P_COLS,
    )
    trust = np.array(["trusted", "trusted", "untrusted", "untrusted", "caution"])
    norm = np.array(["expected", "abnormal", "expected", "abnormal", "expected"])
    out = list(reported_cause(trust, norm, cp))
    assert out == ["plausible", "behavioral_anomaly", "technical_error", "gnss_anomaly", "degraded"]


def test_confidence():
    from divas_air.verdict import confidence

    cp = np.array(
        [
            probs(plausible=0.9),
            probs(plausible=0.9),
            probs(plausible=0.9),
            probs(plausible=0.40, degraded=0.35),
        ]
    )
    value, level = confidence(np.array([30, 2, 30, 30]), np.array([1.0, 1.0, 30.0, 1.0]), cp)
    assert np.allclose(value, [1.0, 0.25, 0.25, 0.6])
    assert list(level) == ["high", "low", "low", "medium"]


def test_severity():
    from divas_air.verdict import severity

    integrity = np.array([8.0, 30, 98, 95, 30, 50, 10])
    normality = np.array([0.0, 100, 100, 0, 100, 100, 100])
    crit = np.array([1.0, 0.2, 1.0, 1.0, 0.5, 1.0, np.nan])
    score, level = severity(integrity, normality, crit)
    assert np.allclose(score, [1.0, 0.14, 0.02, 1.0, 0.35, 0.5, 0.18])
    assert list(level) == ["critical", "low", "none", "critical", "medium", "high", "low"]


# === Part 2: trained models ========================================================


@pytest.fixture(scope="module")
def splits() -> dict:
    return json.loads(need(MODELS / "splits.json").read_text())


@pytest.fixture(scope="module")
def card() -> dict:
    return json.loads(need(MODELS / "model_card.json").read_text())


@pytest.fixture(scope="module")
def bundle():
    from divas_air.models import load_bundle

    for name in ("integrity_p1.txt", "integrity_p2.txt", "cause.txt", "calibration.json"):
        need(MODELS / name)
    return load_bundle()


@pytest.fixture(scope="module")
def synth() -> pd.DataFrame:
    return pd.read_parquet(need(features_path("synthetic")))


@pytest.fixture(scope="module")
def held_out(synth, splits) -> pd.DataFrame:
    rows = synth[synth["scene_id"].isin(splits["test"]) & ~synth["label_transition"].astype(bool)]
    assert len(rows) > 500
    return rows.reset_index(drop=True)


def test_splits_partition_the_scenes(synth, splits):
    tr, ca, te = (set(splits[k]) for k in ("train", "calib", "test"))
    assert tr and ca and te
    assert not (tr & ca) and not (tr & te) and not (ca & te)
    assert tr | ca | te == set(synth["scene_id"].unique())

    which = {s: k for k in ("train", "calib", "test") for s in splits[k]}
    split_of = synth["scene_id"].map(which)
    assert synth.assign(split=split_of).groupby("base_track_id")["split"].nunique().max() == 1
    for k in ("train", "calib", "test"):
        assert set(synth.loc[split_of == k, "label_cause"]) == set(schema.CAUSES), f"{k} lacks a cause"


def test_model_inputs_are_the_registry_lists(bundle, card):
    expected = {
        "integrity_p1": registry.MODEL_INPUTS_INTEGRITY_P1,
        "integrity_p2": registry.MODEL_INPUTS_INTEGRITY_P2,
        "cause": registry.MODEL_INPUTS_CAUSE,
    }
    for name, cols in expected.items():
        assert list(bundle.inputs[name]) == cols, name
        assert list(card["inputs"][name]) == cols, name
        schema.assert_no_leakage(bundle.inputs[name])


def test_predictions_are_probabilities(bundle, held_out):
    x = held_out.head(2000)
    for pass_ in (1, 2):
        p = bundle.p_unsound(x, pass_=pass_)
        assert p.shape == (len(x),) and np.isfinite(p).all() and p.min() >= 0 and p.max() <= 1
    cp = bundle.cause_probs(x)
    assert list(cp.columns) == P_COLS
    assert np.allclose(cp.sum(axis=1), 1.0, atol=1e-6)
    contrib = bundle.contributions(x.head(50), pass_=1)
    assert list(contrib.columns) == registry.MODEL_INPUTS_INTEGRITY_P1
    assert np.isfinite(contrib.to_numpy()).all()


@pytest.mark.parametrize("pass_", [1, 2])
def test_integrity_is_monotone(bundle, held_out, pass_):
    """Raising a kinetic or temporal violation never raises integrity."""
    cols = bundle.inputs[f"integrity_p{pass_}"]
    x = held_out.sample(min(300, len(held_out)), random_state=params.SEED).reset_index(drop=True)
    for col in cols:
        if registry.REGISTRY[col].monotone != 1:
            continue
        # fleet columns are absent from a plain feature table: sweep a fixed grid
        seen = held_out[col].dropna() if col in held_out else pd.Series([0.0, 0.25, 0.5, 1.0, 3.0])
        if seen.empty:
            continue
        grid = np.unique(np.concatenate([np.quantile(seen, [0.05, 0.5, 0.9, 0.99]), [seen.max() * 2 + 1]]))
        prev = None
        for value in grid:
            p = bundle.p_unsound(x.assign(**{col: value}), pass_=pass_)
            if prev is not None:
                assert (p >= prev - 1e-9).all(), f"{col}: P(unsound) fell as the violation rose"
            prev = p


def test_reported_metrics_beat_the_baseline(card):
    t = card["test"]
    assert t["integrity_p2"]["auroc"] > t["baseline"]["auroc"]
    assert t["integrity_p2"]["auprc"] > t["baseline"]["auprc"]
    assert t["integrity_p2"]["auroc"] >= 0.80
    assert t["cause"]["macro_f1"] > t["cause"]["majority_macro_f1"]
    assert t["cause"]["macro_f1"] >= 0.50
    assert t["cause"]["labels"] == list(schema.CAUSES)
    assert np.asarray(t["cause"]["confusion_matrix"]).shape == (7, 7)


def test_calibration_is_reported_and_helps(card):
    cal = card["test"]["calibration"]
    assert 0 <= cal["ece_after"] <= cal["ece_before"] + 0.01
    assert cal["ece_after"] < 0.10


def test_model_card_matches_an_independent_recomputation(bundle, card, held_out):
    from sklearn.metrics import roc_auc_score

    y = schema.integrity_label(held_out["label_cause"]).astype(int)
    auroc = roc_auc_score(y, bundle.p_unsound(held_out, pass_=1))
    assert abs(auroc - card["test"]["integrity_p1"]["auroc"]) < 0.01


def test_behavior_does_not_lower_integrity(bundle, card, held_out):
    """The two axes are separate: a real incursion keeps trusted data."""
    assert card["test"]["axes"]["behavioral_median_integrity"] >= 70
    behav = held_out[held_out["label_cause"] == "behavioral_anomaly"]
    assert len(behav) > 30
    integrity = 100 * (1 - bundle.p_unsound(behav, pass_=1))
    assert np.median(integrity) >= 70


def test_assemble_produces_valid_contract_verdicts(bundle, held_out):
    from divas_air.verdict import assemble, to_contract

    track = held_out["track_id"].iloc[0]
    one = held_out[held_out["track_id"] == track].sort_values("t_end")
    v = assemble(one, bundle)
    assert len(v) == len(one)
    need_cols = {
        "integrity_raw",
        "integrity",
        "normality",
        "trust_state",
        "normality_state",
        "quadrant",
        "confidence",
        "cause",
        "severity_score",
        "severity_level",
        "action_code",
        "evidence_json",
    }
    assert need_cols | set(P_COLS) <= set(v.columns)
    for _, row in v.head(60).iterrows():
        verdict = to_contract(row)
        assert isinstance(verdict, contract.Verdict)
        assert verdict.track_id == track


def test_training_is_deterministic(card):
    assert card["seed"] == params.SEED
