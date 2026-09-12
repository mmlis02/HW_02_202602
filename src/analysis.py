"""analysis — Fase 3: orquestación de `src/metrics.py`.

Recibe DataFrames ya cargados (la lectura de parquet/csv/config vive en
`scripts/calculate_metrics.py`) y ensambla el pipeline completo: cruce de
población, pesos de análisis, clasificación urbano/rural, y las ~14 tablas
de salida. No importa Streamlit. Sí puede tener lógica específica del
proyecto (nombres de columnas concretos, la regla de urbano/rural del CCPP)
que `metrics.py` deliberadamente no conoce, por ser genérico y testeable
con datos sintéticos.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src import metrics as m
from src.routing import status as st

LOW_ROUTING_COVERAGE_THRESHOLD_PCT = 50.0  # documentado: ver config.md / informe, sección H

#: Corrección estadística final (2026-09-11) — los 2 ÚNICOS `CPINEI`
#: duplicados reales en el universo SIGMED de 19 370 (Tumbes+Amazonas+Cusco),
#: resueltos caso por caso (nombre exacto + cercanía real a la coordenada
#: CENEPRED, NUNCA dividiendo población 50/50 ni tomando "la primera fila"):
#: - `0808040208` ("LLACTACUNCA", pob=0): CODCP 529339 "Llactacunca" (nombre
#:   exacto, 2796m de CENEPRED) vs CODCP 670431 "Llactacunca Huillcana"
#:   (4177m) -> se elige 529339. Población=0, así que esta elección no
#:   afecta ninguna métrica ponderada.
#: - `0809060005` ("PENETRACION YAVERO", pob=69): CODCP 614684 "Penetracion"
#:   (277m de CENEPRED) vs CODCP 651194 "Yavero" (505m) -> se elige 614684.
#: Ninguno de los dos pares tiene AMBOS miembros en la muestra de 5000 (ver
#: docs/05_representativeness_audit.md), así que esta corrección no cambia
#: ningún resultado de Fase 3 ya publicado — solo corrige el conteo de
#: población del universo U4 (evitaba que 69 personas se contaran dos veces).
POPULATION_REPRESENTATIVE_OVERRIDE: dict[str, str] = {
    "0808040208": "529339",
    "0809060005": "614684",
}


def build_urban_rural_classification(demand_df: pd.DataFrame, ccpp_df: pd.DataFrame, *, urban_categories: list[str], rural_categories: list[str], demand_key_col: str = "CPINEI", ccpp_key_col: str = "CÓDIGO", ccpp_cat_col: str = "CAT_POBLAD", demand_id_col: str = "CODCP") -> pd.DataFrame:
    """[SUPERSEDIDO 2026-09-11 — ver `build_urban_rural_classification_censal`]
    Clasificación urbano/rural vía `CAT_POBLAD` del shapefile IGN CCPP
    (cobertura parcial, 42.2% de los CP con CPINEI). Se conserva por si el
    cruce censal (MINAM `area_17`) llegara a fallar en el futuro; no se usa
    por defecto en `run_phase3_analysis`."""
    left = demand_df[[demand_id_col, demand_key_col]].copy()
    left[demand_key_col] = left[demand_key_col].astype("string")
    right = ccpp_df[[ccpp_key_col, ccpp_cat_col]].drop_duplicates(subset=[ccpp_key_col]).copy()
    right[ccpp_key_col] = right[ccpp_key_col].astype("string")

    merged = left.merge(right, left_on=demand_key_col, right_on=ccpp_key_col, how="left")
    cat = merged[ccpp_cat_col]
    urban_rural = np.select(
        [cat.isin(urban_categories), cat.isin(rural_categories)],
        [m.URBAN, m.RURAL],
        default=m.UNKNOWN_RURALITY,
    )
    out = pd.DataFrame({
        demand_id_col: merged[demand_id_col],
        "urban_rural": urban_rural,
        "urban_rural_source_category": cat,
    })
    return out.rename(columns={demand_id_col: "demand_id"})


def build_urban_rural_classification_censal(
    demand_df: pd.DataFrame,
    minam_df: pd.DataFrame,
    *,
    demand_key_col: str = "CPINEI",
    minam_key_col: str = "idccpp_17",
    minam_area_col: str = "area_17",
    urban_value: int = 1,
    rural_value: int = 2,
    demand_id_col: str = "CODCP",
) -> pd.DataFrame:
    """Clasificación urbano/rural CENSAL (Censo 2017), vía `area_17` de la
    capa MINAM Geoservidor — cruzada por `CPINEI` (99.4% de solapamiento
    real verificado contra `idccpp_17`, ver `docs/03_population_source_inspection.md`
    sección "corrección 2026-09-11"). `area_17` verificado empíricamente:
    valor 1 = perfil urbano (media pob=3081, mediana=646 en los 3
    departamentos), valor 2 = perfil rural (media=50, mediana=17); el valor
    3 (4 registros nacionales, sin documentación oficial encontrada) se
    mapea a `unknown`, no se adivina. Cobertura ~62.8% del universo de 5000
    (misma tasa que el match de población, mismo origen de datos) — muy
    superior al 26.7% del cruce IGN anterior."""
    left = demand_df[[demand_id_col, demand_key_col]].copy()
    left[demand_key_col] = left[demand_key_col].astype("string")
    right = minam_df[[minam_key_col, minam_area_col]].drop_duplicates(subset=[minam_key_col]).copy()
    right[minam_key_col] = right[minam_key_col].astype("string")

    merged = left.merge(right, left_on=demand_key_col, right_on=minam_key_col, how="left")
    area = merged[minam_area_col]
    urban_rural = np.select(
        [area == urban_value, area == rural_value],
        [m.URBAN, m.RURAL],
        default=m.UNKNOWN_RURALITY,
    )
    out = pd.DataFrame({
        demand_id_col: merged[demand_id_col],
        "urban_rural": urban_rural,
        "urban_rural_source_area_17": area,
    })
    return out.rename(columns={demand_id_col: "demand_id"})


def build_population_universe_unique(
    sigmed_full_df: pd.DataFrame,
    population_df: pd.DataFrame,
    *,
    demand_key_col: str = "CPINEI",
    population_key_col: str,
    population_value_col: str,
    demand_id_col: str = "CODCP",
    representative_override: dict[str, str] | None = None,
) -> pd.DataFrame:
    """U4_unique_census_cp: una fila por CP CENSAL ÚNICO (clave de
    población), con su población contada UNA SOLA VEZ — nunca sumada una vez
    por cada fila SIGMED que comparta esa clave (ver
    `POPULATION_REPRESENTATIVE_OVERRIDE`). DEP/PROV/DIST se toman de la fila
    SIGMED representante. `population_U4 = sum(population)` de esta tabla
    reproduce 1,800,859 (verificado)."""
    representative_override = representative_override or {}
    sig = sigmed_full_df.rename(columns={demand_id_col: "demand_id"}).copy()
    sig["demand_id"] = sig["demand_id"].astype("string")
    sig[demand_key_col] = sig[demand_key_col].astype("string")

    rep_flag = m.flag_population_representative(
        sig, demand_key_col=demand_key_col, demand_id_col="demand_id", representative_override=representative_override,
    )
    n_rows_per_key = sig.groupby(demand_key_col)["demand_id"].transform("size")
    representative_rows = sig[rep_flag].copy()
    representative_rows["n_sigmed_rows_for_key"] = n_rows_per_key[rep_flag]

    pop = population_df[[population_key_col, population_value_col]].copy()
    pop[population_key_col] = pop[population_key_col].astype("string")
    pop_indexed = pop.drop_duplicates(subset=[population_key_col]).set_index(population_key_col)[population_value_col]

    matched = representative_rows[representative_rows[demand_key_col].isin(pop_indexed.index)].copy()
    matched["population"] = pd.to_numeric(matched[demand_key_col].map(pop_indexed), errors="coerce")

    return matched[[demand_key_col, "demand_id", "DEP", "PROV", "DIST", "population", "n_sigmed_rows_for_key"]].rename(
        columns={demand_key_col: "census_cp_id", "demand_id": "representative_demand_id"}
    ).reset_index(drop=True)


def build_population_duplicate_resolution_report(
    sigmed_full_df: pd.DataFrame,
    population_df: pd.DataFrame,
    demand_routing_status_df: pd.DataFrame,
    demand_5000_ids: set[str],
    *,
    demand_key_col: str = "CPINEI",
    population_key_col: str,
    population_value_col: str,
    population_name_col: str = "arnombre",
    demand_id_col: str = "CODCP",
    representative_override: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Reporte caso-por-caso de los CPINEI duplicados en SIGMED (Sección A
    de la auditoría de representatividad): CODCP, CPINEI, nombre SIGMED,
    nombre CENEPRED, UBIGEO, coordenadas, población CENEPRED, presencia en
    U3/U5, routing, y distancia real entre los dos puntos SIGMED."""
    from src.routing.compare import haversine_m

    representative_override = representative_override or {}
    sig = sigmed_full_df.rename(columns={demand_id_col: "demand_id"}).copy()
    sig["demand_id"] = sig["demand_id"].astype("string")
    sig[demand_key_col] = sig[demand_key_col].astype("string")
    dup_mask = sig[demand_key_col].notna() & sig[demand_key_col].duplicated(keep=False)
    dups = sig[dup_mask].copy()

    pop = population_df.copy()
    pop[population_key_col] = pop[population_key_col].astype("string")
    pop_indexed = pop.drop_duplicates(subset=[population_key_col]).set_index(population_key_col)

    routing = demand_routing_status_df.copy()
    routing["demand_id"] = routing["demand_id"].astype("string")
    routing_idx = routing.set_index("demand_id")["routing_status_car"] if "routing_status_car" in routing.columns else pd.Series(dtype="string")

    rows = []
    for key, g in dups.groupby(demand_key_col):
        pop_row = pop_indexed.loc[key] if key in pop_indexed.index else None
        cen_name = pop_row[population_name_col] if pop_row is not None else None
        cen_pop = pop_row[population_value_col] if pop_row is not None else np.nan
        pts = g[["demand_id", "NOMCP", "XGD", "YGD"]].to_dict("records")
        dist_m = haversine_m(pts[0]["XGD"], pts[0]["YGD"], pts[1]["XGD"], pts[1]["YGD"]) if len(pts) == 2 else np.nan
        for r in g.itertuples():
            rid = str(r.demand_id)
            rows.append({
                "census_cp_id": key,
                "CODCP": rid,
                "NOMCP_sigmed": r.NOMCP,
                "NOMCP_cenepred": cen_name,
                "UBIGEO": r.UBIGEO,
                "XGD": r.XGD,
                "YGD": r.YGD,
                "poblacion_cenepred": cen_pop,
                "en_universo_19370_U3": True,
                "en_muestra_5000_U5": rid in demand_5000_ids,
                "routing_status_car": routing_idx.get(rid),
                "distance_between_sigmed_points_m": dist_m,
                "population_representative": representative_override.get(str(key)) == rid,
            })
    return pd.DataFrame(rows)


