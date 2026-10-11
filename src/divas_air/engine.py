"""Online Trust engine (specs/06_api.md requirements 1-5).

The engine runs the batch pipeline's functions on one grid time at a time:
module 3 features, pass 1, the apron fleet layer, pass 2 and cause, and verdict
assembly. It implements no score of its own. Per track it keeps the point
buffer, the smoothed integrity and the two state machines; per area it keeps
the trailing fleet windows and the flagged cells that area alert ids need.

The engine clock is data time: `step(now)` produces the windows ending at
`now` from the fixes with t <= now.
"""

from __future__ import annotations

import json
from collections import deque

import numpy as np
import pandas as pd
import shapely

from divas_air import config, contract, halos, params, registry, schema
from divas_air.features import compute_features
from divas_air.fleet import (
    alert_members,
    area_alerts,
    cells_from_windows,
    fleet_features,
)
from divas_air.models import ModelBundle, load_bundle
from divas_air.params import FleetProfile
from divas_air.pipeline import degraded_flags, load_baseline
from divas_air.verdict import assemble, to_contract

KEYS = list(schema.WINDOW_KEYS)
POINT_COLUMNS = list(schema._REQUIRED_COLUMNS + schema._OPTIONAL_COLUMNS)
FLEET_WINDOW_COLUMNS = KEYS + ["aux_lat", "aux_lon", "degraded"]
_EPS = 1e-6


def grid_floor(t: float) -> float:
    return float(np.floor(t / config.STRIDE_S + 1e-9) * config.STRIDE_S)


def grid_ceil(t: float) -> float:
    return float(np.ceil(t / config.STRIDE_S - 1e-9) * config.STRIDE_S)


def load_static_halos() -> list[dict]:
    path = halos.STATIC_HALOS_PATH
    return json.loads(path.read_text())["features"] if path.exists() else []


