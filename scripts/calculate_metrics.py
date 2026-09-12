"""calculate_metrics (Fase 3).

Lee los insumos de Fase 1/2 (`data/processed/demand.parquet`,
`data/outputs/demand_routing_status.parquet`,
`data/outputs/comparison_car_bike_foot.parquet`), la población real por
centro poblado (CENEPRED/SIGRID, `data/raw/inei_cenepred/`), la validación
cruzada + urbano/rural censal (MINAM Geoservidor, `data/raw/inei_minam/`), y
los números ya calculados de Fase 2 (`routing_quality_report.csv`, para la
tabla de impacto de `track` — no se recalcula nada); corre
`src/analysis.py::run_phase3_analysis` y escribe todas las tablas de salida
en `data/outputs/` + figuras en `figures/`.

Corrección 2026-09-11: la conclusión previa ("no existe población oficial
por centro poblado") era incorrecta — CENEPRED/SIGRID y MINAM Geoservidor sí
exponen servicios ArcGIS REST vivos que redistribuyen el Censo 2017 INEI a
nivel de centro poblado, con `codccpp`/`idccpp_17` de 10 dígitos compatibles
con `CPINEI` (99.3%/99.4% de solapamiento verificado). Ver
`docs/03_population_source_inspection.md` para la investigación completa.

No usa Streamlit. No hace commit. No genera el informe final en LaTeX. No
usa fallback de población distrital (MIMP) como población de CP — ese
archivo se usa solo como benchmark departamental de control.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
import pandas as pd

from src.analysis import POPULATION_REPRESENTATIVE_OVERRIDE, build_urban_rural_classification_censal, run_phase3_analysis
from src.config import get_path, load_config


def _load_department_population_benchmark(path: Path, departments: list[str]) -> pd.DataFrame:
    """Población real Censo 2017 por departamento (MIMP/INEI, DISTRITAL
    agregado) — usada SOLO como benchmark de control, nunca como población
    de CP (ver docs/03_population_source_inspection.md)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["DISTRITAL"]
    rows = list(ws.iter_rows(min_row=5, values_only=True))
    header, data = rows[0], rows[1:]
    df = pd.DataFrame(data, columns=header)
    df = df[df["UBIGEO"].notna()]
    age_cols = list(header[4:11])
    df["pob_total"] = df[age_cols].sum(axis=1)
    by_dep = df.groupby("DEPARTAMENTO")["pob_total"].sum()
    return pd.DataFrame({"dep": departments, "poblacion_censo2017_real": [by_dep[d] for d in departments]})


def _read_routing_quality_report(path: Path) -> dict[str, str]:
    df = pd.read_csv(path)
    return dict(zip(df["metric"], df["value"]))


def _write(df: pd.DataFrame, out_dir: Path, name: str) -> None:
    df.to_parquet(out_dir / f"{name}.parquet", index=False)
    df.to_csv(out_dir / f"{name}.csv", index=False)
    print(f"  - {name}: {len(df)} filas")


