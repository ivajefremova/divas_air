# 04 Scoring, models and verdict assembly

**Goal:** turn a feature table into verdicts: four dimension scores, a calibrated integrity score, a rule-based normality score, cause probabilities, confidence, severity, evidence and action.

**Depends on:** 00, 2, 3. **Owns:** `src/divas_air/scoring/`, `src/divas_air/models/`, `src/divas_air/verdict/`, `tests/unit/test_scoring*.py`, `test_models*.py`, `test_verdict*.py`.

Three parts, in this order. Part A and the pure functions of part C need no trained model and no data: build and test them first.

## Inputs

- `data/processed/features/synthetic.parquet` (labeled) for training; any feature table for scoring.
- `data/reference/dimension_thresholds.csv`, falling back to registry defaults when a row is missing.
- Fleet features (`registry.FLEET_COLUMNS`) when module 5 exists. Until then, pass 2 is trained with those columns as NaN and retrained later.

## Outputs

`artifacts/models/`: `integrity_p1.txt`, `integrity_p2.txt`, `cause.txt` (LightGBM text models), `calibration.json`, `splits.json`, `model_card.json`.

## Part A: deterministic scores (`divas_air.scoring`)

```python
def violations(features: pd.DataFrame) -> pd.DataFrame: ...       # one column per scored feature, values in [0, 1]
def dimension_scores(features: pd.DataFrame) -> pd.DataFrame: ... # d_kinetic, d_temporal, d_spatial, d_contextual in [0, 100]
def normality_score(dims: pd.DataFrame) -> pd.Series: ...         # min(d_spatial, d_contextual)

# divas_air/scoring/baseline.py
def naive_score(points: pd.DataFrame) -> pd.DataFrame: ...        # track_id, t_end, baseline_score in [0, 1], baseline_flag
```

1. Violation of feature `f`: `v = clip((x - tau) / scale, 0, 1)`, with tau and scale from `dimension_thresholds.csv` for the row's domain (`aux_domain`). NaN gives 0: no evidence is no violation.
2. Dimension score: `D = 100 * prod(1 - v)` over the scored features of that dimension. These are the four bars on the verdict card: fixed, explainable, identical for every track.
3. Normality is the minimum of the spatial and contextual scores. There is no separate rule engine: the weighted rules are the per-feature violations.
4. Naive baseline, the comparison for every metric: fixed thresholds on point-to-point quantities only. `baseline_score = max(clip(speed_p2p / V, 0, 1), clip(jump / J, 0, 1))` over the window's consecutive fixes, with `V` = 350 m/s airborne or 30 m/s on the ground, `J` = 500 m; `baseline_flag = baseline_score >= 1`. Same window grid as the features.

## Part B: learned models (`divas_air.models`)

```python
def load_bundle(path: Path | None = None) -> "ModelBundle": ...
class ModelBundle:
    def p_unsound(self, features: pd.DataFrame, pass_: int = 2, calibrated: bool = True) -> np.ndarray: ...
    def cause_probs(self, features: pd.DataFrame) -> pd.DataFrame: ...               # columns p_<cause>, rows sum to 1
    def contributions(self, features: pd.DataFrame, pass_: int = 2) -> pd.DataFrame: ...  # TreeSHAP per input, toward unsound
    inputs: dict[str, list[str]]   # "integrity_p1", "integrity_p2", "cause" -> feature names as stored in the models
```

CLI: `python -m divas_air.models.train`.

The bundle selects its inputs by name from whatever table it is given. Fleet columns that are absent from the table are treated as NaN, so pass 2 and the cause model can score a plain feature table.

