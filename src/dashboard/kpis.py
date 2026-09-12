"""kpis — cálculos del header de KPIs (Fase 4). Python/pandas puro, sin
Streamlit — testeable sin lanzar la app.

Todos los KPIs se calculan SUMANDO `calibrated_weight` ya existente sobre el
subconjunto filtrado — nunca se recalibra al filtrar (sección 23 del
enunciado). La mediana ponderada reutiliza `metrics.weighted_median`
(ya implementada y testeada en Fase 3, ver `src/metrics.py`) — no se
reimplementa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import metrics as m


def total_population_frame(df: pd.DataFrame, *, weight_col: str = "calibrated_weight") -> float:
    """Población total representada por el subconjunto filtrado (Reading B:
    todo el frame, tenga o no tiempo estimable)."""
    total = pd.to_numeric(df[weight_col], errors="coerce").sum(min_count=1)
    return 0.0 if pd.isna(total) else float(total)  # `nan or 0.0` NO funciona (nan es truthy) -- chequeo explícito


def population_le_threshold(df: pd.DataFrame, threshold_min: float, *, time_col: str = "t_min", weight_col: str = "calibrated_weight") -> float:
    t = pd.to_numeric(df[time_col], errors="coerce")
    w = pd.to_numeric(df[weight_col], errors="coerce")
    mask = w.notna() & t.notna() & (t <= threshold_min)
    return float(w[mask].sum())


def population_gt_threshold_routed(df: pd.DataFrame, threshold_min: float, *, time_col: str = "t_min", weight_col: str = "calibrated_weight") -> float:
    """Población CON ruta pero por encima del umbral — NUNCA incluye
    `no_time_estimate` (esa es una categoría aparte, ver
    `population_no_time_estimate`)."""
    t = pd.to_numeric(df[time_col], errors="coerce")
    w = pd.to_numeric(df[weight_col], errors="coerce")
    mask = w.notna() & t.notna() & (t > threshold_min)
    return float(w[mask].sum())


def population_no_time_estimate(df: pd.DataFrame, *, time_col: str = "t_min", weight_col: str = "calibrated_weight") -> float:
    t = pd.to_numeric(df[time_col], errors="coerce")
    w = pd.to_numeric(df[weight_col], errors="coerce")
    mask = w.notna() & t.isna()
    return float(w[mask].sum())


def weighted_mean_access_kpi(df: pd.DataFrame, *, time_col: str = "t_min", weight_col: str = "calibrated_weight") -> float:
    t = pd.to_numeric(df[time_col], errors="coerce")
    w = pd.to_numeric(df[weight_col], errors="coerce")
    mask = w.notna() & t.notna()
    if not mask.any() or w[mask].sum() == 0:
        return float("nan")
    return float((t[mask] * w[mask]).sum() / w[mask].sum())


def weighted_median_access_kpi(df: pd.DataFrame, *, time_col: str = "t_min", weight_col: str = "calibrated_weight") -> float:
    t = pd.to_numeric(df[time_col], errors="coerce")
    w = pd.to_numeric(df[weight_col], errors="coerce")
    mask = w.notna() & t.notna()
    if not mask.any():
        return float("nan")
    return m.weighted_median(t[mask], w[mask])


def worst_computable_district(worst_computable_districts: pd.DataFrame) -> dict | None:
    """Distrito #1 del ranking YA FILTRADO a `district_status == "computable"`
    (`worst_computable_districts.parquet`/`.csv` de Fase 3) — nunca un
    distrito `insufficient_data`/`calibration_impossible`. `None` si, tras
    los filtros del sidebar, no queda ningún distrito computable."""
    if worst_computable_districts is None or len(worst_computable_districts) == 0:
        return None
    row = worst_computable_districts.sort_values("weighted_mean_access_min", ascending=False).iloc[0]
    return row.to_dict()


def kpi_header(df: pd.DataFrame, worst_computable_districts: pd.DataFrame, *, threshold_min: float = 60.0, time_col: str = "t_min", weight_col: str = "calibrated_weight") -> dict:
    """Agrupa los 4 KPIs mínimos exigidos + el frame total, para pintar el
    header de un solo cálculo (evita recorrer `df` 5 veces por separado en
    la UI)."""
    total = total_population_frame(df, weight_col=weight_col)
    le = population_le_threshold(df, threshold_min, time_col=time_col, weight_col=weight_col)
    gt_routed = population_gt_threshold_routed(df, threshold_min, time_col=time_col, weight_col=weight_col)
    no_time = population_no_time_estimate(df, time_col=time_col, weight_col=weight_col)
    return {
        "total_population_frame": total,
        "population_le_threshold": le,
        "pct_le_threshold_of_frame": 100.0 * le / total if total else np.nan,
        "population_gt_threshold_routed": gt_routed,
        "pct_gt_threshold_routed_of_frame": 100.0 * gt_routed / total if total else np.nan,
        "population_no_time_estimate": no_time,
        "pct_no_time_estimate_of_frame": 100.0 * no_time / total if total else np.nan,
        "worst_district": worst_computable_district(worst_computable_districts),
        "weighted_mean_access_min": weighted_mean_access_kpi(df, time_col=time_col, weight_col=weight_col),
        "weighted_median_access_min": weighted_median_access_kpi(df, time_col=time_col, weight_col=weight_col),
    }
