"""Tunables of the ADR per-sample scorer (`divas_air.adr`).

Kept apart from `params.py`, which another session owns. There are no labels:
values come from physical limits and from the bulk of ADR's own asset_tracks
(quantiles quoted next to each value), and lean toward not flagging.
Measured on 2026-10-11, dataset version 1.2.
"""

from __future__ import annotations

# --- common ----------------------------------------------------------------------

# Every rate is a displacement over at least this span (params.RATE_BASE_S).
RATE_BASE_S = 5.0
# A pause in the 1 Hz stream longer than this is a loss of fix (ADR: 9 gaps of 33-86 s,
# every other step is exactly 1.000 s). Windows never straddle such a gap.
GAP_S = 3.0
# Moving / stopped on the >= 5 s implied speed (params.MOVING_MPS for moving).
MOVING_MPS = 1.0
STOPPED_MPS = 0.5

# --- signal ------------------------------------------------------------------------

# fix_loss: samples labeled on each side of a gap.
FIX_LOSS_PAD_BEFORE = 1
FIX_LOSS_PAD_AFTER = 1

# frozen_position: identical lat/lon repeated for at least this long, with evidence of
# motion (reported speed, implied speed before the freeze, or the catch-up after it).
# ADR's speed is position-derived, so a frozen fix reports 0 km/h; real stationary
# receivers jitter (only 638 identical consecutive fixes in 664,573, all but 3 in runs >= 20 s).
FROZEN_MIN_S = 5.0

# Step innovation: |1 s step - step predicted from the >= 5 s velocity on either side|.
# ADR bulk: median 0.90 m, p99 2.96 m, p99.9 13.5 m.
JUMP_M = 10.0
# A step back within this time whose vector cancels the step out closes the jump.
JUMP_MAX_S = 300.0
JUMP_RETURN_FRAC = 0.5  # |out + back| < frac * |out|

# multipath_noise: centered running median of the step innovation over this many samples
# above MULTIPATH_M, for at least MULTIPATH_MIN_S samples. A median ignores one or two steps.
# ADR bulk of the 11-sample median: median 0.90 m, p90 1.29 m, p99 1.97 m.
MULTIPATH_WIN = 11
MULTIPATH_M = 3.0
MULTIPATH_MIN_S = 5

# implausible_speed: reported speed and the >= 5 s implied speed both above
# SPEED_FACTOR x the class's envelope ground speed (the feature layer's LIMIT_MARGIN),
# or reported speed contradicting the implied speed, on a smooth path.
SPEED_FACTOR = 1.5
# Ground speed bound for classes without an envelope (m/s, 100 km/h).
SPEED_ABS_MPS = 27.8
SPEED_RESID_MPS = 5.0  # |reported - implied| above max(this, SPEED_RESID_REL x implied)
SPEED_RESID_REL = 0.5
IMPLAUSIBLE_MIN_S = 3

# heading_incoherent: heading against the >= 5 s displacement, folded so that a reversing
# vehicle (180 deg) is not flagged. ADR bulk while moving: folded diff median 7 deg,
# p99 47.8 deg, p99.9 79 deg (those are 1 s steps on curves and noise).
HEADING_MIN_DISP_M = 15.0
HEADING_MAX_DEG = 60.0
HEADING_MIN_S = 3

# altitude_spike: |alt - the track's own median| (ADR bulk p99.9 2.0 m; 162 samples > 5 m).
ALT_SPIKE_M = 10.0

# --- behaviour ---------------------------------------------------------------------

