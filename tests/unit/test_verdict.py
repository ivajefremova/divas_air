import numpy as np
import pandas as pd

from divas_air import params, schema
from divas_air.verdict import (
    action_codes,
    evidence,
    normality_state,
    reported_cause,
    severity,
    smooth_and_state,
)

P = [f"p_{c}" for c in schema.CAUSES]


def test_smoothing_starts_from_the_first_value_and_stays_trusted():
    s, st = smooth_and_state(np.full(10, 90.0))
    assert np.allclose(s, 90) and set(st) == {"trusted"}


def test_first_window_state_from_entry_thresholds():
    assert smooth_and_state(np.array([30.0]))[1][0] == "untrusted"
    assert smooth_and_state(np.array([60.0]))[1][0] == "caution"


def test_normality_state_entry_is_strict():
    assert list(normality_state(np.array([params.ABNORMAL_ENTER]))) == ["expected"]


def test_untrusted_never_reports_a_sound_cause():
    cp = pd.DataFrame([[0.9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1]], columns=P)
    assert (
        reported_cause(["untrusted"], ["abnormal"], cp).iloc[0] in schema.UNSOUND_CAUSES
    )


def test_severity_nan_criticality_is_low():
    score, _ = severity([0.0], [100.0], [np.nan])
    assert np.isclose(score[0], params.CRITICALITY["low"])


def test_action_table_order():
    codes = action_codes(
        ["a1", None, None, None, None, None, None],
        [
            "caution",
            "untrusted",
            "untrusted",
            "trusted",
            "untrusted",
            "caution",
            "trusted",
        ],
        [
            "expected",
            "abnormal",
            "abnormal",
            "abnormal",
            "expected",
            "expected",
            "expected",
        ],
        [
            "trusted",
            "data_fault",
            "data_fault",
            "real_event",
            "silent_risk",
            "trusted",
            "trusted",
        ],
        ["low", "high", "low", "critical", "medium", "none", "none"],
    )
    assert list(codes) == [
        "area_gnss_unreliable",
        "verify_radio",
        "verify_visual",
        "act_now",
        "cross_check",
        "monitor",
        "none",
    ]


def test_evidence_split_and_template_values():
    row = pd.DataFrame(
        {
            "aux_domain": ["vehicle"],
            "aux_asset_class": ["bus"],
            "aux_class_max_speed_mps": [10.0],
            "aux_zone_name": ["Apron 1"],
            "aux_zone_speed_limit_mps": [8.3],
            "kin_speed_ratio_max": [3.0],
            "tmp_gap_max_s": [40.0],
            "kin_pos_jitter_m": [60.0],
            "ctx_zone_speed_ratio_max": [1.8],
        }
    )
    contrib = pd.DataFrame(
        {
            "kin_speed_ratio_max": [2.0],
            "tmp_gap_max_s": [1.0],
            "kin_pos_jitter_m": [0.5],
        }
    )
    viol = pd.DataFrame(
        0.0, index=[0], columns=["ctx_zone_speed_ratio_max", "spa_in_building_frac"]
    )
    viol.loc[0, "ctx_zone_speed_ratio_max"] = 0.75
    from divas_air.verdict import NORMALITY_FEATURES

    viol = viol.reindex(columns=NORMALITY_FEATURES, fill_value=0.0)
    both = evidence(
        row, np.array(["untrusted"]), np.array(["abnormal"]), contrib, viol
    )[0]
    assert [e["feature"] for e in both] == [
        "kin_speed_ratio_max",
        "tmp_gap_max_s",
        "ctx_zone_speed_ratio_max",
    ]
    assert both[0]["text"] == "Speed is 3.0x the maximum for a bus (10 m/s)"
    assert both[0]["limit"] == 1.5
    only = evidence(row, np.array(["caution"]), np.array(["expected"]), contrib, viol)[
        0
    ]
    assert len(only) == 3 and all(e["dimension"] != "contextual" for e in only)
    assert evidence(
        row, np.array(["trusted"]), np.array(["expected"]), contrib, viol
    ) == [[]]
