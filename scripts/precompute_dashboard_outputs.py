"""precompute_dashboard_outputs (Fase 4).

Genera outputs específicos del dashboard, derivados EXCLUSIVAMENTE de
outputs ya existentes de Fase 1-3 (`data/processed/`, `data/outputs/`).
NO recalcula routing, NO cambia pesos, NO toca la muestra — solo re-agrega
`demand_analysis.parquet` (que ya trae `calibrated_weight`/`t_min` por CP)
agrupando por `UBIGEO` en vez de por nombre (DEP,PROV,DIST), para poder unir
sin ambigüedad con las geometrías distritales oficiales
(`data/processed/districts.gpkg`); precomputa la ganancia poblacional de
CADA candidato de upgrade I-3/I-4 individualmente (372 candidatos) para que
el simulador no repita esa cuenta en cada carga de Streamlit; y prepara una
tabla ligera de facilities para las capas del mapa.

Outputs (`data/outputs/`):
- `dashboard_district_metrics.parquet` — una fila por distrito (UBIGEO),
  métricas calibradas + `district_status` (idéntico al de Fase 3, solo
  re-agrupado por UBIGEO en vez de por nombre).
- `dashboard_district_geometries_simplified.parquet` — geometría distrital
  simplificada (tolerance=0.001° ~ 100m, documentado) SOLO para
  visualización — los datos analíticos (`districts.gpkg`) quedan intactos.
- `dashboard_candidate_scores.parquet` — una fila por candidato de upgrade
  (I-3/I-4 activo), con la ganancia poblacional SI ese candidato, solo, se
  volviera resolutivo (mínimo entre tiempo actual y tiempo al candidato).
- `dashboard_facilities.parquet` — facilities.parquet con una columna
  `layer_category` de conveniencia para las capas del mapa.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import get_path, load_config
from src.dashboard.scenario import compute_scenario_time, summarize_population_by_bands

SIMPLIFY_TOLERANCE_DEG = 0.001  # ~100 m en latitudes de Perú -- documentado, solo para visualización


def build_district_metrics(demand_analysis: pd.DataFrame, weighted_access_district: pd.DataFrame) -> pd.DataFrame:
    """Re-agrega `demand_analysis` por UBIGEO (en vez de por nombre) para
    poder unir sin ambigüedad con la geometría oficial. Reutiliza
    `district_status`/`calibration_factor` ya calculados en Fase 3 (join por
    DEP/PROV/DIST) — no recalcula nada, solo cambia la clave de agrupación
    para el mapa."""
    from src import metrics as m

    keys = ["UBIGEO", "DEP", "PROV", "DIST"]
    wa = m.weighted_mean_access(demand_analysis, keys, weight_col="calibrated_weight")
    bands = []
    for ubigeo, g in demand_analysis.groupby("UBIGEO"):
        b = m.compute_coverage_bands(g, weight_col="calibrated_weight")["reading_b_cumulative"].set_index("band")["pct"]
        bands.append({
            "UBIGEO": ubigeo,
            "pct_le_30": b.get("<=30", np.nan),
            "pct_le_60_cum": b.get("<=60 (cum)", np.nan),
            "pct_le_120_cum": b.get("<=120 (cum)", np.nan),
            "pct_gt_120": b.get(">120", np.nan),
            "pct_no_time_estimate": b.get("sin_tiempo_estimable", np.nan),
        })
    bands_df = pd.DataFrame(bands)
    out = wa.merge(bands_df, on="UBIGEO", how="left")

    # district_status ya viene calculado en Fase 3 por nombre (DEP,PROV,DIST)
    # -- se une por esa misma clave (1:1 real, verificado: un UBIGEO = un
    # (DEP,PROV,DIST) en este universo de 3 departamentos).
    status_cols = ["DEP", "PROV", "DIST", "district_status", "calibration_status", "calibration_factor", "known_population"]
    out = out.merge(weighted_access_district[status_cols], on=["DEP", "PROV", "DIST"], how="left")
    return out


def build_simplified_geometries(districts_gpkg: gpd.GeoDataFrame, *, tolerance: float = SIMPLIFY_TOLERANCE_DEG) -> gpd.GeoDataFrame:
    out = districts_gpkg[["UBIGEO", "geometry"]].copy()
    out["geometry"] = out["geometry"].simplify(tolerance, preserve_topology=True)
    out["simplify_tolerance_deg"] = tolerance
    return out


def build_candidate_scores(
    nearest_resolutive_car: pd.DataFrame,
    upgrade_matrix_car: pd.DataFrame,
    demand_analysis: pd.DataFrame,
) -> pd.DataFrame:
    """Para CADA candidato de upgrade (372), calcula individualmente la
    ganancia poblacional si SOLO ese establecimiento pasara a resolutivo —
    reutiliza `compute_scenario_time` (mínimo entre tiempo actual y tiempo al
    candidato, matrices ya precomputadas, sin routing nuevo)."""
    baseline_time = nearest_resolutive_car.set_index("demand_id")["travel_time_min"]
    weight = demand_analysis.set_index("demand_id")["calibrated_weight"]
    baseline_summary = summarize_population_by_bands(demand_analysis["t_min"], demand_analysis["calibrated_weight"])

    candidates = upgrade_matrix_car[["facility_id"]].drop_duplicates()["facility_id"].tolist()
    rows = []
    t0 = time.time()
    for i, cand in enumerate(candidates):
        scenario_time = compute_scenario_time(baseline_time, upgrade_matrix_car, [cand])
        scenario_summary = summarize_population_by_bands(scenario_time.reindex(demand_analysis["demand_id"]).values, demand_analysis["calibrated_weight"].values)
        rows.append({
            "facility_id": cand,
            "pop_gain_le_30": scenario_summary["pop_le_30"] - baseline_summary["pop_le_30"],
            "pop_gain_le_60": scenario_summary["pop_le_60_cum"] - baseline_summary["pop_le_60_cum"],
            "pop_gain_le_120": scenario_summary["pop_le_120_cum"] - baseline_summary["pop_le_120_cum"],
            "weighted_mean_reduction_min": baseline_summary["weighted_mean"] - scenario_summary["weighted_mean"],
        })
        if (i + 1) % 100 == 0:
            print(f"  candidato {i+1}/{len(candidates)} ({time.time()-t0:.1f}s)")
    return pd.DataFrame(rows)


def main() -> None:
    cfg = load_config()
    processed_dir = get_path("data_processed", cfg)
    outputs_dir = get_path("data_outputs", cfg)

    print("Cargando demand_analysis.parquet (Fase 3, calibrated_weight ya calculado)...")
    da = pd.read_parquet(outputs_dir / "demand_analysis.parquet")
    weighted_access_district = pd.read_parquet(outputs_dir / "weighted_access_district.parquet")

    print("1/4 dashboard_district_metrics.parquet (re-agregado por UBIGEO)...")
    district_metrics = build_district_metrics(da, weighted_access_district)
    district_metrics.to_parquet(outputs_dir / "dashboard_district_metrics.parquet", index=False)
    print(f"  {len(district_metrics)} distritos")

    print("2/4 dashboard_district_geometries_simplified.parquet...")
    districts = gpd.read_file(processed_dir / "districts.gpkg")
    simplified = build_simplified_geometries(districts)
    simplified.to_parquet(outputs_dir / "dashboard_district_geometries_simplified.parquet", index=False)
    print(f"  {len(simplified)} geometrias, tolerance={SIMPLIFY_TOLERANCE_DEG} grados")

    print("3/4 dashboard_facilities.parquet...")
    fac = pd.read_parquet(processed_dir / "facilities.parquet")
    fac = fac.drop(columns=["geometry"], errors="ignore")
    # INSTITUCION (MINSA/GOBIERNO REGIONAL/ESSALUD/PRIVADO/...) existe en el
    # RAW de RENIPRESS (ya descargado en Fase 1) pero no se conservó en
    # facilities.parquet -- se trae aquí solo para el filtro/tooltip del
    # dashboard, no cambia ninguna regla de Fase 1.
    renipress_cfg = cfg["acquisition"]["renipress"]
    raw_renipress = pd.read_csv(REPO_ROOT / "data/raw/renipress" / renipress_cfg["resource"], sep=renipress_cfg["sep"], encoding=renipress_cfg["encoding"], dtype=str, usecols=["COD_IPRESS", "INSTITUCION"])
    fac = fac.merge(raw_renipress, on="COD_IPRESS", how="left")
    fac["layer_category"] = np.select(
        [fac["is_resolutive"], fac["CATEGORIA_NORM"].isin(["I-3", "I-4"]) & fac["is_active"]],
        ["Resolutivo", "Candidato upgrade (I-3/I-4)"],
        default="Otro",
    )
    fac.to_parquet(outputs_dir / "dashboard_facilities.parquet", index=False)
    print(f"  {len(fac)} establecimientos")

    print("4/4 dashboard_candidate_scores.parquet (372 simulaciones individuales, matrices ya precomputadas)...")
    nearest_car = pd.read_parquet(outputs_dir / "nearest_resolutive_by_mode.parquet")
    nearest_car = nearest_car[nearest_car["mode"] == "car"]
    upgrade_car = pd.read_parquet(outputs_dir / "routing_matrix_upgrade_candidates_car.parquet")
    t0 = time.time()
    scores = build_candidate_scores(nearest_car, upgrade_car, da)
    scores = scores.merge(fac[["COD_IPRESS", "NOMBRE", "CATEGORIA_NORM", "DEPARTAMENTO", "PROVINCIA", "DISTRITO"]], left_on="facility_id", right_on="COD_IPRESS", how="left")
    scores.to_parquet(outputs_dir / "dashboard_candidate_scores.parquet", index=False)
    print(f"  {len(scores)} candidatos, {time.time()-t0:.1f}s")

    print("\nOK — outputs de dashboard escritos en data/outputs/dashboard_*.parquet")


if __name__ == "__main__":
    main()