def main() -> None:
    cfg = load_config()
    processed_dir = get_path("data_processed", cfg)
    outputs_dir = get_path("data_outputs", cfg)
    figures_dir = get_path("figures", cfg)
    tables_dir = get_path("tables", cfg)
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    print("Cargando insumos de Fase 1/2...")
    demand_df = pd.read_parquet(processed_dir / "demand.parquet").drop(columns=["geometry"], errors="ignore")
    demand_routing_status_df = pd.read_parquet(outputs_dir / "demand_routing_status.parquet")
    three_mode_df = pd.read_parquet(outputs_dir / "comparison_car_bike_foot.parquet")

    print("Cargando población real por centro poblado (CENEPRED/SIGRID, Censo 2017 INEI)...")
    cenepred_cfg = cfg["acquisition"]["inei_cenepred_ccpp"]
    minam_cfg = cfg["acquisition"]["inei_minam_ccpp"]
    cenepred_df = pd.read_parquet(REPO_ROOT / cenepred_cfg["raw_dir"] / "ccpp_raw.parquet")
    minam_df = pd.read_parquet(REPO_ROOT / minam_cfg["raw_dir"] / "ccpp_raw.parquet")

    quality = _read_routing_quality_report(outputs_dir / "routing_quality_report.csv")
    routed_after = int(quality["car_routed"])
    recovers = int(quality["car_track_recovers_route_to_resolutive"])
    routed_before = routed_after - recovers

    print("Construyendo clasificación urbano/rural censal (MINAM area_17, Censo 2017)...")
    urban_rural_df = build_urban_rural_classification_censal(demand_df, minam_df)

    print("Construyendo benchmark departamental de poblacion (MIMP/INEI, Censo 2017, solo control)...")
    dep_benchmark = _load_department_population_benchmark(
        REPO_ROOT / "data/raw/inei/2_Inf_de_Poblacion-CensoNacional-2017.xlsx",
        departments=["TUMBES", "AMAZONAS", "CUSCO"],
    )

    print("Cargando universo SIGMED completo (19,370 CP, 3 departamentos, pre-muestreo) para U4...")
    sigmed_full = gpd.read_file(REPO_ROOT / "data/raw/sigmed/extracted/CP_P.shp")
    sigmed_full = sigmed_full[sigmed_full["DEP"].isin(["TUMBES", "AMAZONAS", "CUSCO"])].copy()

    print("Ejecutando pipeline de Fase 3 (src/analysis.py) con población real CENEPRED + calibración por distrito...")
    results = run_phase3_analysis(
        demand_df, demand_routing_status_df, urban_rural_df,
        population_df=cenepred_df, three_mode_df=three_mode_df,
        demand_id_col="CODCP",
        population_key_col=cenepred_cfg["id_field"], population_value_col=cenepred_cfg["population_field"],
        minam_df=minam_df, department_population_benchmark=dep_benchmark,
        sigmed_full_df=sigmed_full, population_representative_override=POPULATION_REPRESENTATIVE_OVERRIDE,
        routed_car_before_track=routed_before, routed_car_after_track=routed_after, points_recovered_by_track=recovers,
    )

    print("\nEscribiendo outputs en data/outputs/:")
    da = results["demand_analysis"]
    _write(da, outputs_dir, "demand_analysis")
    _write(results["population_match_report"], outputs_dir, "population_match_report")

    if results["population_universe_unique"] is not None:
        _write(results["population_universe_unique"], outputs_dir, "population_universe_unique")
    if results["population_duplicate_resolution"] is not None:
        _write(results["population_duplicate_resolution"], outputs_dir, "population_duplicate_resolution")
    if results["weight_calibration_by_district"] is not None:
        _write(results["weight_calibration_by_district"], outputs_dir, "weight_calibration_by_district")
    _write(results["effective_sample_size"], outputs_dir, "weight_diagnostics")
    _write(results["phase3_metrics_ht_vs_calibrated"], outputs_dir, "phase3_metrics_ht_vs_calibrated")
    _write(results["worst_computable_districts"], outputs_dir, "worst_computable_districts")
    _write(results["districts_with_insufficient_data"], outputs_dir, "districts_with_insufficient_data")
    _write(results["weighted_access_department_ht"], outputs_dir, "weighted_access_department_ht")
    _write(results["weighted_access_total_ht"], outputs_dir, "weighted_access_total_ht")
    _write(results["urban_rural_coverage"], outputs_dir, "urban_rural_coverage")
    _write(results["population_match_summary"], outputs_dir, "population_match_summary")
    _write(results["sample_representativeness"], outputs_dir, "sample_representativeness")
    if results["population_control_by_department"] is not None:
        _write(results["population_control_by_department"], outputs_dir, "population_control_by_department")
    if results["minam_cross_validation"] is not None:
        cv = results["minam_cross_validation"]
        _write(cv["discrepant_examples"], outputs_dir, "cenepred_minam_discrepant_examples")
        flat = {k: v for k, v in cv.items() if k not in ("discrepant_examples", "diff_abs_summary")}
        flat.update({f"diff_abs_{k}": v for k, v in cv["diff_abs_summary"].items()})
        _write(pd.DataFrame([flat]), outputs_dir, "cenepred_minam_cross_validation_summary")
    _write(results["routing_completeness"], outputs_dir, "routing_completeness")
    _write(results["coverage_bands_department"], outputs_dir, "coverage_bands_department")
    _write(results["coverage_bands_province"], outputs_dir, "coverage_bands_province")
    _write(results["coverage_bands_district"], outputs_dir, "coverage_bands_district")
    _write(results["weighted_access_department"], outputs_dir, "weighted_access_department")
    _write(results["weighted_access_province"], outputs_dir, "weighted_access_province")
    _write(results["weighted_access_district"], outputs_dir, "weighted_access_district")
    _write(results["weighted_access_total"], outputs_dir, "weighted_access_total")
    _write(results["critical_gap_districts"], outputs_dir, "critical_gap_districts")
    _write(results["lorenz_curve"], outputs_dir, "lorenz_curve")
    _write(results["urban_rural_summary"], outputs_dir, "urban_rural_summary")
    _write(results["rurality_cross_analysis"]["table"], outputs_dir, "rurality_cross_analysis")
    _write(results["extreme_cases"], outputs_dir, "extreme_access_cases")
    _write(results["unroutable_by_department"], outputs_dir, "unroutable_by_department")
    _write(results["unroutable_by_department_rurality"], outputs_dir, "unroutable_by_department_rurality")
    if len(results["foot_car_extreme_ratio"]):
        _write(results["foot_car_extreme_ratio"], outputs_dir, "foot_over_car_extreme_ratio")
    _write(results["track_impact_table"], outputs_dir, "track_impact_table")

    _write(pd.DataFrame([results["gini_result"]]), outputs_dir, "inequality_summary")

    phase3_summary = results["phase3_summary"]
    dwc = results["design_weight_check"]
    for k, v in dwc.items():
        phase3_summary[f"design_weight_check_{k}"] = v
    _write(phase3_summary, outputs_dir, "phase3_summary")

    print("\nGenerando figuras en figures/:")
    _fig_ecdf(da, figures_dir)
    _fig_lorenz(results["lorenz_curve"], results["gini_result"], figures_dir)
    _fig_coverage_by_department(results["coverage_bands_department"], figures_dir)
    _fig_urban_rural(results["urban_rural_summary"], figures_dir)

    print("\n=== Resumen ===")
    print(phase3_summary.T)


