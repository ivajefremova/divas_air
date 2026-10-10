# Status

One row per module. Update it when you start and when you finish a module: state, date, the measured headline numbers, and anything the next module needs to know. Measured values only.

| # | Module | State | Updated | Headline numbers | Open items |
|---|---|---|---|---|---|
| 0 | Contracts | done | 2026-10-10 | 13 contract tests pass | |
| 1 | Ingest | done | 2026-10-10 | fco 1,108,346 rows / 12,688 tracks / 2,781 aircraft / 8 days, typed 97.4 %; baltic 285,211 / 1,730 / 628 / 1 day, typed 87.7 %; control 1,190,201 / 8,020 / 3,506 / 1 day, typed 87.8 %. Rows dropped: 0 (no missing t/lat/lon). Byte-identical reruns, about 12 s for all three | adr_mock, lira: no data; `alt_geom_m`, `heading_deg` 100 % NaN |
| 2 | Generator | not started | | scenes; points per cause; noise RMS | |
| 3 | Features | not started | | over-limit share on clean `fco`; runtime; features still NaN | |
| 4 | Models | not started | | AUROC, AUPRC vs baseline; macro-F1; ECE before and after | |
| 5 | Fleet | not started | | Baltic red / qualifying cells; control cells above 2 % | |
| 6 | API | not started | | step latency; seconds to detect each demo event | |
| 8 | Evaluation | not started | | false alarms per 1,000 track-minutes; median time to detect | |

## Notes

### Module 1 (ingest), 2026-10-10

- Inputs are the flattened, already-SI `data/processed/adsblol_{fco,jam,control}_*.parquet` files (`scripts/filter_adsblol.py`); `data/raw/` does not exist here. Ingest maps columns and does not convert units.
- Null shares after the per-track forward-fill of `nacp`/`nic`/`sil`:
  - fco: gs 1.1 %, nacp 2.9 %, nic 1.7 %, alt_baro 3.9 %, track 1.5 %, vrate 3.4 %
  - baltic: gs 22.4 %, nacp 16.5 %, nic 0.9 %, alt_baro 27.6 %, track 27.1 %, vrate 29.6 %
  - control: gs 1.2 %, nacp 2.8 %, nic 1.0 %, alt_baro 4.5 %, track 2.1 %, vrate 5.6 %
- Human decision: baro altitudes above the 20,000 m bound in `schema.validate` are set to NaN and counted, not dropped. This hit 148 control fixes of one C130 (icao 010078, 31,821 m reported).
- Human decision: `schema.LABEL_COLUMNS` was added as a public alias (commit 7075ad5); `test_01_ingest` reads it.
- `on_ground` is NA where the source gave neither "ground" nor an altitude. The filter script wrote False there.
- **For module 3:** real data has no out-of-order fixes, because the upstream script writes each trace sorted by time. Duplicate timestamps do occur (fco 302, baltic 5,502, control 169). Out-of-order signal comes from synthetic injection only.
- **For module 3:** `alt_geom_m` and `heading_deg` are all NaN because `filter_adsblol.py` never read them. Raw readsb traces may carry `alt_geom` and `true_heading`; this is unchecked because `data/raw/` is absent. Re-flattening the raw traces would bring back the altitude-divergence and heading-vs-track signal.
- `make lint` fails repo-wide on pre-existing issues: 9 in `scripts/`, 9 in frozen `tests/acceptance/` files. Module 1 files are clean.

