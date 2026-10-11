"""Training on a tiny in-memory feature table: artifacts, leak guard, determinism."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from divas_air import params, registry, schema
from divas_air.models import load_bundle
from divas_air.models.splits import load_or_make_splits
from divas_air.models.train import ece, train
from divas_air.verdict import assemble, to_contract
from tests.helpers import LAT0, LON0, T0

# feature that carries each cause's signature in the fixture
SIGNATURE = {
    "degraded": "sig_degraded_frac",
    "technical_error": "tmp_gap_max_s",
    "gnss_anomaly": "kin_pos_jitter_m",
    "possible_interference": "sig_nacp_drop",
    "possible_spoofing": "kin_speed_resid_max",
    "behavioral_anomaly": "ctx_zone_speed_ratio_max",
}


def _windows(n_scenes=42, tracks=3, n_w=40, seed=0, n_clean=6):
    rng = np.random.default_rng(seed)
    parts = []
    for s in range(n_scenes + n_clean):
        cause = schema.CAUSES[1 + s % 6]
        for k in range(tracks):
            f = pd.DataFrame(
                {c: rng.normal(0, 1, n_w) for c in registry.FEATURE_COLUMNS}
            )
            f["tmp_n_points"] = 10.0
            f["tmp_gap_max_s"] = np.abs(f["tmp_gap_max_s"]) + 2
            f["spa_zone_crit_max"] = 0.5
            lab = np.full(n_w, "plausible", dtype=object)
            if k == 0 and s < n_scenes:
                lab[20:35] = cause
                f.loc[20:34, SIGNATURE[cause]] += 30
            tid = f"synthetic:a{s}_{k}:0"
            f["track_id"] = tid
            f["t_end"] = T0 + 5.0 * np.arange(n_w) + 1000 * s
            f["aux_asset_id"] = f"a{s}_{k}"
            f["aux_domain"] = "vehicle"
            f["aux_asset_class"] = "bus"
            f["aux_callsign"] = None
            f["aux_lat"], f["aux_lon"] = LAT0, LON0
            f["aux_alt_m"] = np.nan
            f["aux_gs_mps"] = 5.0
            f["aux_track_deg"] = 90.0
            f["aux_airborne"] = False
            f["aux_speed_implied_mps"] = 5.0
            f["aux_speed_reported_mps"] = 5.0
            f["aux_class_max_speed_mps"] = 10.0
            f["aux_zone_id"] = "z1"
            f["aux_zone_name"] = "Apron 1"
            f["aux_zone_type"] = "apron"
            f["aux_zone_speed_limit_mps"] = 8.3
            f["label_cause"] = lab
            f["label_frac"] = (lab != "plausible").astype(float)
            f["label_transition"] = False
            f["scene_id"] = f"ground_{s:04d}"
            f["base_track_id"] = tid
            parts.append(f)
    return pd.concat(parts, ignore_index=True)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("models")
    w = _windows()
    splits = load_or_make_splits(w, out / "splits.json")
    card = train(w, splits, out_dir=out)
    return out, w, splits, card


def test_artifacts_and_card(trained):
    out, _, _, card = trained
    for f in (
        "integrity_p1.txt",
        "integrity_p2.txt",
        "cause.txt",
        "calibration.json",
        "model_card.json",
    ):
        assert (out / f).exists(), f
    assert card["fleet"] is False and card["seed"] == params.SEED
    assert card["inputs"]["integrity_p2"] == registry.MODEL_INPUTS_INTEGRITY_P2
    assert card["inputs"]["cause"] == registry.MODEL_INPUTS_CAUSE
    for name in card["inputs"].values():
        schema.assert_no_leakage(name)
    assert card["test"]["integrity_p1"]["auroc"] > 0.8
    assert np.asarray(card["test"]["cause"]["confusion_matrix"]).shape == (7, 7)


def test_bundle_outputs(trained):
    out, w, _, _ = trained
    b = load_bundle(out)
    x = w.head(200)
    p = b.p_unsound(x, pass_=2)
    assert p.shape == (200,) and (p >= 0).all() and (p <= 1).all()
    assert np.allclose(b.cause_probs(x).sum(axis=1), 1)
    c = b.contributions(x, pass_=1)
    assert list(c.columns) == registry.MODEL_INPUTS_INTEGRITY_P1


def test_training_is_deterministic(trained, tmp_path):
    out, w, splits, _ = trained
    train(w, splits, out_dir=tmp_path)
    for f in ("integrity_p1.txt", "integrity_p2.txt", "cause.txt", "calibration.json"):
        assert (out / f).read_bytes() == (tmp_path / f).read_bytes(), f


def test_fleet_hook_uses_out_of_fold_scores(tmp_path, monkeypatch):
    import divas_air.models.train as tr

    monkeypatch.setattr(tr, "BASELINE_APRON_PATH", tmp_path / "baseline_apron.parquet")
    seen = {}

    def apron_baseline(windows, profile):
        seen["baseline_rows"] = len(windows)
        return pd.DataFrame({"cell": ["x"], "baseline": [0.02]})

    def fleet_features(windows, profile, baseline=None):
        seen.setdefault("calls", 0)
        seen["calls"] += 1
        assert windows["t_end"].max() - windows["t_end"].min() < 1000, (
            "one scene per call"
        )
        ff = windows[["track_id", "t_end"]].copy()
        for c in registry.FLEET_COLUMNS:
            ff[c] = 0.0
        return ff

    fake = SimpleNamespace(apron_baseline=apron_baseline, fleet_features=fleet_features)
    w = _windows(seed=1)
    splits = load_or_make_splits(w, tmp_path / "splits.json")
    card = train(w, splits, out_dir=tmp_path, fleet=fake)
    assert card["fleet"] is True
    assert (tmp_path / "baseline_apron.parquet").exists()
    assert 0 < seen["baseline_rows"] < len(w)
    assert seen["calls"] == w["scene_id"].nunique()


def test_ece():
    p = np.array([0.1, 0.1, 0.9, 0.9])
    assert ece(p, np.array([0, 0, 1, 1])) == pytest.approx(0.1)


def test_assemble_on_trained_bundle(trained):
    out, w, _, _ = trained
    b = load_bundle(out)
    one = w[w["track_id"] == w["track_id"].iloc[0]]
    v = assemble(one.iloc[::-1], b)  # input order is kept
    assert (v["t_end"].to_numpy() == one["t_end"].to_numpy()[::-1]).all()
    for _, row in v.iterrows():
        verdict = to_contract(row)
        assert verdict.track_id == one["track_id"].iloc[0]
        assert len(verdict.evidence) <= 3
    bad = v[v["trust_state"] != "trusted"]
    assert len(bad), "the injected stretch must leave trusted"
    ev = json.loads(bad["evidence_json"].iloc[0])
    assert ev and all(e["text"] for e in ev)
