"""audit_representativeness (Fase 3 — auditoría focalizada, 2026-09-11).

Auditoría de representatividad poblacional pedida explícitamente para
decidir si `design_weight` expande razonablemente hacia el universo para el
que fue diseñado. NO cambia métricas de Fase 3, NO recalcula routing, NO usa
Streamlit, NO hace commit — es un script de solo lectura/diagnóstico
adicional que escribe CSVs de auditoría bajo `data/outputs/audit_*`.

No modifica `src/metrics.py` ni `src/analysis.py`; reutiliza
`build_population_match_report`/`build_analysis_weights` tal como están.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd
import pandas as pd

from src import metrics as m
from src.config import get_path, load_config


def main() -> None:
    cfg = load_config()
    outputs_dir = get_path("data_outputs", cfg)

    cenepred = pd.read_parquet(REPO_ROOT / "data/raw/inei_cenepred/ccpp_raw.parquet")
    cenepred["pob_total"] = pd.to_numeric(cenepred["pob_total"], errors="coerce")
    cenepred["codccpp"] = cenepred["codccpp"].astype("string")

    sigmed_full = gpd.read_file(REPO_ROOT / "data/raw/sigmed/extracted/CP_P.shp")
    sigmed_full = sigmed_full[sigmed_full["DEP"].isin(["TUMBES", "AMAZONAS", "CUSCO"])].rename(columns={"CODCP": "demand_id"})
    sigmed_full["demand_id"] = sigmed_full["demand_id"].astype("string")

    demand = pd.read_parquet(REPO_ROOT / "data/processed/demand.parquet").rename(columns={"CODCP": "demand_id"})
    demand["demand_id"] = demand["demand_id"].astype("string")

    # --- Sección 2: población CENEPRED vs benchmark censal, por depto/prov ---
    import openpyxl
    wb = openpyxl.load_workbook(REPO_ROOT / "data/raw/inei/2_Inf_de_Poblacion-CensoNacional-2017.xlsx", data_only=True)
    ws = wb["DISTRITAL"]
    rows = list(ws.iter_rows(min_row=5, values_only=True))
    header, data = rows[0], rows[1:]
    mimp = pd.DataFrame(data, columns=header)
    mimp = mimp[mimp["UBIGEO"].notna()].copy()
    age_cols = list(header[4:11])
    mimp["pob_total"] = mimp[age_cols].sum(axis=1)
    mimp3 = mimp[mimp["DEPARTAMENTO"].isin(["TUMBES", "AMAZONAS", "CUSCO"])]

    cen_dep = cenepred.groupby("nomb_dep")["pob_total"].sum()
    mimp_dep = mimp3.groupby("DEPARTAMENTO")["pob_total"].sum()
    dep_comp = pd.DataFrame({"cenepred_pob_total": cen_dep, "censo2017_benchmark": mimp_dep})
    dep_comp["diff_abs"] = dep_comp["censo2017_benchmark"] - dep_comp["cenepred_pob_total"]
    dep_comp["diff_pct"] = 100 * dep_comp["diff_abs"] / dep_comp["censo2017_benchmark"]
    dep_comp["coverage_ratio"] = dep_comp["cenepred_pob_total"] / dep_comp["censo2017_benchmark"]
    dep_comp = dep_comp.reset_index().rename(columns={"index": "DEP", "nomb_dep": "DEP"})
    dep_comp.to_csv(outputs_dir / "audit_cenepred_vs_censo_department.csv", index=False)

    cenepred["prov_key"] = cenepred["nomb_dep"].str.upper().str.strip() + "|" + cenepred["nomb_pro"].str.upper().str.strip()
    mimp3 = mimp3.copy()
    mimp3["prov_key"] = mimp3["DEPARTAMENTO"].str.upper().str.strip() + "|" + mimp3["PROVINCIA"].str.upper().str.strip()
    prov_comp = pd.DataFrame({
        "cenepred_pob_total": cenepred.groupby("prov_key")["pob_total"].sum(),
        "censo2017_benchmark": mimp3.groupby("prov_key")["pob_total"].sum(),
    })
    prov_comp["diff_abs"] = prov_comp["censo2017_benchmark"] - prov_comp["cenepred_pob_total"]
    prov_comp["diff_pct"] = 100 * prov_comp["diff_abs"] / prov_comp["censo2017_benchmark"]
    prov_comp = prov_comp.reset_index().rename(columns={"index": "prov_key"})
    prov_comp.to_csv(outputs_dir / "audit_cenepred_vs_censo_province.csv", index=False)

    # --- Sección 3: cuánta población CENEPRED captura SIGMED ---
    sigmed_cpinei_primary = set(sigmed_full["CPINEI"].dropna().astype(str))
    cenepred["matched_in_sigmed"] = cenepred["codccpp"].isin(sigmed_cpinei_primary)
    cap = cenepred.groupby(["nomb_dep", "matched_in_sigmed"]).agg(n_cp=("codccpp", "size"), poblacion=("pob_total", "sum")).reset_index()
    cap.to_csv(outputs_dir / "audit_cenepred_population_captured_by_sigmed.csv", index=False)

    # --- Sección 4: caracterización de los 7148 SIGMED sin match ---
    cenepred_ids = set(cenepred["codccpp"])
    cpinei = sigmed_full["CPINEI"].astype("string")
    cpinei2 = sigmed_full["CPINEI2"].astype("string")
    matched_cpinei = cpinei.isin(cenepred_ids)
    unmatched = sigmed_full[~matched_cpinei].copy()
    grpA = unmatched[unmatched["CPINEI"].isna()].copy()
    grpA["audit_group"] = "A_cpinei_ausente"
    with_cpinei_unmatched = unmatched[unmatched["CPINEI"].notna()].copy()
    grpC_mask = with_cpinei_unmatched["CPINEI2"].notna() & with_cpinei_unmatched["CPINEI2"].astype(str).isin(cenepred_ids)
    grpC = with_cpinei_unmatched[grpC_mask].copy()
    grpC["audit_group"] = "C_cpinei2_rescataria"
    grpB = with_cpinei_unmatched[~grpC_mask].copy()
    grpB["audit_group"] = "B_cpinei_presente_sin_match_cenepred"
    unmatched_labeled = pd.concat([grpA, grpB, grpC])[["demand_id", "DEP", "PROV", "DIST", "NOMCP", "NIVEL", "CON_IE", "CPINEI", "CPINEI2", "audit_group"]]
    unmatched_labeled.to_csv(outputs_dir / "audit_sigmed_unmatched_characterization.csv", index=False)

    summary_unmatched = unmatched_labeled.groupby(["audit_group", "DEP"]).size().reset_index(name="n_cp")
    summary_unmatched.to_csv(outputs_dir / "audit_sigmed_unmatched_summary.csv", index=False)

    # --- Sección 5: design_weight vs U4 (universo matched real), no censo total ---
    match_report_sample = m.build_population_match_report(demand, cenepred, demand_key_col="CPINEI", population_key_col="codccpp", population_value_col="pob_total", demand_id_col="demand_id")
    weights = m.build_analysis_weights(match_report_sample, demand, demand_id_col="demand_id")
    weights = weights.merge(demand[["demand_id", "DEP", "PROV", "DIST"]], on="demand_id")

    full_match = m.build_population_match_report(sigmed_full, cenepred, demand_key_col="CPINEI", population_key_col="codccpp", population_value_col="pob_total", demand_id_col="demand_id")
    full_match = full_match.merge(sigmed_full[["demand_id", "DEP", "PROV", "DIST"]], on="demand_id")

    def _compare(group_cols):
        est = weights[weights["population_match_status"] == m.MATCHED].groupby(group_cols)["analysis_weight"].sum()
        real = full_match[full_match["population_match_status"] == m.MATCHED].groupby(group_cols)["population"].sum()
        out = pd.DataFrame({"estimado_design_weight": est, "real_U4_matched_universe": real}).dropna()
        out["ratio_estimado_sobre_real"] = out["estimado_design_weight"] / out["real_U4_matched_universe"]
        out["diff_pct"] = 100 * (out["estimado_design_weight"] - out["real_U4_matched_universe"]) / out["real_U4_matched_universe"]
        return out.reset_index()

    total_est = weights.loc[weights["population_match_status"] == m.MATCHED, "analysis_weight"].sum()
    total_real = full_match.loc[full_match["population_match_status"] == m.MATCHED, "population"].sum()
    pd.DataFrame([{
        "estimado_design_weight": total_est, "real_U4_matched_universe": total_real,
        "ratio_estimado_sobre_real": total_est / total_real, "diff_pct": 100 * (total_est - total_real) / total_real,
    }]).to_csv(outputs_dir / "audit_design_weight_validation_total.csv", index=False)
    _compare(["DEP"]).to_csv(outputs_dir / "audit_design_weight_validation_department.csv", index=False)
    _compare(["DEP", "PROV"]).to_csv(outputs_dir / "audit_design_weight_validation_province.csv", index=False)

    print("Auditoría de representatividad escrita en data/outputs/audit_*.csv")


if __name__ == "__main__":
    main()
