"""GNSS risk halos (specs/05_fleet.md requirements 12-14).

- static: signal shadows around buildings, from the elevation angle
  atan(height / distance) and the generator's error model (`geo.gnss`);
- live: the cells of an area alert, buffered by HALO_SIGMA_M;
- forecast: a track extrapolated at constant velocity that enters a halo.

Every feature is a `contract.RiskZoneFeature`, returned as a plain dict.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import shapely
from pyproj import Geod

from divas_air import config, contract, params
from divas_air.fleet import cell_polygon
from divas_air.geo import to_metric, to_wgs84
from divas_air.geo.gnss import error_ratio, sigma_m
from divas_air.verdict import action_text

STATIC_HALOS_PATH = config.LAYERS / "halos_static.geojson"
_GEOD = Geod(ellps="WGS84")
# median horizontal error of the generator's model per unit of per-axis sigma
MEDIAN_ERROR_PER_SIGMA = 1.177 * math.sqrt(1.0 + params.GNSS_WHITE_FRAC**2)
COORD_GRID_DEG = 1e-6  # ~0.1 m


def _feature(geometry: shapely.Geometry, **props) -> dict:
    f = contract.RiskZoneFeature(
        geometry=shapely.geometry.mapping(geometry),
        properties=contract.RiskZoneProps(**props),
    )
    return f.model_dump(mode="json")


def _metric_to_wgs84(g: shapely.Geometry) -> shapely.Geometry:
    def fn(xy):
        lon, lat = to_wgs84(xy[:, 0], xy[:, 1])
        return np.column_stack([lon, lat])

    return shapely.set_precision(shapely.transform(g, fn), COORD_GRID_DEG)


def _wgs84_to_metric(g: shapely.Geometry) -> shapely.Geometry:
    def fn(xy):
        x, y = to_metric(xy[:, 0], xy[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(g, fn)


# --- static ------------------------------------------------------------------------


def ring_error(elev_deg: float) -> tuple[float, float]:
    """(expected median horizontal error in m, level) at a building elevation angle.

    level = 1 - open-sky error / expected error: 0 in open sky, toward 1 as the
    error grows.
    """
    ratio = float(error_ratio(elev_deg))
    return float(sigma_m(elev_deg)) * MEDIAN_ERROR_PER_SIGMA, 1.0 - 1.0 / ratio


def static_halos(layers) -> dict:
    """GeoJSON FeatureCollection: one dissolved (Multi)Polygon per elevation band.

    Band k covers points that see some building above HALO_ELEVATION_DEG[k] but
    none above the next steeper angle: distance <= height / tan(angle).
    """
    b = layers.buildings
    geoms = b.geometry.to_numpy()
    h = b["height_m"].to_numpy(dtype="float64")
    feats, inner = [], None
    for ang in sorted(params.HALO_ELEVATION_DEG, reverse=True):
        reach = shapely.union_all(
            shapely.buffer(geoms, h / math.tan(math.radians(ang)), quad_segs=4)
        )
        band = reach if inner is None else shapely.difference(reach, inner)
        inner = reach
        band = shapely.simplify(band, params.HALO_SIMPLIFY_M)
        err, level = ring_error(ang)
        feats.append(
            _feature(
                _metric_to_wgs84(band),
                risk_zone_id=f"static_elev{ang:.0f}",
                kind="static",
                level=round(level, 3),
                label=f"Signal shadow: buildings above {ang:.0f} deg elevation",
                expected_error_m=round(err, 2),
            )
        )
    return {
        "type": "FeatureCollection",
        "schema_version": contract.SCHEMA_VERSION,
        "features": feats,
    }


# --- live --------------------------------------------------------------------------


def live_halos(
    alerts: pd.DataFrame, t: float, members: dict[str, list[str]]
) -> list[dict]:
    """Live halos of the area alerts at time t (rows of `fleet.area_alerts` with t_end == t)."""
    if alerts is None or len(alerts) == 0:
        return []
    now = alerts[np.abs(alerts["t_end"].to_numpy(dtype="float64") - t) < 1e-6]
    first = alerts[alerts["t_end"] <= t + 1e-9].groupby("area_alert_id")["t_end"].min()
    act = contract.Action(
        code="area_gnss_unreliable", text=action_text("area_gnss_unreliable", {})
    )
    out = []
    for r in now.sort_values("area_alert_id").itertuples(index=False):
        area = _wgs84_to_metric(cell_polygon(r.cells)).buffer(
            params.HALO_SIGMA_M, quad_segs=8
        )
        out.append(
            _feature(
                _metric_to_wgs84(area),
                risk_zone_id=f"live_{r.area_alert_id}",
                kind="live",
                level=float(np.clip(r.share, 0.0, 1.0)),
                label=f"Area GNSS alert: {int(r.n_degraded)} of {int(r.n_tracks)} assets degraded",
                area_alert_id=r.area_alert_id,
                track_ids=sorted(members.get(r.area_alert_id, [])),
                action=act,
                t_start=float(first.get(r.area_alert_id, t)),
                t_end=float(t),
            )
        )
    return out


# --- forecast ----------------------------------------------------------------------


def forecast_paths(
    verdict_rows: pd.DataFrame,
    halos: list[dict],
    t: float,
    shapes: list[shapely.Geometry] | None = None,
) -> list[dict]:
    """Forecast features for tracks whose constant-velocity path enters a halo they are not in.

    `verdict_rows`: one row per track with track_id, aux_lat, aux_lon, aux_gs_mps,
    aux_track_deg. Paths are sampled every STRIDE_S up to max(FORECAST_HORIZONS_S).
    `shapes`: the halos' geometries, already parsed and prepared (the online engine
    parses the static halos once); None parses them here.
    """
    if len(verdict_rows) == 0 or not halos:
        return []
    v = verdict_rows.reset_index(drop=True)
    gs = v["aux_gs_mps"].to_numpy(dtype="float64", na_value=np.nan)
    crs = v["aux_track_deg"].to_numpy(dtype="float64", na_value=np.nan)
    lat = v["aux_lat"].to_numpy(dtype="float64", na_value=np.nan)
    lon = v["aux_lon"].to_numpy(dtype="float64", na_value=np.nan)
    ok = (
        np.isfinite(gs)
        & np.isfinite(crs)
        & np.isfinite(lat)
        & np.isfinite(lon)
        & (gs >= params.MOVING_MPS)
    )
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        return []
    horizon = max(params.FORECAST_HORIZONS_S)
    steps = np.arange(0.0, horizon + 1e-9, config.STRIDE_S)  # 0 = now
    n, s = len(idx), len(steps)
    lon2, lat2, _ = _GEOD.fwd(
        np.repeat(lon[idx], s),
        np.repeat(lat[idx], s),
        np.repeat(crs[idx], s),
        np.tile(steps, n) * np.repeat(gs[idx], s),
    )
    plon, plat = np.asarray(lon2).reshape(n, s), np.asarray(lat2).reshape(n, s)
    best: dict[int, tuple[float, dict]] = {}
    if shapes is None:
        shapes = [shapely.geometry.shape(h["geometry"]) for h in halos]
        shapely.prepare(shapes)
    for halo, g in zip(halos, shapes, strict=True):
        inside = shapely.contains_xy(g, plon, plat)  # n x s
        enters = ~inside[:, 0] & inside[:, 1:].any(axis=1)
        for i in np.flatnonzero(enters):
            eta = float(steps[1 + np.argmax(inside[i, 1:])])
            if i not in best or eta < best[i][0]:
                best[i] = (eta, halo)
    out = []
    for i, (eta, halo) in sorted(best.items()):
        row = v.iloc[idx[i]]
        p = halo["properties"]
        out.append(
            _feature(
                shapely.LineString(np.column_stack([plon[i], plat[i]])),
                risk_zone_id=f"forecast_{row['track_id']}_{p['risk_zone_id']}",
                kind="forecast",
                level=float(p["level"]),
                label=f"Path enters {p['label']} in {eta:.0f} s",
                track_ids=[str(row["track_id"])],
                enters_risk_zone_id=p["risk_zone_id"],
                eta_s=eta,
                t_start=float(t),
                t_end=float(t) + eta,
            )
        )
    return out
