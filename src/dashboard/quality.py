"""quality — preparación de datos para el panel de calidad (Fase 4).
Python/pandas puro, sin Streamlit — testeable sin lanzar la app. Solo
resume/reformatea tablas ya calculadas en Fases 1-3; no recalcula nada.
"""

from __future__ import annotations

import pandas as pd


def summarize_facility_quality(data_quality_report: pd.DataFrame) -> pd.DataFrame:
    """Filtra el reporte de calidad de Fase 1 a las reglas de `facilities`,
    en un formato compacto para el panel (regla, N afectados, acción)."""
    fac = data_quality_report[data_quality_report["dataset"] == "facilities"].copy()
    return fac[["regla", "n_afectados", "accion", "justificacion"]].reset_index(drop=True)


def summarize_routing_quality(routing_quality: dict) -> dict:
    """Extrae del `routing_quality_report.csv` (dict metric->value) los
    campos relevantes para el panel — snap failures, no-route,
    cross-department, supuesto de `track`."""

    def _num(key, cast=float):
        v = routing_quality.get(key)
        return cast(v) if v is not None else None

    total = _num("demand_total", int) or 1
    return {
        "car_snap_failed": _num("car_snap_failed", int),
        "car_snap_failed_pct": 100.0 * (_num("car_snap_failed", int) or 0) / total,
        "car_no_route_same_department": _num("car_no_route_same_department", int),
        "car_no_route_same_department_pct": 100.0 * (_num("car_no_route_same_department", int) or 0) / total,
        "car_matrix_cross_department_not_evaluated_pct": _num("car_matrix_cross_department_pct"),
        "car_track_fallback_speed_kmh": _num("car_track_fallback_speed_kmh"),
        "car_track_recovers_route_to_resolutive": _num("car_track_recovers_route_to_resolutive", int),
        "demand_total": total,
    }


def summarize_population_quality(phase3_summary: dict, weight_calibration_by_district: pd.DataFrame | None) -> dict:
    """U2/U4/frame coverage + distritos no calibrables — para el panel de
    calidad poblacional (nunca oculto en código, siempre visible)."""
    n_impossible = 0
    pop_impossible = 0.0
    if weight_calibration_by_district is not None and len(weight_calibration_by_district):
        impossible = weight_calibration_by_district[weight_calibration_by_district["calibration_status"] == "impossible_no_sample"]
        n_impossible = len(impossible)
        pop_impossible = float(impossible["known_population"].sum())
    return {
        "u2_total_population": phase3_summary.get("u2_total_population"),
        "u4_total_population": phase3_summary.get("u4_total_population"),
        "frame_coverage_u4_over_u2_pct": phase3_summary.get("frame_coverage_u4_over_u2_pct"),
        "outside_sigmed_frame_population": (phase3_summary.get("u2_total_population") or 0) - (phase3_summary.get("u4_total_population") or 0),
        "pct_population_matched_in_sample": phase3_summary.get("pct_population_matched"),
        "n_districts_calibration_impossible": n_impossible,
        "population_calibration_impossible": pop_impossible,
    }


def summarize_statistical_quality(phase3_summary: dict, weight_diagnostics: pd.DataFrame | None, weight_calibration_by_district: pd.DataFrame | None) -> dict:
    """Comparación HT vs calibrado + n_eff + factores de calibración
    extremos (diagnóstico, nunca criterio de exclusión)."""
    n_eff_total_ht = n_eff_total_cal = None
    if weight_diagnostics is not None and len(weight_diagnostics):
        row = weight_diagnostics[weight_diagnostics["scope"] == "TOTAL"]
        if len(row):
            n_eff_total_ht = float(row["n_eff_ht"].iloc[0])
            n_eff_total_cal = float(row["n_eff_calibrated"].iloc[0])

    extreme_low = extreme_high = 0
    if weight_calibration_by_district is not None and len(weight_calibration_by_district):
        f = weight_calibration_by_district["calibration_factor"].dropna()
        extreme_low = int((f < 0.5).sum())
        extreme_high = int((f > 2.0).sum())

    return {
        "weighted_mean_access_min_ht": phase3_summary.get("weighted_mean_access_min_total_ht"),
        "weighted_mean_access_min_calibrated": phase3_summary.get("weighted_mean_access_min_total_calibrated"),
        "weighted_gini_access": phase3_summary.get("weighted_gini_access"),
        "gini_pct_population_excluded": phase3_summary.get("gini_pct_population_excluded"),
        "n_eff_total_ht": n_eff_total_ht,
        "n_eff_total_calibrated": n_eff_total_cal,
        "n_districts_extreme_calibration_factor_low": extreme_low,
        "n_districts_extreme_calibration_factor_high": extreme_high,
    }
