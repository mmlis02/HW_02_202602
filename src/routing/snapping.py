"""Snapping: asignar a cada punto (demanda o establecimiento) el nodo de red
más cercano, por perfil (cada perfil puede tener un grafo con nodos distintos,
ya que las vías excluidas difieren).

Umbral de snap no aceptable: `routing.snap_max_distance_m` en `config.md` —
**decisión metodológica del proyecto**, no un dato observado: un punto a más de
esa distancia del nodo vial más cercano probablemente esté mal geocodificado o
en una zona sin cobertura vial mapeada en OSM, y forzar un snap ahí produciría
un tiempo de viaje ficticio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)

_EARTH_RADIUS_M = 6371000.0


def _haversine_m(lon1, lat1, lon2, lat2) -> np.ndarray:
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


@dataclass
class SnapResult:
    point_id: str
    node_id: int | None
    snap_distance_m: float | None
    status: str        # "success" | "failure"
    fail_reason: str | None


def snap_points(
    point_ids: list[str],
    lons: np.ndarray,
    lats: np.ndarray,
    node_ids: np.ndarray,
    node_lons: np.ndarray,
    node_lats: np.ndarray,
    max_distance_m: float,
) -> pd.DataFrame:
    """Snapea cada punto (lon,lat) al nodo más cercano de `node_ids`.

    Búsqueda por KD-tree en un plano equirrectangular local (aproximación
    razonable a esta escala — unas decenas de km — y muchísimo más rápida que
    proyectar cada consulta); la distancia final reportada se recalcula con
    Haversine real para no subestimarla por la aproximación de búsqueda.
    """
    if len(node_ids) == 0:
        return pd.DataFrame([
            {"point_id": pid, "node_id": None, "snap_distance_m": None, "status": "failure", "fail_reason": "grafo_vacio"}
            for pid in point_ids
        ])

    lat0 = np.radians(np.mean(node_lats))
    tree = cKDTree(np.column_stack([node_lons * np.cos(lat0), node_lats]))
    query = np.column_stack([lons * np.cos(lat0), lats])
    dist_deg, idx = tree.query(query, k=1)

    matched_node = node_ids[idx]
    matched_lon = node_lons[idx]
    matched_lat = node_lats[idx]
    dist_m = _haversine_m(lons, lats, matched_lon, matched_lat)

    rows = []
    for pid, nid, d in zip(point_ids, matched_node, dist_m):
        if d > max_distance_m:
            rows.append({"point_id": pid, "node_id": int(nid), "snap_distance_m": float(d), "status": "failure", "fail_reason": f"distancia {d:.0f} m > umbral {max_distance_m:.0f} m"})
        else:
            rows.append({"point_id": pid, "node_id": int(nid), "snap_distance_m": float(d), "status": "success", "fail_reason": None})
    return pd.DataFrame(rows)


def snap_report(snap_df: pd.DataFrame) -> dict:
    n_total = len(snap_df)
    n_failed = int((snap_df["status"] == "failure").sum())
    d = snap_df["snap_distance_m"].dropna()
    return {
        "n_total": n_total,
        "n_failed": n_failed,
        "pct_failed": 100.0 * n_failed / n_total if n_total else 0.0,
        "mean_snap_m": float(d.mean()) if len(d) else None,
        "median_snap_m": float(d.median()) if len(d) else None,
        "p95_snap_m": float(d.quantile(0.95)) if len(d) else None,
        "max_snap_m": float(d.max()) if len(d) else None,
    }