def _fig_ecdf(da: pd.DataFrame, figures_dir: Path) -> None:
    t = da["t_min"].dropna().sort_values()
    fig, ax = plt.subplots(figsize=(6, 4))
    if len(t):
        y = np.arange(1, len(t) + 1) / len(t)
        ax.plot(t.values, y)
    for x in (30, 60, 120):
        ax.axvline(x, linestyle="--", color="gray", linewidth=0.8)
    ax.set_xlabel("Tiempo de acceso en auto (min)")
    ax.set_ylabel("ECDF (fracción de CP con tiempo estimado)")
    ax.set_title("Distribución del tiempo de acceso en auto (ECDF, por CP)")
    fig.tight_layout()
    fig.savefig(figures_dir / "fase3_ecdf_access_time.pdf")
    plt.close(fig)
    print("  - fase3_ecdf_access_time.pdf")


def _fig_lorenz(lorenz: pd.DataFrame, gini_result: dict, figures_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(5, 5))
    if len(lorenz):
        ax.plot(lorenz["cum_pop_share"], lorenz["cum_time_share"], label="Lorenz (tiempo de acceso)")
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="Igualdad perfecta")
    ax.set_xlabel("% acumulado de población (ordenada por tiempo)")
    ax.set_ylabel("% acumulado de tiempo de acceso")
    ax.set_title(f"Curva de Lorenz — Gini={gini_result['gini']:.3f}" if not np.isnan(gini_result["gini"]) else "Curva de Lorenz — Gini no calculable (sin población con tiempo)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(figures_dir / "fase3_lorenz_curve.pdf")
    plt.close(fig)
    print("  - fase3_lorenz_curve.pdf")


def _fig_coverage_by_department(coverage_dep: pd.DataFrame, figures_dir: Path) -> None:
    bands = ["<=30", ">30_<=60", ">60_<=120", ">120"]
    fig, ax = plt.subplots(figsize=(7, 4))
    if len(coverage_dep):
        x = np.arange(len(coverage_dep))
        bottom = np.zeros(len(coverage_dep))
        for b in bands:
            col = f"pct_{b}"
            vals = coverage_dep[col].fillna(0).values if col in coverage_dep.columns else np.zeros(len(coverage_dep))
            ax.bar(x, vals, bottom=bottom, label=b)
            bottom += vals
        ax.set_xticks(x)
        ax.set_xticklabels(coverage_dep["DEP"])
    ax.set_ylabel("% de población con tiempo estimable")
    ax.set_title("Bandas de cobertura por departamento (sobre población con tiempo estimable)")
    ax.legend(title="banda (min)")
    fig.tight_layout()
    fig.savefig(figures_dir / "fase3_coverage_bands_department.pdf")
    plt.close(fig)
    print("  - fase3_coverage_bands_department.pdf")


def _fig_urban_rural(urban_rural_summary: pd.DataFrame, figures_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    df = urban_rural_summary.set_index("urban_rural")
    ax.bar(df.index.astype(str), df["weighted_mean_access_min"].fillna(0))
    ax.set_ylabel("Tiempo medio de acceso ponderado (min)")
    ax.set_title("Acceso en auto: urbano vs rural (asociación descriptiva, no causal)")
    fig.tight_layout()
    fig.savefig(figures_dir / "fase3_urban_rural_comparison.pdf")
    plt.close(fig)
    print("  - fase3_urban_rural_comparison.pdf")


if __name__ == "__main__":
    main()