def build_demand_analysis(
    demand_df: pd.DataFrame,
    demand_routing_status_df: pd.DataFrame,
    urban_rural_df: pd.DataFrame,
    population_df: pd.DataFrame | None,
    *,
    demand_id_col: str = "CODCP",
    population_key_col: str | None = None,
    population_value_col: str | None = None,
    population_representative_override: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Ensambla la tabla maestra (`demand_analysis`) y el reporte de cruce
    de población. `population_df` puede ser None/vacío (bloqueo documentado
    de fuente de población por CP) — en ese caso todo el universo queda
    `population_match_status="unmatched"`, de forma honesta, no simulada.

    `population_representative_override`: ver
    `POPULATION_REPRESENTATIVE_OVERRIDE` — evita que un CP censal duplicado
    en SIGMED aporte su población dos veces si AMBAS filas cayeran en la
    misma muestra (no ocurre en la muestra actual de 5000, pero la lógica es
    genérica y a prueba de futuras re-muestras)."""
    demand = demand_df.rename(columns={demand_id_col: "demand_id"}).copy()
    demand["demand_id"] = demand["demand_id"].astype("string")

    routing = demand_routing_status_df.copy()
    routing["demand_id"] = routing["demand_id"].astype("string")

    if population_df is None or len(population_df) == 0 or population_key_col is None:
        # Placeholder vacío con el esquema esperado -> 100% unmatched, explícito.
        population_df = pd.DataFrame({"__key__": pd.array([], dtype="string"), "__pop__": pd.array([], dtype="float64")})
        population_key_col, population_value_col = "__key__", "__pop__"

    population_representative = None
    if population_representative_override is not None:
        population_representative = m.flag_population_representative(
            demand, demand_key_col="CPINEI", demand_id_col="demand_id",
            representative_override=population_representative_override,
        )

    match_report = m.build_population_match_report(
        demand, population_df,
        demand_key_col="CPINEI", population_key_col=population_key_col, population_value_col=population_value_col,
        demand_id_col="demand_id",
        demand_secondary_key_col="CPINEI2" if "CPINEI2" in demand.columns else None,
        population_representative=population_representative,
    )
    weights = m.build_analysis_weights(match_report, demand, demand_id_col="demand_id")

    analysis = (
        demand.merge(routing, on="demand_id", how="left", suffixes=("", "_routing"))
        .merge(weights[["demand_id", "population", "population_match_status", "analysis_weight"]], on="demand_id", how="left")
        .merge(urban_rural_df, on="demand_id", how="left")
    )
    analysis["urban_rural"] = analysis["urban_rural"].fillna(m.UNKNOWN_RURALITY)
    analysis["t_min"] = m.compute_access_time(analysis, routing_status_col="routing_status_car", travel_time_col="travel_time_min_car")
    # Alias explícito (Sección 4 de la auditoría): analysis_weight ES el peso
    # Horvitz-Thompson SIN calibrar. Se conserva `analysis_weight` por
    # compatibilidad y se añade `ht_population_weight` con el nombre
    # inequívoco que usa el resto del pipeline de calibración.
    analysis["ht_population_weight"] = analysis["analysis_weight"]

    return {"demand_analysis": analysis, "population_match_report": match_report}


def run_phase3_analysis(
    demand_df: pd.DataFrame,
    demand_routing_status_df: pd.DataFrame,
    urban_rural_df: pd.DataFrame,
    population_df: pd.DataFrame | None,
    three_mode_df: pd.DataFrame,
    *,
    demand_id_col: str = "CODCP",
    population_key_col: str | None = None,
    population_value_col: str | None = None,
    minam_df: pd.DataFrame | None = None,
    department_population_benchmark: pd.DataFrame | None = None,
    sigmed_full_df: pd.DataFrame | None = None,
    population_representative_override: dict[str, str] | None = None,
    routed_car_before_track: int,
    routed_car_after_track: int,
    points_recovered_by_track: int,
    low_routing_coverage_threshold_pct: float = LOW_ROUTING_COVERAGE_THRESHOLD_PCT,
) -> dict[str, Any]:
    """Pipeline completo de Fase 3, con calibración de pesos por distrito
    (corrección estadística final, 2026-09-11). `sigmed_full_df` (el
    universo de 19,370 CP, ANTES del muestreo) es requerido para construir
    U4_unique_census_cp y el `known_population_h` por distrito contra el que
    se calibra; si se omite, se usa el peso Horvitz-Thompson sin calibrar en
    todas las métricas (comportamiento de la versión anterior)."""
    population_representative_override = population_representative_override or POPULATION_REPRESENTATIVE_OVERRIDE
    built = build_demand_analysis(
        demand_df, demand_routing_status_df, urban_rural_df, population_df,
        demand_id_col=demand_id_col, population_key_col=population_key_col, population_value_col=population_value_col,
        population_representative_override=population_representative_override,
    )
    da = built["demand_analysis"]
    match_report = built["population_match_report"]

    universe_unique = None
    duplicate_resolution = None
    district_calibration = None
    if sigmed_full_df is not None and population_df is not None and population_key_col is not None:
        universe_unique = build_population_universe_unique(
            sigmed_full_df, population_df,
            population_key_col=population_key_col, population_value_col=population_value_col,
            representative_override=population_representative_override,
        )
        duplicate_resolution = build_population_duplicate_resolution_report(
            sigmed_full_df, population_df, demand_routing_status_df, set(da["demand_id"]),
            population_key_col=population_key_col, population_value_col=population_value_col,
            representative_override=population_representative_override,
        )
        known_population_by_district = universe_unique.groupby(["DEP", "PROV", "DIST"])["population"].sum().reset_index().rename(columns={"population": "known_population"})
        calib = m.calibrate_weights_by_district(da, known_population_by_district, group_cols=["DEP", "PROV", "DIST"], ht_weight_col="ht_population_weight")
        da = calib["row_level"]
        district_calibration = calib["district_level"]
        weight_col = "calibrated_weight"
    else:
        da["calibrated_weight"] = da["ht_population_weight"]
        weight_col = "ht_population_weight"

    demand_renamed = demand_df.rename(columns={demand_id_col: "demand_id"})
    population_match_summary = m.population_match_summary(match_report, demand_renamed)
    representativeness = m.sample_representativeness_summary(demand_renamed, match_report)
    design_weight_check = m.verify_design_weights(demand_df, stratum_col="stratum_n" if "stratum_n" in demand_df.columns else None)

    minam_cross_validation = None
    if minam_df is not None and population_df is not None and population_key_col is not None:
        minam_cross_validation = m.cross_validate_population_sources(
            population_df, minam_df,
            key_a=population_key_col, key_b="idccpp_17", value_a=population_value_col, value_b="pob17",
        )

    population_control = None
    if department_population_benchmark is not None:
        population_control = m.population_control_by_department(match_report, demand_renamed, department_population_benchmark)

    routing_completeness = m.routing_completeness_summary(da, weight_col=weight_col)
    coverage_total = m.compute_coverage_bands(da, weight_col=weight_col)

    def _coverage_by(group_cols: list[str], wcol: str) -> pd.DataFrame:
        rows = []
        for keys, g in da.groupby(group_cols, dropna=False):
            keys = keys if isinstance(keys, tuple) else (keys,)
            bands = m.compute_coverage_bands(g, weight_col=wcol)["reading_a_sobre_poblacion_con_tiempo_estimable"]
            row = dict(zip(group_cols, keys))
            for _, r in bands.iterrows():
                row[f"pct_{r['band']}"] = r["pct"]
                row[f"pop_{r['band']}"] = r["poblacion_ponderada"]
            rows.append(row)
        return pd.DataFrame(rows)

    coverage_department = _coverage_by(["DEP"], weight_col)
    coverage_province = _coverage_by(["DEP", "PROV"], weight_col)
    coverage_district = _coverage_by(["DEP", "PROV", "DIST"], weight_col)

    weighted_access_department = m.weighted_mean_access(da, ["DEP"], weight_col=weight_col)
    weighted_access_province = m.weighted_mean_access(da, ["DEP", "PROV"], weight_col=weight_col)
    weighted_access_district = m.weighted_mean_access(da, ["DEP", "PROV", "DIST"], weight_col=weight_col)
    weighted_access_total = m.weighted_mean_access(da, None, weight_col=weight_col)

    # --- versión HT sin calibrar, en paralelo, para transparencia/sensibilidad ---
    weighted_access_department_ht = m.weighted_mean_access(da, ["DEP"], weight_col="ht_population_weight")
    weighted_access_total_ht = m.weighted_mean_access(da, None, weight_col="ht_population_weight")

    # --- ranking de brechas críticas con estados de calidad de dato explícitos ---
    if district_calibration is not None:
        weighted_access_district = weighted_access_district.merge(
            district_calibration[["DEP", "PROV", "DIST", "calibration_status", "calibration_factor", "known_population", "ht_total"]],
            on=["DEP", "PROV", "DIST"], how="left",
        )
    weighted_access_district["district_status"] = m.classify_district_data_quality(
        weighted_access_district, low_routing_coverage_threshold_pct=low_routing_coverage_threshold_pct,
    )
    critical_gap_districts = m.rank_critical_gaps(
        weighted_access_district, district_cols=["DEP", "PROV", "DIST"],
        low_routing_coverage_threshold_pct=low_routing_coverage_threshold_pct,
    )
    gap_split = m.split_critical_gaps(weighted_access_district)

    u2_total_population = float(population_df[population_value_col].astype(float).sum()) if population_df is not None and population_key_col is not None and len(population_df) else np.nan
    u4_total_population = float(universe_unique["population"].sum()) if universe_unique is not None else np.nan
    gini_result = m.weighted_gini(da["t_min"], da[weight_col])
    gini_result["weight_used"] = weight_col
    gini_result["u4_total_population"] = u4_total_population
    gini_result["u2_total_population"] = u2_total_population
    gini_result["pct_of_u4_included"] = 100.0 * gini_result["population_included"] / u4_total_population if u4_total_population else np.nan
    gini_result["pct_of_u2_included"] = 100.0 * gini_result["population_included"] / u2_total_population if u2_total_population else np.nan
    gini_result["label"] = (
        "Gini del tiempo de acceso en automovil entre la poblacion del frame "
        "SIGMED-Censo 2017 (U4) con tiempo de ruta estimable -- NO es el Gini "
        "de toda la poblacion censal (U2), ni de toda la poblacion U4."
    )
    lorenz = m.build_lorenz_curve(da["t_min"], da[weight_col])

    urban_rural_summary = m.urban_rural_summary(da, weight_col=weight_col)
    cross_analysis = m.rurality_access_cross_analysis(da, weight_col=weight_col)

    extreme_cases = m.top_extreme_access_cases(da, n=20)
    unroutable_by_dep = m.unroutable_concentration_summary(da, group_cols=["DEP"], weight_col=weight_col)
    unroutable_by_dep_rurality = m.unroutable_concentration_summary(da, group_cols=["DEP", "urban_rural"], weight_col=weight_col)

    foot_car_extreme = m.foot_over_car_extreme_ratio(three_mode_df) if "foot_over_car_ratio" in three_mode_df.columns else pd.DataFrame()

    track_impact = m.track_impact_table(
        routed_before=routed_car_before_track, routed_after=routed_car_after_track,
        points_recovered=points_recovered_by_track, universe_n=len(da),
    )

    # --- Effective sample size (diagnóstico de concentración de pesos) ---
    ess_rows = [{"scope": "TOTAL", "n_eff_ht": m.effective_sample_size(da["ht_population_weight"]), "n_eff_calibrated": m.effective_sample_size(da["calibrated_weight"])}]
    for dep, g in da.groupby("DEP"):
        ess_rows.append({"scope": dep, "n_eff_ht": m.effective_sample_size(g["ht_population_weight"]), "n_eff_calibrated": m.effective_sample_size(g["calibrated_weight"])})
    effective_sample_size_table = pd.DataFrame(ess_rows)

    # --- HT sin calibrar vs calibrado: TOTAL y por departamento ---
    def _ht_vs_calibrated_row(scope: str, ht_row: pd.Series, cal_row: pd.Series) -> dict:
        return {
            "scope": scope,
            "weighted_mean_access_min_ht": ht_row["weighted_mean_access_min"],
            "weighted_mean_access_min_calibrated": cal_row["weighted_mean_access_min"],
            "diff_weighted_mean_access_min": cal_row["weighted_mean_access_min"] - ht_row["weighted_mean_access_min"],
        }
    ht_vs_cal_rows = [_ht_vs_calibrated_row("TOTAL", weighted_access_total_ht.iloc[0], weighted_access_total.iloc[0])]
    for dep in weighted_access_department["DEP"]:
        ht_row = weighted_access_department_ht.set_index("DEP").loc[dep]
        cal_row = weighted_access_department.set_index("DEP").loc[dep]
        ht_vs_cal_rows.append(_ht_vs_calibrated_row(dep, ht_row, cal_row))
    phase3_metrics_ht_vs_calibrated = pd.DataFrame(ht_vs_cal_rows)

    # --- Urban/rural: cobertura poblacional explícita (Sección L) ---
    n_classified = int((da["urban_rural"] != m.UNKNOWN_RURALITY).sum())
    pop_classified = da.loc[da["urban_rural"] != m.UNKNOWN_RURALITY, "calibrated_weight"].sum()
    pop_total_weighted = da["calibrated_weight"].sum(min_count=1)
    pop_routed_classified = da.loc[(da["urban_rural"] != m.UNKNOWN_RURALITY) & (da["t_min"].notna()), "calibrated_weight"].sum()
    pop_routed_total = da.loc[da["t_min"].notna(), "calibrated_weight"].sum(min_count=1)
    urban_rural_coverage = pd.DataFrame([{
        "n_cp_classified": n_classified,
        "n_cp_total": len(da),
        "poblacion_calibrada_clasificada": pop_classified,
        "pct_poblacion_u4_clasificada": 100.0 * pop_classified / pop_total_weighted if pop_total_weighted else np.nan,
        "pct_poblacion_ruteada_clasificada": 100.0 * pop_routed_classified / pop_routed_total if pop_routed_total else np.nan,
    }])

    n_matched = int((da["population_match_status"] == m.MATCHED).sum())
    frame_coverage_u4_u2 = 100.0 * u4_total_population / u2_total_population if u2_total_population else np.nan
    phase3_summary = pd.DataFrame([{
        "universe_n": len(da),
        "n_population_matched": n_matched,
        "pct_population_matched": 100.0 * n_matched / len(da),
        "n_routed_car": int((da["routing_status_car"] == st.ROUTED).sum()),
        "n_snap_failed_car": int((da["routing_status_car"] == st.SNAP_FAILED).sum()),
        "n_no_route_same_department_car": int((da["routing_status_car"] == st.NO_ROUTE_SAME_DEPT).sum()),
        "weighted_gini_access": gini_result["gini"],
        "gini_pct_population_excluded": gini_result["pct_population_excluded"],
        "weighted_mean_access_min_total_calibrated": weighted_access_total["weighted_mean_access_min"].iloc[0] if len(weighted_access_total) else np.nan,
        "weighted_mean_access_min_total_ht": weighted_access_total_ht["weighted_mean_access_min"].iloc[0] if len(weighted_access_total_ht) else np.nan,
        "u4_total_population": u4_total_population,
        "u2_total_population": u2_total_population,
        "frame_coverage_u4_over_u2_pct": frame_coverage_u4_u2,
        "population_source_status": "BLOQUEADO: sin fuente oficial de poblacion por centro poblado (ver docs/03_population_source_inspection.md)" if n_matched == 0 else "ok",
    }])

    return {
        "demand_analysis": da,
        "population_match_report": match_report,
        "population_match_summary": population_match_summary,
        "sample_representativeness": representativeness,
        "design_weight_check": design_weight_check,
        "minam_cross_validation": minam_cross_validation,
        "population_control_by_department": population_control,
        "routing_completeness": routing_completeness,
        "coverage_bands_total": coverage_total,
        "coverage_bands_department": coverage_department,
        "coverage_bands_province": coverage_province,
        "coverage_bands_district": coverage_district,
        "weighted_access_department": weighted_access_department,
        "weighted_access_province": weighted_access_province,
        "weighted_access_district": weighted_access_district,
        "weighted_access_total": weighted_access_total,
        "critical_gap_districts": critical_gap_districts,
        "gini_result": gini_result,
        "lorenz_curve": lorenz,
        "urban_rural_summary": urban_rural_summary,
        "rurality_cross_analysis": cross_analysis,
        "extreme_cases": extreme_cases,
        "unroutable_by_department": unroutable_by_dep,
        "unroutable_by_department_rurality": unroutable_by_dep_rurality,
        "foot_car_extreme_ratio": foot_car_extreme,
        "track_impact_table": track_impact,
        "phase3_summary": phase3_summary,
        "population_universe_unique": universe_unique,
        "population_duplicate_resolution": duplicate_resolution,
        "weight_calibration_by_district": district_calibration,
        "weighted_access_department_ht": weighted_access_department_ht,
        "weighted_access_total_ht": weighted_access_total_ht,
        "worst_computable_districts": gap_split["worst_computable_districts"],
        "districts_with_insufficient_data": gap_split["districts_with_insufficient_data"],
        "effective_sample_size": effective_sample_size_table,
        "phase3_metrics_ht_vs_calibrated": phase3_metrics_ht_vs_calibrated,
        "urban_rural_coverage": urban_rural_coverage,
        "weight_col_used": weight_col,
    }
