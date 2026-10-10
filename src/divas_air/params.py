"""Tunable constants of the trust engine, in one place.

Paths, CRS, area boxes, WINDOW_S and STRIDE_S live in config.py. Everything
else that a spec refers to by name lives here. Change a value here, never
inline in a module. Thresholds that are fitted on data are NOT here: they are
written to data/reference/dimension_thresholds.csv by the feature layer.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- windows and features (specs/03) ---------------------------------------
RATE_BASE_S = 5.0  # every rate is computed over at least this many seconds
MIN_POINTS = 4  # below this a window is scored but confidence is low
BASELINE_S = 300.0  # trailing span for per-track baselines (dt, NACp, alt divergence)
BUFFER_S = 330.0  # points kept per track online; must be >= BASELINE_S + WINDOW_S
TRACK_GAP_SPLIT_S = 300.0  # a longer silence starts a new track_id
LIMIT_MARGIN = 1.5  # tau for envelope-ratio features = class limit x this
MOVING_MPS = 1.0  # "moving" for frozen-position checks
COURSE_MIN_MPS = 3.0  # below this, course and turn rate are undefined
COURSE_MIN_DISP_M = 20.0  # minimum displacement for an implied course
ZONE_BUFFER_M = 50.0  # "next to" a zone, for severity
DWELL_MOVE_M = 10.0  # displacement that resets the dwell timer
APPROACH_FINAL_KM = 10.0  # approach features apply inside this distance
GLIDESLOPE_DEG = 3.0

# --- labels (specs/03, specs/04) -------------------------------------------
LABEL_POS_FRAC = 1.0 / 3.0  # window is anomalous if >= this share of its points is
# 0 < share < LABEL_POS_FRAC -> label_transition=True: excluded from training
# and from classification metrics, kept for time-to-detect.

# --- verdict assembly (specs/04) -------------------------------------------
UNTRUSTED_ENTER, UNTRUSTED_EXIT = 40.0, 55.0  # on smoothed integrity
CAUTION_ENTER, CAUTION_EXIT = 70.0, 75.0
ABNORMAL_ENTER, ABNORMAL_EXIT = 40.0, 55.0  # on normality
EMA_ALPHA_DOWN = 0.7  # weight of the new value when the score falls (fast attack)
EMA_ALPHA_UP = 0.3  # weight of the new value when it recovers (slow release)
CAUSE_MARGIN = 0.2  # top-2 causes closer than this -> lower confidence
CONF_HIGH, CONF_MEDIUM = 0.75, 0.45
# severity score = max(1 - integrity/100, 1 - normality/100) x zone criticality
SEVERITY_LEVELS: tuple[tuple[float, str], ...] = (
    (0.60, "critical"),
    (0.40, "high"),
    (0.20, "medium"),
    (0.05, "low"),
)  # below the last threshold: "none"
CRITICALITY = {"high": 1.0, "medium": 0.5, "low": 0.2}  # map-layer label -> [0, 1]
CRITICALITY_AIRBORNE_FINAL = 1.0  # airborne inside APPROACH_FINAL_KM of a runway
CRITICALITY_AIRBORNE_OTHER = 0.5
MAX_EVIDENCE = 3

# --- models (specs/04) ------------------------------------------------------
SEED = 42
SPLIT_FRACTIONS = {"train": 0.6, "calib": 0.2, "test": 0.2}  # by scene_id
N_FOLDS = 5  # GroupKFold over train scenes, for out-of-fold pass-1 scores
REAL_HOLDOUT_DAYS = 2  # last N days of `fco` are never seen by training


# --- fleet layer (specs/05) -------------------------------------------------
@dataclass(frozen=True)
class FleetProfile:
    name: str
    h3_res: int
    bin_s: int
    min_tracks: int  # tracks needed in a cell-bin before it can be flagged
    cell_share_min: float  # flagged if degraded share > this
    use_baseline_test: bool  # also require a significant excess over the cell baseline
    alpha: float = 0.01  # one-sided binomial test level
    baseline_floor: float = 0.02  # lower bound on the baseline degraded rate
    k_ring: int = 1  # neighbor ring used by leave-one-out features
    warn_share: float = 0.02  # GPSJam "yellow" boundary (regional profile only)


# Apron: H3 res 9 is ~175 m edge. "Most of them degraded" = share > 0.5.
# bin_s is the presence span (tracks with a window in the last bin_s) and the alert hold.
APRON = FleetProfile("apron", h3_res=9, bin_s=60, min_tracks=3, cell_share_min=0.5, use_baseline_test=True)
# Regional: the GPSJam reproduction (red > 10 %, yellow > 2 %, >= 10 aircraft
# per hexagon per day). h3_res MUST equal the value used by the existing Baltic
# reproduction script; /bootstrap checks it and records it in DATA_INVENTORY.md.
REGIONAL = FleetProfile(
    "regional", h3_res=4, bin_s=86400, min_tracks=10, cell_share_min=0.10, use_baseline_test=False
)
FLEET_PROFILES = {p.name: p for p in (APRON, REGIONAL)}
HALO_SIGMA_M = 150.0  # Gaussian kernel of live halos
FORECAST_HORIZONS_S = (30, 60)

# --- API (specs/06) ---------------------------------------------------------
REPLAY_STEP_S = 5  # = STRIDE_S
HISTORY_S = 300  # integrity history shown on the verdict card