# overspeed: centered >= 5 s implied speed above limit x (1 + tol) for >= min samples.
OVERSPEED_TOL = 0.2
OVERSPEED_MIN_S = 3
# Where more than 1 - OVERSPEED_BULK_Q of a zone class's traffic is above the posted
# limit, the limit does not describe normal operations there: the threshold rises to that
# class's OVERSPEED_BULK_Q speed. On ADR this hits the 10 km/h stands (per-track max
# ratio median 1.62) and holding positions (sample ratio median 1.01); service roads
# (p99 ratio 0.96) and taxi corridors (0.72) keep the posted limit.
OVERSPEED_BULK_Q = 0.99
# unauthorized_zone / runway_incursion: at least this many consecutive samples.
ZONE_MIN_S = 3
# Classes whose job puts them in zones their group may not enter on its own:
# a pushback tug tows aircraft along taxi corridors.
ROLE_ZONES = {"pushback_tug": ("taxi_corridor",)}
# unexpected_stop: stopped longer than the zone's dwell limit (zone_access.csv
# max_dwell_s: runway 120 s, taxiway 300 s, holding point 900 s). Stands and aprons
# are where assets park; aircraft hold at holding positions. Stops that touch the
# first or last sample of a mission are parking.
STOP_LIMIT_S = {
    "runway_critical": 120.0,
    "runway_strip": 120.0,
    "taxi_corridor": 300.0,
    "holding_position": 900.0,
    "service_road_corridor": 900.0,
}
STOP_FREE_ZONES = ("aircraft_stand", "apron")
STOP_AIRCRAFT_FREE_ZONES = ("holding_position", "taxi_corridor")
# aircraft_proximity: a vehicle within this distance of a moving aircraft_taxi asset in
# the same second. Pushback tugs and follow-me cars work next to moving aircraft.
PROXIMITY_M = 20.0
PROXIMITY_EXEMPT = ("pushback_tug", "follow_me")

# --- output ------------------------------------------------------------------------

SIGNAL_LABELS = (
    "frozen_position",
    "position_jump",
    "fix_loss",
    "multipath_noise",
    "gnss_drift",
    "implausible_speed",
    "heading_incoherent",
    "altitude_spike",
)  # precedence order when several fire on one sample
BEHAVIOUR_LABELS = (
    "runway_incursion",
    "unauthorized_zone",
    "aircraft_proximity",
    "overspeed",
    "unexpected_stop",
    "wrong_way",
)
# Signal labels that say the reported position is wrong: position-based behaviour
# labels are never raised on these samples.
POSITION_WRONG = (
    "frozen_position",
    "position_jump",
    "fix_loss",
    "multipath_noise",
    "gnss_drift",
)
# Labels that say the reported speed is wrong: overspeed is not raised either.
SPEED_WRONG = ("implausible_speed",)

CAUSE = {
    "frozen_position": "technical_error",
    "position_jump": "technical_error",
    "fix_loss": "technical_error",
    "multipath_noise": "degraded",
    "gnss_drift": "gnss_anomaly",
    "implausible_speed": "technical_error",
    "heading_incoherent": "technical_error",
    "altitude_spike": "gnss_anomaly",
}

# Fixed templates filled with raw values (CLAUDE.md rule 11). contracts/ is frozen,
# so these live here rather than in contracts/features.csv.
TEMPLATES = {
    "frozen_position": "Position repeated unchanged for {frozen_s:.0f} s while the asset was moving ({moving_mps:.1f} m/s)",
    "position_jump": "Position stepped {step_m:.0f} m off the path predicted from the last 5 s",
    "fix_loss": "No position for {gap_s:.0f} s in the 1 Hz stream",
    "multipath_noise": "Position scatters {scatter_m:.1f} m around the path (median over 11 s) with no step or ramp",
    "implausible_speed": "Speed {speed_mps:.0f} m/s is beyond the {bound_mps:.0f} m/s physical bound for a {asset_class}",
    "heading_incoherent": "Heading is {heading_diff_deg:.0f} deg off the direction of travel over 5 s",
    "altitude_spike": "Altitude {alt_m:.0f} m is {alt_dev_m:.0f} m from the track's median",
    "runway_incursion": "A {group} asset is inside runway {runway} critical area",
    "unauthorized_zone": "A {group} asset is inside {zone_class} {zone_id}, open only to {allowed}",
    "aircraft_proximity": "Moving aircraft {other_id} is {prox_m:.0f} m away",
    "overspeed": "Speed {speed_kmh:.0f} km/h over 5 s in {zone_class} {zone_id} (limit {limit_kmh:.0f} km/h, flagged above {threshold_kmh:.0f} km/h)",
    "unexpected_stop": "Stopped for {stop_s:.0f} s in {zone_class} {zone_id} (limit {stop_limit_s:.0f} s)",
    "engine": "Engine integrity {trust:.0f}: {engine_text}",
    "clean": "No signal or behaviour check fired; engine integrity {trust:.0f} of 100",
}
