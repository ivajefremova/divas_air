"""Output contract of the Trust API (pydantic v2).

FROZEN. The Risk Map team builds against these models and the JSON Schemas in
contracts/. Additive, optional fields only; anything else needs human approval
and a SCHEMA_VERSION bump. Regenerate contracts/ with
`python scripts/make_contract_examples.py` after any change.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from divas_air.schema import CAUSES, SOUND_CAUSES

SCHEMA_VERSION = "1.0"

Cause = Literal[
    "plausible",
    "degraded",
    "technical_error",
    "gnss_anomaly",
    "possible_interference",
    "possible_spoofing",
    "behavioral_anomaly",
]
TrustState = Literal["trusted", "caution", "untrusted"]
NormalityState = Literal["expected", "abnormal"]
Quadrant = Literal["trusted", "real_event", "data_fault", "silent_risk"]
ConfidenceLevel = Literal["high", "medium", "low"]
SeverityLevel = Literal["none", "low", "medium", "high", "critical"]
Dimension = Literal["kinetic", "temporal", "spatial", "contextual", "signal", "fleet"]
ActionCode = Literal[
    "none",  # no action
    "monitor",  # keep watching, nothing to do yet
    "verify_radio",  # data fault near a critical zone: confirm position by radio
    "verify_visual",  # data fault elsewhere: confirm visually or by a second source
    "cross_check",  # silent risk: behavior looks normal but the data is inconsistent
    "act_now",  # real event: data is sound, behavior is abnormal
    "area_gnss_unreliable",  # area alert: GNSS unreliable in this sector
]
RiskZoneKind = Literal["static", "live", "forecast"]

assert set(Cause.__args__) == set(CAUSES)  # keep in step with schema.py


def quadrant_of(trust_state: str, normality_state: str) -> str:
    """Two axes, four quadrants. `caution` counts as data still usable."""
    data_ok = trust_state != "untrusted"
    behavior_ok = normality_state == "expected"
    if data_ok:
        return "trusted" if behavior_ok else "real_event"
    return "silent_risk" if behavior_ok else "data_fault"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- input ------------------------------------------------------------------


class TrackPointIn(_Model):
    """One position report sent to POST /tracks. SI units, WGS84."""

    asset_id: str = Field(description="icao24 hex or vehicle id")
    t: float = Field(description="position time, UNIX seconds UTC")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    domain: Literal["aircraft", "vehicle"]
    asset_class: str | None = Field(None, description="envelope category; inferred from typecode if absent")
    typecode: str | None = None
    callsign: str | None = None
    alt_baro_m: float | None = None
    alt_geom_m: float | None = None
    gs_mps: float | None = None
    track_deg: float | None = None
    heading_deg: float | None = None
    vrate_mps: float | None = None
    on_ground: bool | None = None
    nacp: float | None = None
    nic: float | None = None
    sil: float | None = None


class TracksIn(_Model):
    points: list[TrackPointIn]


class IngestAck(_Model):
    accepted: int
    rejected: int
    errors: list[str] = []


# --- verdict ----------------------------------------------------------------


class Position(_Model):
    lat: float
    lon: float
    alt_m: float | None = None
    track_deg: float | None = None
    speed_mps: float | None = None


class Dimensions(_Model):
    """The four bars of the verdict card, 0 (violated) to 100 (coherent)."""

    kinetic: float = Field(ge=0, le=100)
    temporal: float = Field(ge=0, le=100)
    spatial: float = Field(ge=0, le=100)
    contextual: float = Field(ge=0, le=100)


class Severity(_Model):
    level: SeverityLevel
    score: float = Field(ge=0, le=1, description="max(untrust, abnormality) x zone criticality")
    zone_id: str | None = None
    zone_name: str | None = None
    zone_criticality: float = Field(ge=0, le=1)


class Evidence(_Model):
    """One plain-language sentence, filled from a fixed template with raw values."""

    feature: str = Field(description="feature name in contracts/features.csv")
    dimension: Dimension
    text: str
    value: float | None = None
    limit: float | None = None
    unit: str | None = None


class Action(_Model):
    code: ActionCode
    text: str = Field(description="action first, plain verbs, every number with a unit")


class EarlyWarning(_Model):
    """The track, extrapolated at constant velocity, enters a GNSS risk halo."""

    risk_zone_id: str
    eta_s: float = Field(ge=0)


class Verdict(_Model):
    """One verdict per track per window (30 s window, re-evaluated every 5 s)."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    track_id: str
    asset_id: str
    domain: Literal["aircraft", "vehicle"]
    asset_class: str
    callsign: str | None = None
    t: float = Field(description="window end, UNIX seconds UTC")
    window_s: int = 30
    position: Position = Field(description="last reported fix at or before t")

    integrity: float = Field(ge=0, le=100, description="is the data sound? smoothed, drives trust_state")
    integrity_raw: float = Field(ge=0, le=100, description="calibrated, before smoothing")
    normality: float = Field(ge=0, le=100, description="is the behavior expected?")
    dimensions: Dimensions

    trust_state: TrustState
    normality_state: NormalityState
    quadrant: Quadrant

    confidence: float = Field(ge=0, le=1)
    confidence_level: ConfidenceLevel

    cause: Cause = Field(description="reported cause, consistent with trust_state")
    cause_probs: dict[Cause, float] = Field(description="calibrated, all seven causes, sums to 1")

    severity: Severity
    evidence: list[Evidence] = Field(max_length=3)
    action: Action

    area_alert_id: str | None = Field(None, description="set when the track belongs to an area alert")
    early_warning: EarlyWarning | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Verdict:
        if set(self.cause_probs) != set(CAUSES):
            raise ValueError("cause_probs must have exactly the seven causes")
        if abs(sum(self.cause_probs.values()) - 1.0) > 1e-3:
            raise ValueError("cause_probs must sum to 1")
        if any(p < 0 for p in self.cause_probs.values()):
            raise ValueError("cause_probs must be non-negative")
        if self.quadrant != quadrant_of(self.trust_state, self.normality_state):
            raise ValueError("quadrant inconsistent with trust_state and normality_state")
        if self.trust_state == "untrusted" and self.cause == "plausible":
            raise ValueError("an untrusted verdict cannot report cause 'plausible'")
        if self.trust_state == "trusted" and self.cause not in SOUND_CAUSES:
            raise ValueError("a trusted verdict can only report a sound cause")
        return self