5. **Splits.** Assign each `scene_id` to train, calib or test by `params.SPLIT_FRACTIONS`, seeded, stratified so each split has every cause. Write `splits.json` (`{"train": [...], "calib": [...], "test": [...]}`) once; if the file exists and covers every scene, reuse it.
6. **Rows.** Drop `label_transition` rows. Integrity target = `schema.integrity_label(label_cause)`.
7. **Integrity, pass 1.** LightGBM binary on `registry.MODEL_INPUTS_INTEGRITY_P1`, `monotone_constraints = registry.monotone_constraints(cols)`, class-weighted, early stopping on a grouped validation fold cut from train. Modest capacity (about 31 leaves, 300 to 500 trees, `min_data_in_leaf` 50): the data is small and the features carry the physics.
8. **Integrity, pass 2.** Same, on `MODEL_INPUTS_INTEGRITY_P2`. Fleet features for train scenes must come from out-of-fold pass-1 scores (`GroupKFold` by scene, `params.N_FOLDS`); for calib and test scenes from the final pass-1 model. When `divas_air.fleet` exists, training also writes `data/processed/fleet/baseline_apron.parquet` by calling `fleet.apron_baseline` on the clean train scenes, before computing fleet features. If module 5 does not exist yet, fleet columns are NaN and `model_card.json` says `"fleet": false`.
9. **Cause.** LightGBM multiclass over the seven causes on `MODEL_INPUTS_CAUSE`, class-weighted. No monotone constraints.
10. **Calibration** on the calib split only: isotonic regression for each integrity model, a single temperature for the cause model's raw scores. Store both in `calibration.json` so the bundle needs no pickle.
11. **Leak guard.** `schema.assert_no_leakage(cols)` immediately before every `fit`.
12. **Model card.** `model_card.json` holds git sha, seed, row and scene counts per split, the three input lists, `fleet`, and test-split metrics computed here, in this shape:

    ```json
    {"git_sha": "...", "seed": 42, "fleet": false,
     "inputs": {"integrity_p1": [], "integrity_p2": [], "cause": []},
     "counts": {"train": {"scenes": 0, "rows": 0}, "calib": {}, "test": {}},
     "test": {
       "integrity_p1": {"auroc": 0.0, "auprc": 0.0},
       "integrity_p2": {"auroc": 0.0, "auprc": 0.0},
       "baseline": {"auroc": 0.0, "auprc": 0.0},
       "calibration": {"ece_before": 0.0, "ece_after": 0.0},
       "cause": {"macro_f1": 0.0, "majority_macro_f1": 0.0, "labels": [], "confusion_matrix": [[]]},
       "axes": {"behavioral_median_integrity": 0.0, "behavioral_abnormal_share": 0.0, "spoofing_median_normality": 0.0}
     }}
    ```

    The baseline is `naive_score` on the same rows. ECE uses 15 equal-width bins and is reported for the pass-2 model. `majority_macro_f1` is the macro-F1 of always predicting the most frequent cause.
13. **Axes stay separate.** On test rows labeled `behavioral_anomaly`, report median integrity (target at least 70) and the share with normality below 40. On test rows labeled `possible_spoofing`, report median normality. These go on the pitch slide.
14. **Deterministic**: two runs give identical model files.

## Part C: verdict assembly (`divas_air.verdict`)

```python
def smooth_and_state(integrity_raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...
    # one track, in time order -> (smoothed integrity, trust_state per window)
def normality_state(normality: np.ndarray) -> np.ndarray: ...          # one track, in time order
def confidence(n_points, gap_max_s, cause_probs: np.ndarray) -> tuple[np.ndarray, np.ndarray]: ...  # value, level
def severity(integrity, normality, zone_criticality) -> tuple[np.ndarray, np.ndarray]: ...          # score, level
def reported_cause(trust_state, normality_state, cause_probs: pd.DataFrame) -> pd.Series: ...
def assemble(features: pd.DataFrame, bundle: ModelBundle, fleet: pd.DataFrame | None = None,
             area_alerts: pd.DataFrame | None = None) -> pd.DataFrame: ...   # flat verdict table, 00 section 6
def to_contract(row) -> contract.Verdict: ...
```

