"""scenario — lógica del simulador de upgrade (Fase 4). Python/pandas puro,
sin Streamlit — testeable sin lanzar la app.

Regla central (NO recalcula routing): para cada demand point i,

    scenario_time_i = min(baseline_time_i, tiempo a cada candidato SELECCIONADO)

usando ÚNICAMENTE `routing_matrix_upgrade_candidates_car.parquet` (ya
precomputado en Fase 2) y el `baseline_time` ya calculado en Fase 3
(`nearest_resolutive_by_mode.parquet`, modo car). Si un candidato no tiene
ruta válida hacia un punto, ese punto no mejora — nunca se imputa una
distancia. Con selección vacía, `scenario_time == baseline_time` (no hay
"mejora fantasma"). Con selección múltiple, se toma el mínimo conjunto
-- NUNCA se suman ganancias individuales (evita doble conteo).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src import metrics as m


def compute_scenario_time(
    baseline_time: pd.Series,
    upgrade_matrix: pd.DataFrame,
    selected_candidate_ids: list[str],
    *,
    demand_id_col: str = "demand_id",
    facility_id_col: str = "facility_id",
    time_col: str = "travel_time_min",
) -> pd.Series:
    """`baseline_time`: Series indexada por `demand_id_col` (tiempo actual al
    resolutivo más cercano, NaN si no ruteado). `upgrade_matrix`: filas
    demand×candidato con `travel_time_min`/`reachable`/`routing_status` ya
    calculadas — nunca se recalcula. Con `selected_candidate_ids=[]` (o
    None), devuelve `baseline_time` sin modificar (escenario == baseline)."""
    baseline = baseline_time.copy()
    baseline.index = baseline.index.astype(str)
    if not selected_candidate_ids:
        return baseline

    ids = {str(c) for c in selected_candidate_ids}
    sub = upgrade_matrix[upgrade_matrix[facility_id_col].astype(str).isin(ids)]
    sub_time = pd.to_numeric(sub[time_col], errors="coerce")
    # Solo rutas válidas (`reachable`/tiempo no nulo) pueden mejorar un punto;
    # una fila sin ruta simplemente no aporta ("no imputes distancia").
    best_candidate_time = sub.assign(_t=sub_time).groupby(sub[demand_id_col].astype(str))["_t"].min()

    combined = pd.concat([baseline.rename("baseline"), best_candidate_time.rename("candidate")], axis=1)
    return combined.min(axis=1, skipna=True)


def summarize_population_by_bands(t_min, weights) -> dict:
    """Resumen poblacional (Reading B — sobre TODA la población representada,
    nunca solo la ruteada) reutilizando `metrics.compute_coverage_bands` —
    misma lógica exacta que Fase 3, ninguna reimplementación paralela."""
    df = pd.DataFrame({
        "t_min": pd.Series(np.asarray(t_min, dtype=float)).reset_index(drop=True),
        "w": pd.Series(np.asarray(weights, dtype=float)).reset_index(drop=True),
    })
    bands = m.compute_coverage_bands(df, time_col="t_min", weight_col="w")
    b = bands["reading_b_cumulative"].set_index("band")["poblacion_ponderada"]
    reading_a = bands["reading_a_sobre_poblacion_con_tiempo_estimable"].set_index("band")["poblacion_ponderada"]

    valid_w = df["w"].notna()
    has_time = valid_w & df["t_min"].notna()
    total_population = df.loc[valid_w, "w"].sum(min_count=1)
    w_valid = df.loc[has_time, "w"]
    t_valid = df.loc[has_time, "t_min"]
    weighted_mean = float((t_valid * w_valid).sum() / w_valid.sum()) if w_valid.sum() else np.nan

    return {
        "total_population": total_population,
        "pop_le_30": b.get("<=30", 0.0),
        "pop_le_60_cum": b.get("<=60 (cum)", 0.0),
        "pop_le_120_cum": b.get("<=120 (cum)", 0.0),
        "pop_gt_120": b.get(">120", 0.0),
        "pop_no_time_estimate": b.get("sin_tiempo_estimable", 0.0),
        "pop_30_60_only": reading_a.get(m.BAND_30_60, 0.0),  # informativo (Reading A), no se usa como default
        "weighted_mean": weighted_mean,
    }


def baseline_vs_scenario_summary(
    demand_analysis: pd.DataFrame,
    upgrade_matrix: pd.DataFrame,
    selected_candidate_ids: list[str],
    *,
    demand_id_col: str = "demand_id",
    baseline_time_col: str = "t_min",
    weight_col: str = "calibrated_weight",
) -> dict:
    """Resultado completo del simulador: baseline, escenario, y ganancia
    marginal — todo con los mismos `calibrated_weight` de Fase 3 (nunca se
    recalibra por filtrar/seleccionar)."""
    da = demand_analysis.copy()
    da[demand_id_col] = da[demand_id_col].astype(str)
    baseline_time = da.set_index(demand_id_col)[baseline_time_col]

    scenario_time = compute_scenario_time(baseline_time, upgrade_matrix, selected_candidate_ids, demand_id_col=demand_id_col)
    scenario_time = scenario_time.reindex(da[demand_id_col]).values

    weights = da[weight_col].values
    baseline_summary = summarize_population_by_bands(baseline_time.reindex(da[demand_id_col]).values, weights)
    scenario_summary = summarize_population_by_bands(scenario_time, weights)

    # Población que pasa de "sin tiempo estimable" a tener un tiempo (nunca
    # al revés, dado que scenario_time = min(baseline, candidato) nunca
    # empeora un punto ya ruteado).
    was_no_time = pd.isna(baseline_time.reindex(da[demand_id_col]).values)
    now_has_time = ~pd.isna(scenario_time)
    newly_routed_weight = float(np.nansum(np.where(was_no_time & now_has_time, weights, 0.0)))

    marginal = {
        "pop_gain_le_30": scenario_summary["pop_le_30"] - baseline_summary["pop_le_30"],
        "pop_gain_le_60": scenario_summary["pop_le_60_cum"] - baseline_summary["pop_le_60_cum"],
        "pop_gain_le_120": scenario_summary["pop_le_120_cum"] - baseline_summary["pop_le_120_cum"],
        "weighted_mean_reduction_min": (
            baseline_summary["weighted_mean"] - scenario_summary["weighted_mean"]
            if not (np.isnan(baseline_summary["weighted_mean"]) or np.isnan(scenario_summary["weighted_mean"]))
            else np.nan
        ),
        "population_newly_routed": newly_routed_weight,
    }
    return {"baseline": baseline_summary, "scenario": scenario_summary, "marginal_gain": marginal, "n_selected": len(selected_candidate_ids or [])}


def rank_candidates(candidate_scores: pd.DataFrame, *, by: str = "pop_gain_le_60", ascending: bool = False, top_n: int | None = None) -> pd.DataFrame:
    """Ordena la tabla YA PRECOMPUTADA de puntajes por candidato
    (`dashboard_candidate_scores.parquet`) — no repite ninguna simulación."""
    out = candidate_scores.sort_values(by, ascending=ascending).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    return out.head(top_n) if top_n else out
