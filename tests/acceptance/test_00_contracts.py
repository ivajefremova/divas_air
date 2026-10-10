"""Module 0: the frozen contracts are internally consistent.

These pass on a fresh checkout. If one fails, a frozen file was edited:
revert it or get human approval (specs/00_contracts.md).
"""

import csv
import json

import numpy as np
import pytest

from divas_air import config, contract, params, registry, schema
from tests.helpers import make_track


def test_asset_classes_match_envelopes():
    with open(config.REFERENCE / "envelopes.csv", newline="") as f:
        cats = [r["category"] for r in csv.DictReader(f)]
    assert tuple(cats) == schema.ASSET_CLASSES


def test_aircraft_type_classes_are_envelope_categories():
    with open(config.REFERENCE / "aircraft_types.csv", newline="") as f:
        classes = {r["size_class"] for r in csv.DictReader(f)}
    assert classes <= set(schema.ASSET_CLASSES)


def test_causes_partition():
    assert len(schema.CAUSES) == 7
    assert set(schema.SOUND_CAUSES) | set(schema.UNSOUND_CAUSES) == set(schema.CAUSES)
    assert not set(schema.SOUND_CAUSES) & set(schema.UNSOUND_CAUSES)
    assert "behavioral_anomaly" in schema.SOUND_CAUSES


def test_registry_is_valid_and_leak_free():
    registry.validate_registry(registry.REGISTRY)
    schema.assert_no_leakage(registry.MODEL_INPUTS_CAUSE)
    assert not set(registry.MODEL_INPUTS_INTEGRITY_P1) & set(registry.columns("spatial", "contextual"))
    assert set(registry.FLEET_COLUMNS) <= set(registry.MODEL_INPUTS_INTEGRITY_P2)
    assert not set(registry.FLEET_COLUMNS) & set(registry.MODEL_INPUTS_INTEGRITY_P1)


def test_integrity_monotone_on_kinetic_and_temporal():
    for name in registry.columns("kinetic", "temporal"):
        if name != "tmp_n_points":
            assert registry.REGISTRY[name].monotone == 1, name


def test_leakage_guard_rejects_labels_and_identifiers():
    for bad in ("label_cause", "scene_id", "track_id", "lat", "t", "aux_lat", "p_plausible", "source"):
        with pytest.raises(schema.LeakageError):
            schema.assert_no_leakage(["kin_speed_resid_max", bad])


def test_validate_accepts_helper_track_and_rejects_bad_units():
    df = make_track(labeled=True)
    schema.validate(df)
    feet = df.copy()
    feet["alt_baro_m"] = 35000.0
    with pytest.raises(schema.SchemaError):
        schema.validate(feet)
    ms = df.copy()
    ms["t"] = ms["t"] * 1000.0
    with pytest.raises(schema.SchemaError):
        schema.validate(ms)
    dup = df.copy()
    dup.loc[dup.index[1], "seq"] = 0
    with pytest.raises(schema.SchemaError):
        schema.validate(dup)


def test_validate_allows_anomalous_values():
    df = make_track()
    df.loc[df.index[10], "t"] = df["t"].iloc[5]  # out of order
    df.loc[df.index[20], "gs_mps"] = 900.0  # impossible speed is data, not a schema error
    df.loc[df.index[30], ["lat", "lon"]] = [41.9, 12.4]  # jump
    schema.validate(df)


def test_integrity_label():
    lab = schema.integrity_label(make_track(labeled=True)["label_cause"])
    assert (lab == 0).all()


def test_examples_validate_against_contract():
    ex = config.ROOT / "contracts" / "examples"
    out = contract.VerdictsOut.model_validate_json((ex / "verdicts.json").read_text())
    assert {v.quadrant for v in out.verdicts} == {"trusted", "real_event", "data_fault", "silent_risk"}
    contract.RiskZones.model_validate_json((ex / "risk_zones.json").read_text())
    contract.TracksIn.model_validate_json((ex / "tracks_in.json").read_text())
    contract.ReplayFrame.model_validate_json((ex / "replay_frame.json").read_text())
    contract.ReplayManifest.model_validate_json((ex / "replay_manifest.json").read_text())


def test_json_schemas_are_current():
    path = config.ROOT / "contracts" / "verdict.schema.json"
    assert json.loads(path.read_text()) == contract.Verdict.model_json_schema(), (
        "contracts/ is stale: run python scripts/make_contract_examples.py"
    )


def test_quadrants():
    q = contract.quadrant_of
    assert q("trusted", "expected") == "trusted"
    assert q("caution", "expected") == "trusted"
    assert q("trusted", "abnormal") == "real_event"
    assert q("untrusted", "abnormal") == "data_fault"
    assert q("untrusted", "expected") == "silent_risk"


def test_params_are_coherent():
    assert params.UNTRUSTED_ENTER < params.UNTRUSTED_EXIT <= params.CAUTION_ENTER < params.CAUTION_EXIT
    assert params.BUFFER_S >= params.BASELINE_S + config.WINDOW_S
    assert params.RATE_BASE_S >= 5.0
    assert abs(sum(params.SPLIT_FRACTIONS.values()) - 1.0) < 1e-9
    levels = [x for x, _ in params.SEVERITY_LEVELS]
    assert levels == sorted(levels, reverse=True)
    assert np.isclose(config.WINDOW_S % config.STRIDE_S, 0)