15. **Smoothing.** `s[0] = raw[0]`; `s[k] = a * raw[k] + (1 - a) * s[k-1]` with `a = EMA_ALPHA_DOWN` if `raw[k] < s[k-1]` else `EMA_ALPHA_UP`.
16. **Trust state with hysteresis**, on the smoothed score: `untrusted` once it falls below `UNTRUSTED_ENTER`, until it rises above `UNTRUSTED_EXIT`; otherwise `caution` once below `CAUTION_ENTER`, until above `CAUTION_EXIT`; otherwise `trusted`. Leaving `untrusted` lands in `caution` if the score is not above `CAUTION_EXIT`.
17. **Normality state**: `abnormal` once normality falls below `ABNORMAL_ENTER`, until it rises above `ABNORMAL_EXIT`. No smoothing.
18. **Reported cause.** `trusted`: `behavioral_anomaly` if abnormal, else `plausible`. `untrusted`: the most probable of `schema.UNSOUND_CAUSES`. `caution`: the argmax of all seven.
19. **Confidence** = `min(c_points, c_gap) * c_margin`, with `c_points = clip(n / (2 * MIN_POINTS), 0.25, 1)`, `c_gap = clip(1 - (gap_max_s - 5) / 25, 0.25, 1)`, `c_margin = 1` if the top two cause probabilities differ by at least `CAUSE_MARGIN`, else 0.6. Levels by `CONF_HIGH` and `CONF_MEDIUM`.
20. **Severity** score = `max(1 - integrity / 100, 1 - normality / 100) * zone_criticality`, using smoothed integrity and `spa_zone_crit_max` (NaN counts as `CRITICALITY["low"]`). Level by `params.SEVERITY_LEVELS`.
21. **Evidence**, at most `MAX_EVIDENCE` sentences, chosen from the two states (not from the quadrant, which folds `caution` into "data usable"):
    - integrity sentences when `trust_state` is `caution` or `untrusted`: the inputs with the largest positive TreeSHAP contribution toward unsound;
    - normality sentences when `normality_state` is `abnormal`: the spatial and contextual features with the largest violation;
    - both apply: two integrity sentences and one normality sentence; only one applies: up to three of that kind; neither: none.

    Fill the registry template with `v` = the feature value and the `aux_*` fields; skip a feature whose template is empty or whose fields are missing and take the next. `limit` is the feature's tau.
22. **Action**, fixed text per code, zone name and class filled in. First matching row wins:

    | Condition | Code |
    |---|---|
    | `area_alert_id` set and `trust_state` is not `trusted` | `area_gnss_unreliable` |
    | quadrant `data_fault`, severity critical or high | `verify_radio` |
    | quadrant `data_fault`, lower severity | `verify_visual` |
    | quadrant `real_event`, severity critical or high | `act_now` |
    | quadrant `silent_risk`, severity medium or above | `cross_check` |
    | anything left where `trust_state` is not `trusted` or `normality_state` is `abnormal` | `monitor` |
    | otherwise | `none` |

    Wording: action first, plain verbs, no ML terms, every number with a unit.
23. `assemble` applies the state machines per track in time order and returns one row per input row. `to_contract` must produce a model that validates.

## Acceptance (`tests/acceptance/test_04_models.py`)

Pure functions:
- violations, dimension scores and normality behave as defined, NaN included;
- smoothing and hysteresis: a drop is felt at once, a score hovering between 40 and 55 does not flicker, recovery passes through `caution`;
- reported cause never contradicts the state; confidence and severity follow their formulas.

Trained models:
- `splits.json` is a partition of scenes, and no `base_track_id` crosses splits;
- model inputs equal the registry lists and pass the leak guard;
- integrity is monotone: raising any constrained input never raises integrity;
- test AUROC and AUPRC beat the baseline, with AUROC at least 0.80; ECE is reported, does not get worse with calibration and is below 0.10; cause macro-F1 beats the majority class and is at least 0.50;
- the model card's AUROC matches an independent recomputation;
- behavioral anomalies keep high integrity (median at least 70);
- `assemble` and `to_contract` produce contract-valid verdicts.

The numeric floors are sanity bounds, not targets. If the honest value is below one, report it and stop; do not chase it by touching the test split.

Report in `docs/STATUS.md`: AUROC and AUPRC (both passes and baseline), macro-F1, ECE before and after, the axes numbers.