class VerdictsOut(_Model):
    """Body of GET /verdicts."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    t: float = Field(description="engine clock, UNIX seconds UTC")
    verdicts: list[Verdict]


# --- risk zones (GeoJSON) ---------------------------------------------------


class RiskZoneProps(_Model):
    risk_zone_id: str
    kind: RiskZoneKind
    level: float = Field(ge=0, le=1, description="0 = no risk, 1 = GNSS unusable")
    label: str = Field(description="short operator-facing title")
    expected_error_m: float | None = Field(None, description="static halos")
    area_alert_id: str | None = Field(None, description="live halos")
    track_ids: list[str] = Field(
        default_factory=list,
        description="live: tracks grouped under this area alert; forecast: the track being extrapolated",
    )
    enters_risk_zone_id: str | None = Field(None, description="forecast: the halo the path enters")
    eta_s: float | None = Field(None, description="forecast: seconds until the path enters it")
    action: Action | None = None
    t_start: float | None = None
    t_end: float | None = None


class RiskZoneFeature(_Model):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any] = Field(
        description="GeoJSON geometry, WGS84 lon/lat. Polygon or MultiPolygon for static and live "
        "halos; LineString for a forecast (the extrapolated path of a track about to enter a halo)"
    )
    properties: RiskZoneProps


class RiskZones(_Model):
    """Body of GET /risk-zones: a GeoJSON FeatureCollection."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    t: float
    features: list[RiskZoneFeature]


# --- offline replay bundle --------------------------------------------------


class ReplayEvent(_Model):
    event_id: str
    kind: Literal["phantom_incursion", "real_incursion", "sector_interference", "red_team"]
    title: str
    t_start: float
    t_end: float
    track_ids: list[str]


class ReplayManifest(_Model):
    """data/processed/demo/replay/manifest.json"""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    airport: str
    t_start: float
    t_end: float
    step_s: int
    n_frames: int
    frames_file: str = "frames.jsonl"
    events: list[ReplayEvent]


class ReplayFrame(_Model):
    """One line of frames.jsonl: the full API state at engine time t."""

    t: float
    verdicts: list[Verdict]
    risk_zones: RiskZones