class TrustEngine:
    def __init__(
        self,
        layers,
        bundle: ModelBundle,
        profile: FleetProfile = params.APRON,
        *,
        baseline: pd.DataFrame | None = None,
        static_halos: list[dict] | None = None,
    ):
        self.layers = layers  # None: no map features
        self.bundle = bundle
        self.profile = profile
        self.baseline = baseline
        self.static_halos = static_halos or []
        self._static_shapes = [
            shapely.geometry.shape(h["geometry"]) for h in self.static_halos
        ]
        shapely.prepare(self._static_shapes)
        self.clock: float | None = None  # last stepped grid time
        self._pts = pd.DataFrame(columns=POINT_COLUMNS)
        self._state = pd.DataFrame(  # per track, after its latest window
            columns=["integrity", "trust_state", "normality_state"]
        )
        self._fleet = pd.DataFrame(columns=FLEET_WINDOW_COLUMNS)  # trailing bin_s
        self._flagged = (
            pd.DataFrame()
        )  # flagged apron cells that may keep an alert alive
        self._alerts = pd.DataFrame()  # area alerts at the clock
        self._members: dict[str, list[str]] = {}
        self._rows = pd.DataFrame()  # flat verdict rows at the clock
        self._latest: dict[str, contract.Verdict] = {}
        self._history: dict[str, deque] = {}
        self._forecast: list[dict] = []
        self._live: dict[str, tuple[int, float]] = {}  # asset_id -> (segment, last t)
        self._next_seq: dict[str, int] = {}

    @classmethod
    def from_disk(cls) -> TrustEngine:
        from divas_air.geo import MapLayers

        return cls(
            MapLayers.load(),
            load_bundle(),
            params.APRON,
            baseline=load_baseline(),
            static_halos=load_static_halos(),
        )

    # --- input ---------------------------------------------------------------------

    def ingest(self, points: pd.DataFrame) -> None:
        """Buffer points in the unified schema (extra columns, labels included, are dropped)."""
        if len(points) == 0:
            return
        p = points[[c for c in POINT_COLUMNS if c in points.columns]].copy()
        for c in POINT_COLUMNS:
            if c not in p:
                p[c] = pd.NA
        p = schema.coerce_points(p[POINT_COLUMNS])
        self._pts = (
            p if len(self._pts) == 0 else pd.concat([self._pts, p], ignore_index=True)
        )

    def live_ids(self, asset_id: str, t: float) -> tuple[str, int]:
        """(track_id, seq) for a live point: `live:<asset_id>:<segment>`, a new segment
        after a silence longer than TRACK_GAP_SPLIT_S; seq in arrival order."""
        seg, last = self._live.get(asset_id, (-1, -np.inf))
        if seg < 0 or t - last > params.TRACK_GAP_SPLIT_S:
            seg, last = seg + 1, t
        self._live[asset_id] = (seg, max(last, t))
        track_id = f"live:{asset_id}:{seg}"
        seq = self._next_seq.get(track_id, 0)
        self._next_seq[track_id] = seq + 1
        return track_id, seq

    @property
    def latest_fix_t(self) -> float | None:
        return float(self._pts["t"].max()) if len(self._pts) else None

    # --- step ----------------------------------------------------------------------

    def _active_points(self, now: float) -> pd.DataFrame:
        p = self._pts[self._pts["t"].to_numpy(dtype="float64") <= now + _EPS]
        if len(p) == 0:
            return p
        last = p.groupby("track_id", sort=False)["t"].transform("max")
        return p[(now - last).to_numpy(dtype="float64") <= params.TRACK_GAP_SPLIT_S]

    def _prune(self, now: float) -> None:
        t = self._pts["t"].to_numpy(dtype="float64")
        last = self._pts.groupby("track_id", sort=False)["t"].transform("max")
        alive = (now - last.to_numpy(dtype="float64")) <= params.TRACK_GAP_SPLIT_S
        keep = alive & (t > now - params.ENGINE_KEEP_S)
        keep |= t > now  # points ahead of the clock wait for their step
        self._pts = self._pts[keep].reset_index(drop=True)
        tracks = set(self._pts["track_id"].astype(str))
        self._state = self._state[self._state.index.isin(tracks)]
        for tid in [k for k in self._history if k not in tracks]:
            del self._history[tid]

    def _fleet_step(self, f: pd.DataFrame, now: float) -> pd.DataFrame:
        """Fleet columns and area_alert_id for the windows `f` at `now` (module 5 functions)."""
        w = f[KEYS + ["aux_lat", "aux_lon"]].copy()
        w["degraded"] = degraded_flags(f, self.bundle)
        fw = self._fleet
        fw = fw[fw["t_end"].to_numpy(dtype="float64") > now - self.profile.bin_s + _EPS]
        self._fleet = w if len(fw) == 0 else pd.concat([fw, w], ignore_index=True)

        cells = cells_from_windows(self._fleet, self.profile, self.baseline)
        cells_now = cells[np.abs(cells["t_end"].to_numpy(dtype="float64") - now) < _EPS]
        hist = pd.concat([self._flagged, cells_now], ignore_index=True)
        alerts = area_alerts(hist, self.profile)
        if len(alerts):
            alerts = alerts[
                np.abs(alerts["t_end"].to_numpy(dtype="float64") - now) < _EPS
            ]
        self._alerts = alerts.reset_index(drop=True)
        self._remember_flagged(cells_now, now)

        ff = fleet_features(self._fleet, self.profile, self.baseline)
        ff = ff[np.abs(ff["t_end"].to_numpy(dtype="float64") - now) < _EPS]
        members = alert_members(w, self._alerts, self.profile)
        out = f.drop(
            columns=[c for c in [*registry.FLEET_COLUMNS, "area_alert_id"] if c in f]
        ).merge(ff[KEYS + registry.FLEET_COLUMNS], on=KEYS, how="left")
        out = out.merge(members[KEYS + ["area_alert_id"]], on=KEYS, how="left")
        out["area_alert_id"] = (
            out["area_alert_id"]
            .astype(object)
            .where(out["area_alert_id"].notna(), None)
        )
        self._members = {
            a: sorted(g["track_id"].astype(str))
            for a, g in members.groupby("area_alert_id")
        }
        return out

    def _remember_flagged(self, cells_now: pd.DataFrame, now: float) -> None:
        """Keep flagged cells back to the last silence of at least bin_s: before it, no
        alert can still be alive, so area_alerts gives the same ids as on the full history."""
        flagged = cells_now[cells_now["flagged"].astype(bool)]
        hist = pd.concat([self._flagged, flagged], ignore_index=True)
        if len(hist) == 0:
            self._flagged = hist
            return
        times = np.unique(hist["t_end"].to_numpy(dtype="float64"))
        times = np.r_[times, now + config.STRIDE_S]  # the next step
        breaks = np.flatnonzero(np.diff(times) >= self.profile.bin_s - 1e-9)
        start = times[breaks[-1] + 1] if len(breaks) else times[0]
        self._flagged = hist[hist["t_end"].to_numpy(dtype="float64") >= start - _EPS]
        self._flagged = self._flagged.reset_index(drop=True)

    def step(self, now: float) -> list[contract.Verdict]:
        """One verdict per active track (a fix in the last TRACK_GAP_SPLIT_S) at grid time `now`."""
        now = float(now)
        self.clock = now
        self._prune(now)
        pts = self._active_points(now)
        if len(pts) == 0:
            self._rows, self._latest, self._alerts, self._members = (
                pd.DataFrame(),
                {},
                pd.DataFrame(),
                {},
            )
            self._forecast = []
            return []
        feats = compute_features(pts, self.layers, until=now)
        f = feats[np.abs(feats["t_end"].to_numpy(dtype="float64") - now) < _EPS]
        f = self._fleet_step(f.reset_index(drop=True), now)

        init = self._state.reindex(f["track_id"].astype(str).unique())
        rows = assemble(f, self.bundle, init=init)
        new = rows.set_index(rows["track_id"].astype(str))[
            ["integrity", "trust_state", "normality_state"]
        ]
        old = self._state.drop(index=new.index, errors="ignore")
        self._state = new if len(old) == 0 else pd.concat([old, new])
        self._rows = rows
        live = self._live_halos(now)
        live_shapes = [shapely.geometry.shape(h["geometry"]) for h in live]
        shapely.prepare(live_shapes)
        self._forecast = halos.forecast_paths(
            rows, self.static_halos + live, now, self._static_shapes + live_shapes
        )
        warn = self._early_warnings()

        out = []
        for r in rows.to_dict("records"):
            v = to_contract(r)
            if v.track_id in warn:
                v = v.model_copy(update={"early_warning": warn[v.track_id]})
            out.append(v)
        self._latest = {v.track_id: v for v in out}
        for v in out:
            h = self._history.setdefault(v.track_id, deque())
            h.append(v)
            while h and h[0].t < now - params.HISTORY_S - _EPS:
                h.popleft()
        return out

    # --- outputs -------------------------------------------------------------------

    def _live_halos(self, now: float) -> list[dict]:
        return halos.live_halos(self._alerts, now, self._members)

    def _early_warnings(self) -> dict[str, contract.EarlyWarning]:
        out = {}
        for f in self._forecast:
            p = f["properties"]
            out[p["track_ids"][0]] = contract.EarlyWarning(
                risk_zone_id=p["enters_risk_zone_id"], eta_s=p["eta_s"]
            )
        return out

    def risk_zones(
        self, now: float | None = None, *, static: bool = True
    ) -> contract.RiskZones:
        """Static halos, live halos of the area alerts and forecasts at the engine clock."""
        now = self.clock if now is None else float(now)
        if now is None:
            return contract.RiskZones(t=0.0, features=[])
        live = (
            self._live_halos(now)
            if self.clock is not None and abs(now - self.clock) < _EPS
            else []
        )
        feats = (self.static_halos if static else []) + live + self._forecast
        return contract.RiskZones(t=now, features=feats)

    def latest(self, track_id: str | None = None) -> list[contract.Verdict]:
        vs = sorted(self._latest.values(), key=lambda v: v.track_id)
        return [v for v in vs if track_id is None or v.track_id == track_id]

    def history(
        self, track_id: str, seconds: float = params.HISTORY_S
    ) -> list[contract.Verdict]:
        """Verdicts of a track over the last `seconds` of engine time, oldest first."""
        h = self._history.get(track_id, ())
        if self.clock is None:
            return []
        return [v for v in h if v.t >= self.clock - seconds - _EPS]

    @property
    def n_tracks(self) -> int:
        return len(self._latest)
