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
APRON = FleetProfile(
    "apron",
    h3_res=9,
    bin_s=60,
    min_tracks=3,
    cell_share_min=0.5,
    use_baseline_test=True,
)
# Regional: the GPSJam reproduction (red > 10 %, yellow > 2 %, >= 10 aircraft
# per hexagon per day). h3_res MUST equal the value used by the existing Baltic
# reproduction script; /bootstrap checks it and records it in DATA_INVENTORY.md.
REGIONAL = FleetProfile(
    "regional",
    h3_res=4,
    bin_s=86400,
    min_tracks=10,
    cell_share_min=0.10,
    use_baseline_test=False,
)
FLEET_PROFILES = {p.name: p for p in (APRON, REGIONAL)}
HALO_SIGMA_M = 150.0  # Gaussian kernel of live halos
FORECAST_HORIZONS_S = (30, 60)

# --- API (specs/06) ---------------------------------------------------------
REPLAY_STEP_S = 5  # = STRIDE_S
HISTORY_S = 300  # integrity history shown on the verdict card

# --- map layers (specs/02) --------------------------------------------------
# Half widths used to turn OSM centerlines and points into zone polygons.
RUNWAY_HALF_WIDTH_M = 30.0  # FCO runways are 60 m wide
TAXIWAY_HALF_WIDTH_M = 12.0  # code E taxiway ~23 m
SERVICE_ROAD_HALF_WIDTH_M = 4.0
HOLDING_POINT_RADIUS_M = 15.0
STAND_RADIUS_M = 30.0
AIRPORT_ELEVATION_M = (
    4.0  # LIRF 13 ft; runway threshold elevations are not in the layers
)
ZONE_CRITICALITY = {  # zone type -> CRITICALITY label (docs/DATA_INVENTORY.md gap 5)
    "runway": "high",
    "taxiway": "medium",
    "holding_point": "medium",
    "apron": "low",
    "stand": "low",
    "service_road": "low",
}
BUILDING_DEFAULT_HEIGHT_M = 6.0  # OSM buildings without height or levels
BUILDING_TALL_DEFAULT_M = 15.0  # hangars and terminals without height
BUILDING_LEVEL_M = 3.0

# --- GNSS error model (specs/02 section 2) ----------------------------------
# ASSUMPTION: the Decimeter-derived error model is not in data/ (DATA_INVENTORY
# lists no path), so these are parametric stand-ins with the same shape:
# open-sky sigma, scaled up with the highest building elevation angle.
GNSS_OPEN_SIGMA_M = (
    1.5  # per-axis 1-sigma in open sky (EPU 3.7 m -> NACp 10, as on fco)
)
GNSS_OBSTRUCTED_RATIO = 4.0  # error ratio at >= GNSS_FULL_OBSTRUCTION_DEG vs open sky
GNSS_FULL_OBSTRUCTION_DEG = 45.0
GNSS_WHITE_FRAC = 0.15  # white term, as a share of the Gauss-Markov sigma
GNSS_TAU_S = (20.0, 60.0)  # Gauss-Markov correlation time, drawn per track
BUILDING_SEARCH_M = 150.0  # buildings farther than this do not obstruct
OBSTRUCTION_GRID_M = 10.0  # resolution of the precomputed elevation-angle grid

# --- generator (specs/02) ---------------------------------------------------
SYNTH_T0 = 1_600_000_000.0  # ground scenes start at SYNTH_T0 + slot x SYNTH_SLOT_S
SYNTH_SLOT_S = 1200.0  # one slot per seed, so no two ground scenes share a clock
SPEED_NOISE_MPS = 0.1  # reported ground speed noise
COURSE_NOISE_DEG = 1.0  # reported course noise
T_JITTER_S = 0.05  # timestamp jitter, uniform +-
WORK_RADIUS_M = (
    1200.0  # vehicle destinations lie within this of the scene's work center
)
