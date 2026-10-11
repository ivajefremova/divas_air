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
# feature-layer details (specs/03; values the spec states, or module 3 choices noted in STATUS)
DEGRADED_NACP_BELOW = 8.0  # GPSJam reproduction: a reading is degraded if NACp < 8
DEGRADED_ELIGIBLE_NACP = 8.0  # ... counted only once the track has reported NACp >= 8
MIN_HISTORY_S = 30.0  # trailing baselines are NaN until the track has this much history
MIN_JITTER_POINTS = 5  # quadratic jitter fit needs this many fixes
TURN_MIN_DPS = 1.0  # turn radius only where the turn rate exceeds this
# calibrated tau = max(default, this quantile of clean windows)
THRESHOLD_QUANTILE = 0.999
THRESHOLD_MIN_N = 100  # fewer clean windows than this: keep the registry default
# GNSS noise margin for "in a zone" (off-zone, allowed zone, speed limit)
ZONE_OCCUPANCY_MARGIN_M = 10.0
APPROACH_ALIGN_DEG = 30.0  # reported course within this of the runway bearing
# on final: height above threshold <= tan(this) x distance + floor
APPROACH_CONE_DEG = 6.0
APPROACH_CONE_FLOOR_M = 150.0
PHASE_LOW_M = 150.0  # "low" for the phase check, above aerodrome elevation
PHASE_AXIS_M = 500.0  # farther than this from every runway axis is "away"
# on_ground with baro altitude this far above the aerodrome
GROUND_ALT_CONFLICT_M = 300.0
AIRBORNE_MIN_MPS = 10.0  # airborne fixed-wing slower than this contradicts the flag

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
# LightGBM, shared by the three models. Modest capacity: the features carry the physics.
LGB_PARAMS = {
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 50,
    "feature_fraction": 1.0,
    "bagging_fraction": 1.0,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 8,
    "verbosity": -1,
}
LGB_MAX_TREES = 500
LGB_MIN_TREES = 50  # floor on the early-stopped tree count
LGB_EARLY_STOP = 50  # rounds without improvement on the grouped validation fold
LGB_VALID_FRAC = 0.2  # share of train scenes held out for early stopping
ECE_BINS = 15


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
# static halos: rings where the building elevation angle crosses these (degrees)
HALO_ELEVATION_DEG = (45.0, 30.0, 15.0)
HALO_SIMPLIFY_M = 1.0  # simplification tolerance of static halo polygons
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
GNSS_MODEL_OPEN_SIGMA_M = 1.5  # per-axis 1-sigma of the parametric model in open sky
# The model's absolute values give an open-sky median horizontal error of 1.79 m
# (Rayleigh median 1.177 x per-axis sigma, white term included). Scaled so the
# open-sky median is about 1.5 m. The scale multiplies every sigma, so the
# relative growth with obstruction is unchanged; static halos (module 5) read
# GNSS_OPEN_SIGMA_M and get the same scale.
GNSS_ERROR_SCALE = 0.84
GNSS_OPEN_SIGMA_M = GNSS_MODEL_OPEN_SIGMA_M * GNSS_ERROR_SCALE  # EPU 3.1 m -> NACp 10
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
SYNTH_GROUND_SCENES = 800  # enough for >= 150 events of every cause
# behavioral speeding: true speed = zone limit x U(ratio range), kept under the class max
SPEEDING_RATIO = (1.2, 1.8)
SPEEDING_CLASS_MARGIN = 0.95  # speeding stays below this share of the class max speed
SPEEDING_MIN_S = 20.0  # a speeding stretch lasts at least this long
