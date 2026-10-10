# 08 Evaluation report

**Goal:** one command regenerates every number and figure on the evidence slide, each against the naive baseline.

**Depends on:** 00, 4, 5. **Owns:** `src/divas_air/eval/`, `tests/unit/test_eval*.py`.

The judges' sharpest question is whether results on our own synthetic data are circular. The answer is this report: held-out synthetic scenes, real traffic the models never saw, a real jamming day, and ADR's own scenarios if they arrive. Report what is measured. A weak number that is true is worth more on stage than a strong one that falls apart under one question.

## Inputs

`artifacts/models/` (models, `splits.json`, `model_card.json`), `features/*.parquet`, `verdicts/*.parquet`, `points/*.parquet`, `synth/events.parquet`, `fleet/*_regional_cells.parquet`.

## Outputs

- `reports/metrics.json`
- `reports/REPORT.md`: one table of every metric next to its baseline, and the figures
- `reports/figures/confusion_matrix.png`, `reliability.png`, `time_to_detect.png`, `false_alarms.png`, `baltic_vs_control.png`
- `reports/baltic_cells.geojson`: our red and yellow cells, for the map next to GPSJam

CLI: `python -m divas_air.eval.report`. Runs with whatever sources exist and writes `null` with a reason for a section whose inputs are missing.

## Requirements

1. **Synthetic benchmark**, test scenes only, transition windows dropped: integrity AUROC and AUPRC for the model and for `naive_score` on the same rows; cause macro-F1 and confusion matrix for the cause model's argmax and for the reported cause.
2. **Calibration**, test scenes: ECE (15 equal-width bins) before and after isotonic calibration; the reliability diagram.
3. **Time to detect**: for each event in test scenes, seconds from `t_onset` to the first window where an affected track's `trust_state` is `untrusted` (unsound causes) or `normality_state` is `abnormal` (`behavioral_anomaly`). Report median, 90th percentile and detected share (within the event's duration), overall and per cause, and the same for the baseline flag.
4. **Real false alarms**: on the held-out `fco` days only, assumed nominal: `untrusted` verdicts per 1,000 track-minutes, counted as entries into the state (not windows), and the same for the baseline. Also the share of track-minutes spent `untrusted`.
5. **Real interference**: from the regional cell tables: Baltic qualifying cells, red cells, red share; control qualifying cells and cells above 2 %; next to the reference 82 / 109 and 0 / 172.
6. **ADR scenarios**, only if `points/adr_mock.parquet` exists: requirement 1's metrics on them. They were never in training; say so in the report.
7. **Transfer**, only if `verdicts/lira.parquet` exists: the false-alarm rate of requirement 4 on Ciampino with no retraining.
8. Every reported number comes from the test split, the held-out days or real interference data. Nothing from train or calib is reported as a result.
9. Deterministic: two runs give identical `metrics.json` except `meta.generated_at`. Never write NaN or Infinity: a value that cannot be computed (a median over zero detections, for example) is `null`.
10. Figures are for a projected slide: one message per figure stated in its title, at least 14 pt text, the model and the baseline in two clearly different colors that also differ in lightness, values labeled directly on bars, no gridline clutter, 200 dpi, 16:9.

## `metrics.json` shape

```json
{
  "meta": {"git_sha": "...", "seed": 42, "generated_at": "...", "fleet": true},
  "synthetic": {
    "n_windows": 0, "n_scenes": 0,
    "integrity": {"auroc": 0.0, "auprc": 0.0, "baseline_auroc": 0.0, "baseline_auprc": 0.0},
    "cause": {"macro_f1": 0.0, "macro_f1_reported": 0.0, "labels": [], "confusion_matrix": [[]]},
    "calibration": {"ece_before": 0.0, "ece_after": 0.0}
  },
  "time_to_detect": {"n_events": 0, "median_s": 0.0, "p90_s": 0.0, "detected_share": 0.0,
                     "baseline_median_s": 0.0, "baseline_detected_share": 0.0, "by_cause": {}},
  "real_false_alarms": {"track_minutes": 0.0, "untrusted_per_1000_track_min": 0.0,
                        "untrusted_time_share": 0.0, "baseline_per_1000_track_min": 0.0},
  "real_interference": {"baltic_cells": 0, "baltic_red": 0, "control_cells": 0, "control_above_2pct": 0,
                        "reference": {"baltic_cells": 109, "baltic_red": 82, "control_cells": 172, "control_above_2pct": 0}},
  "adr": null,
  "transfer": null
}
```

A section that cannot be computed is `{"skipped": "<reason>"}` or `null`.

## Acceptance (`tests/acceptance/test_08_evaluation.py`)

- the command exits 0 and writes `metrics.json`, `REPORT.md` and the five figures;
- `metrics.json` has the sections and keys above, with finite numbers where inputs exist;
- the synthetic section reports only test scenes; the model beats the baseline on AUROC, AUPRC and detected share;
- two runs agree.

Report in `docs/STATUS.md` the four headline numbers for the slide: AUROC versus baseline, ECE after calibration, median time to detect, false alarms per 1,000 track-minutes.
