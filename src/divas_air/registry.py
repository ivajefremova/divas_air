"""Feature registry: the single source of truth for feature names.

Loaded from contracts/features.csv (FROZEN). The registry fixes, for every
feature: its group, the dimension bar it feeds, its unit, its monotone
constraint in the integrity model, its default violation threshold and the
sentence template used as verdict evidence.

The feature layer must emit exactly FEATURE_COLUMNS + AUX_COLUMNS; the fleet
layer adds FLEET_COLUMNS; the models read the MODEL_INPUTS_* lists. Nothing
else names a feature.
"""

from __future__ import annotations

import csv
import string
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from divas_air.config import ROOT
from divas_air.schema import assert_no_leakage

REGISTRY_PATH: Path = ROOT / "contracts" / "features.csv"

GROUPS = ("kinetic", "temporal", "signal", "spatial", "contextual", "fleet")
SCORED_DIMENSIONS = ("kinetic", "temporal", "spatial", "contextual")  # the four bars
TAU_SOURCES = ("envelope", "calibrated", "fixed", "none")
APPLIES_TO = ("all", "aircraft", "vehicle", "ground", "airborne", "approach")

# Per-window context columns emitted by the feature layer. Never model inputs
# (prefix aux_ is forbidden by schema.assert_no_leakage). Used to build the
# verdict (position, identity, zone) and to fill evidence templates.
AUX_COLUMNS: tuple[str, ...] = (
    "aux_asset_id",
    "aux_domain",
    "aux_asset_class",
    "aux_callsign",
    "aux_lat",  # last fix at or before t_end (works for empty windows)
    "aux_lon",
    "aux_alt_m",
    "aux_gs_mps",
    "aux_track_deg",
    "aux_airborne",  # bool: last fix airborne
    "aux_speed_implied_mps",  # at the pair with the largest speed residual
    "aux_speed_reported_mps",
    "aux_class_max_speed_mps",  # class limit that applied (ground or air)
    "aux_zone_id",  # the zone behind spa_zone_crit_max
    "aux_zone_name",
    "aux_zone_type",
    "aux_zone_speed_limit_mps",
)


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    group: str
    dimension: str
    unit: str
    monotone: int  # +1: integrity may only fall as this rises; 0: unconstrained
    priority: str  # P0 must be computed; P1/P2 may be emitted as NaN at first
    tau_source: str  # envelope | calibrated | fixed | none (not in a dimension bar)
    tau: float | None
    scale: float | None
    applies_to: str
    description: str
    template: str

    @property
    def scored(self) -> bool:
        return self.tau_source != "none"

    def template_fields(self) -> list[str]:
        return [f for _, f, _, _ in string.Formatter().parse(self.template) if f]


def _num(x: str) -> float | None:
    return float(x) if x != "" else None


@lru_cache(maxsize=1)
def load_registry(path: Path | None = None) -> dict[str, FeatureSpec]:
    with open(path or REGISTRY_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    reg: dict[str, FeatureSpec] = {}
    for r in rows:
        spec = FeatureSpec(
            name=r["name"],
            group=r["group"],
            dimension=r["dimension"],
            unit=r["unit"],
            monotone=int(r["monotone"]),
            priority=r["priority"],
            tau_source=r["tau_source"],
            tau=_num(r["tau"]),
            scale=_num(r["scale"]),
            applies_to=r["applies_to"],
            description=r["description"],
            template=r["template"],
        )
        if spec.name in reg:
            raise ValueError(f"duplicate feature {spec.name}")
        reg[spec.name] = spec
    validate_registry(reg)
    return reg


def validate_registry(reg: dict[str, FeatureSpec]) -> None:
    errs = []
    for s in reg.values():
        if s.group not in GROUPS:
            errs.append(f"{s.name}: group {s.group}")
        if s.dimension != s.group:
            errs.append(f"{s.name}: dimension must equal group")
        if s.tau_source not in TAU_SOURCES:
            errs.append(f"{s.name}: tau_source {s.tau_source}")
        if s.applies_to not in APPLIES_TO:
            errs.append(f"{s.name}: applies_to {s.applies_to}")
        if s.priority not in ("P0", "P1", "P2"):
            errs.append(f"{s.name}: priority {s.priority}")
        if s.monotone not in (-1, 0, 1):
            errs.append(f"{s.name}: monotone {s.monotone}")
        if s.scored and (s.tau is None or not s.scale or s.scale <= 0):
            errs.append(f"{s.name}: scored feature needs tau and scale > 0")
        if s.scored and s.dimension not in SCORED_DIMENSIONS:
            errs.append(f"{s.name}: only the four dimensions are scored")
        if s.tau_source == "envelope" and s.tau != 1.5:
            errs.append(f"{s.name}: envelope tau must be LIMIT_MARGIN")
        for fld in s.template_fields():
            if fld != "v" and fld not in AUX_COLUMNS:
                errs.append(f"{s.name}: template field {fld} is not 'v' or an aux column")
    if errs:
        raise ValueError("; ".join(errs))
    assert_no_leakage(reg)


REGISTRY: dict[str, FeatureSpec] = load_registry()


def columns(*groups: str) -> list[str]:
    """Feature names of the given groups, in registry order."""
    return [s.name for s in REGISTRY.values() if s.group in groups]


# Emitted by the feature layer (module 3): everything except the fleet group.
FEATURE_COLUMNS: list[str] = columns("kinetic", "temporal", "signal", "spatial", "contextual")
# Added by the fleet layer (module 5).
FLEET_COLUMNS: list[str] = columns("fleet")

# Model inputs (module 4). Integrity sees data-soundness evidence only: no
# spatial or contextual feature, so behavior cannot lower integrity.
MODEL_INPUTS_INTEGRITY_P1: list[str] = columns("kinetic", "temporal", "signal")
MODEL_INPUTS_INTEGRITY_P2: list[str] = MODEL_INPUTS_INTEGRITY_P1 + FLEET_COLUMNS
MODEL_INPUTS_CAUSE: list[str] = FEATURE_COLUMNS + FLEET_COLUMNS

ENVELOPE_RATIO_COLUMNS: list[str] = [s.name for s in REGISTRY.values() if s.tau_source == "envelope"]


def monotone_constraints(cols: list[str]) -> list[int]:
    """LightGBM monotone_constraints for target = 1 (unsound)."""
    return [REGISTRY[c].monotone for c in cols]


def scored_features(dimension: str) -> list[FeatureSpec]:
    return [s for s in REGISTRY.values() if s.dimension == dimension and s.scored]
