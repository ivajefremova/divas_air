"""Module 8 acceptance: every pitch figure regenerates from one command.

Spec: specs/08_evaluation.md. Frozen: do not edit to make it pass.
"""

import json
import math
import os
import subprocess
import sys

import pandas as pd
import pytest

from divas_air import config
from tests.helpers import MODELS, REPORTS, need

FIGURES = (
    "confusion_matrix.png",
    "reliability.png",
    "time_to_detect.png",
    "false_alarms.png",
    "baltic_vs_control.png",
)


def run_report() -> dict:
    env = dict(os.environ, PYTHONPATH=str(config.ROOT / "src"), MPLBACKEND="Agg")
    subprocess.run(
        [sys.executable, "-m", "divas_air.eval.report"], cwd=config.ROOT, env=env, check=True, timeout=1800
    )
    return json.loads((REPORTS / "metrics.json").read_text())


@pytest.fixture(scope="module")
def metrics() -> dict:
    need(MODELS / "model_card.json")
    return run_report()


def finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def test_outputs_exist(metrics):
    assert (REPORTS / "REPORT.md").stat().st_size > 500
    for name in FIGURES:
        assert (REPORTS / "figures" / name).stat().st_size > 5000, name
    assert "baseline" in (REPORTS / "REPORT.md").read_text().lower()


def test_sections_and_keys(metrics):
    assert {
        "meta",
        "synthetic",
        "time_to_detect",
        "real_false_alarms",
        "real_interference",
        "adr",
        "transfer",
    } <= set(metrics)
    syn = metrics["synthetic"]
    for k in ("auroc", "auprc", "baseline_auroc", "baseline_auprc"):
        assert finite(syn["integrity"][k]) and 0 <= syn["integrity"][k] <= 1, k
    assert finite(syn["cause"]["macro_f1"]) and finite(syn["cause"]["macro_f1_reported"])
    assert len(syn["cause"]["confusion_matrix"]) == len(syn["cause"]["labels"]) == 7
    assert finite(syn["calibration"]["ece_before"]) and finite(syn["calibration"]["ece_after"])

    ttd = metrics["time_to_detect"]
    assert ttd["n_events"] > 0
    assert finite(ttd["median_s"]) and ttd["median_s"] >= 0
    assert 0 <= ttd["detected_share"] <= 1 and 0 <= ttd["baseline_detected_share"] <= 1
    assert ttd["by_cause"]

    fa = metrics["real_false_alarms"]
    assert fa["track_minutes"] > 0
    assert finite(fa["untrusted_per_1000_track_min"]) and fa["untrusted_per_1000_track_min"] >= 0
    assert finite(fa["baseline_per_1000_track_min"])
    assert 0 <= fa["untrusted_time_share"] <= 1


def test_model_beats_the_baseline_on_held_out_scenes(metrics):
    integ = metrics["synthetic"]["integrity"]
    assert integ["auroc"] > integ["baseline_auroc"]
    assert integ["auprc"] > integ["baseline_auprc"]
    ttd = metrics["time_to_detect"]
    assert ttd["detected_share"] > ttd["baseline_detected_share"]


def test_only_test_scenes_are_reported(metrics):
    splits = json.loads((MODELS / "splits.json").read_text())
    assert metrics["synthetic"]["n_scenes"] == len(splits["test"])


def test_real_interference_matches_the_cell_tables(metrics):
    ri = metrics["real_interference"]
    baltic = pd.read_parquet(need(config.PROCESSED / "fleet" / "baltic_regional_cells.parquet"))
    control = pd.read_parquet(need(config.PROCESSED / "fleet" / "control_regional_cells.parquet"))
    assert ri["baltic_cells"] == len(baltic)
    assert ri["baltic_red"] == int((baltic["level"] == "red").sum())
    assert ri["control_cells"] == len(control)
    assert ri["control_above_2pct"] == int((control["share"] > 0.02).sum())
    assert ri["reference"] == {
        "baltic_cells": 109,
        "baltic_red": 82,
        "control_cells": 172,
        "control_above_2pct": 0,
    }


def test_report_is_deterministic(metrics):
    again = run_report()
    a = {k: v for k, v in metrics.items() if k != "meta"}
    b = {k: v for k, v in again.items() if k != "meta"}
    assert a == b
    strip = lambda m: {k: v for k, v in m["meta"].items() if k != "generated_at"}  # noqa: E731
    assert strip(metrics) == strip(again)
