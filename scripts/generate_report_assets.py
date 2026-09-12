"""generate_report_assets (Fase 5).

Genera TODO el contenido cuantitativo del informe LaTeX (`report/main.tex`)
a partir de outputs YA calculados en Fases 1-4 — nunca recalcula routing,
nunca cambia pesos ni muestra. Escribe:

- `report/generated/metrics.tex`: macros LaTeX (`\\newcommand`) para cada
  cifra citada en el texto — evita escribir números a mano en múltiples
  sitios; si un output cambia, basta con re-ejecutar este script.
- `report/generated/tables/*.tex`: tablas booktabs generadas desde
  DataFrames reales.
- `report/generated/figures/*.pdf`: figuras vectoriales estáticas
  (matplotlib/geopandas) — nunca screenshots de Streamlit/Folium.

No usa Streamlit. No recalcula routing/pesos/muestra. No hace commit.
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
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from src import metrics as m
from src.config import get_path, load_config

CFG = load_config()
OUT = get_path("data_outputs", CFG)
PROC = get_path("data_processed", CFG)
REPORT_DIR = REPO_ROOT / "report"
GEN = REPORT_DIR / "generated"
FIG_DIR = GEN / "figures"
TAB_DIR = GEN / "tables"

DEPARTMENTS = ["TUMBES", "AMAZONAS", "CUSCO"]
BAND_COLORS = {"<=30 min": "#1a9850", "30-60 min": "#91cf60", "60-120 min": "#fee08b", ">120 min": "#d73027", "No time estimate": "#bdbdbd"}


def esc(s: str) -> str:
    """Escapa caracteres especiales de LaTeX en texto libre (nombres, notas)."""
    s = str(s)
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}")]:
        s = s.replace(a, b)
    return s


def fmt_num(x, decimals=1) -> str:
    if pd.isna(x):
        return "--"
    return f"{x:,.{decimals}f}"


# --------------------------------------------------------------------------
# Carga de outputs reales
# --------------------------------------------------------------------------

def load_all() -> dict:
    da = pd.read_parquet(OUT / "demand_analysis.parquet")
    sigmed_full = gpd.read_file(REPO_ROOT / "data/raw/sigmed/extracted/CP_P.shp")
    sigmed_full = sigmed_full[sigmed_full["DEP"].isin(DEPARTMENTS)]
    d = {
        "da": da,
        "sigmed_universe_n": len(sigmed_full),
        "phase3_summary": pd.read_csv(OUT / "phase3_summary.csv").iloc[0].to_dict(),
        "weighted_access_department": pd.read_csv(OUT / "weighted_access_department.csv"),
        "worst_computable": pd.read_csv(OUT / "worst_computable_districts.csv"),
        "insufficient": pd.read_csv(OUT / "districts_with_insufficient_data.csv"),
        "urban_rural": pd.read_csv(OUT / "urban_rural_summary.csv"),
        "inequality": pd.read_csv(OUT / "inequality_summary.csv").iloc[0].to_dict(),
        "lorenz": pd.read_parquet(OUT / "lorenz_curve.parquet"),
        "routing_quality": dict(zip(pd.read_csv(OUT / "routing_quality_report.csv")["metric"], pd.read_csv(OUT / "routing_quality_report.csv")["value"])),
        "data_quality": pd.read_csv(OUT / "data_quality_report.csv"),
        "straight_vs_network": pd.read_parquet(OUT / "comparison_straight_vs_network_car.parquet"),
        "dashboard_district_metrics": pd.read_parquet(OUT / "dashboard_district_metrics.parquet"),
        "facilities": pd.read_parquet(PROC / "facilities.parquet"),
        "demand_full": pd.read_parquet(PROC / "demand.parquet"),
        "population_match_summary": pd.read_csv(OUT / "population_match_summary.csv"),
        "population_universe_unique": pd.read_parquet(OUT / "population_universe_unique.parquet"),
        "weight_diagnostics": pd.read_csv(OUT / "weight_diagnostics.csv"),
    }
    return d


# --------------------------------------------------------------------------
# Cifras clave -> macros LaTeX
# --------------------------------------------------------------------------

def build_macros(d: dict) -> str:
    p3 = d["phase3_summary"]
    fac = d["facilities"]
    resolutive = fac[fac["is_resolutive"]]
    svn = d["straight_vs_network"]["network_over_straight_ratio"]
    rq = d["routing_quality"]
    wad = d["weighted_access_department"].set_index("DEP")
    ineq = d["inequality"]
    ur = d["urban_rural"].set_index("urban_rural")

    da = d["da"]
    cov_total = m.compute_coverage_bands(da, weight_col="calibrated_weight")["reading_b_cumulative"].set_index("band")["pct"]

    def cov_dep(dep):
        sub = da[da["DEP"] == dep]
        c = m.compute_coverage_bands(sub, weight_col="calibrated_weight")["reading_b_cumulative"].set_index("band")["pct"]
        wm = m.weighted_mean_access(sub, None, weight_col="calibrated_weight")["weighted_mean_access_min"].iloc[0]
        return c, wm

    lines = ["% AUTO-GENERADO por scripts/generate_report_assets.py -- NO editar a mano.", ""]

    def add(name, value):
        lines.append(f"\\newcommand{{\\{name}}}{{{value}}}")

    # --- Sample / universe ---
    add("SigmedUniverse", f"{d['sigmed_universe_n']:,}")
    add("SampleSize", f"{p3['universe_n']:,.0f}")
    add("SampleSeed", "42")
    add("PopulationMatchedPct", f"{p3['pct_population_matched']:.1f}")
    add("UTwoPopulation", f"{p3['u2_total_population']:,.0f}")
    add("UFourPopulation", f"{p3['u4_total_population']:,.0f}")
    add("FrameCoveragePct", f"{p3['frame_coverage_u4_over_u2_pct']:.2f}")
    add("OutsideFramePct", f"{100 - p3['frame_coverage_u4_over_u2_pct']:.2f}")
    add("OutsideFramePop", f"{p3['u2_total_population'] - p3['u4_total_population']:,.0f}")

    # --- Facilities ---
    add("NFacilitiesTotal", f"{len(fac):,}")
    add("NResolutive", f"{len(resolutive):,}")
    add("NResolutiveMissingCoords", f"{resolutive['lon'].isna().sum():,}")
    add("NResolutiveRoutable", f"{int(resolutive['usable_for_routing'].sum()):,}")
    add("NDistrictMismatch", f"{int(fac['qc_district_mismatch'].sum()):,}")
    add("NMissingCoordsAll", f"{int(fac['lon'].isna().sum()):,}")

    # --- Routing ---
    add("OsmCutoffDate", str(rq.get("osm_cutoff_date")))
    add("NetworkNodes", f"{int(rq.get('network_nodes')):,}")
    add("CarSnapFailed", f"{int(rq.get('car_snap_failed')):,}")
    add("CarSnapFailedPct", f"{100*int(rq.get('car_snap_failed'))/int(rq.get('demand_total')):.1f}")
    add("CarRouted", f"{int(rq.get('car_routed')):,}")
    add("CarNoRouteSameDept", f"{int(rq.get('car_no_route_same_department')):,}")
    add("CarNoRouteSameDeptPct", f"{100*int(rq.get('car_no_route_same_department'))/int(rq.get('demand_total')):.1f}")
    add("CrossDeptNotEvaluatedPct", f"{float(rq.get('car_matrix_cross_department_pct')):.1f}")
    add("TrackFallbackSpeed", f"{rq.get('car_track_fallback_speed_kmh')}")
    add("TrackRecovers", f"{int(rq.get('car_track_recovers_route_to_resolutive')):,}")
    add("TrackPreviouslyIsolated", f"{int(rq.get('car_track_previously_isolated')):,}")

    # --- Straight-line vs network ---
    add("SvnMedian", f"{svn.median():.2f}")
    add("SvnMean", f"{svn.mean():.2f}")
    add("SvnMax", f"{svn.max():.2f}")
    add("SvnPctBelowOne", f"{100*(svn < 1).mean():.2f}")

    # --- Main results (calibrated) ---
    add("MeanAccessTotal", f"{p3['weighted_mean_access_min_total_calibrated']:.1f}")
    add("MeanAccessTotalHt", f"{p3['weighted_mean_access_min_total_ht']:.1f}")
    add("MeanAccessDiffHtCal", f"{p3['weighted_mean_access_min_total_ht'] - p3['weighted_mean_access_min_total_calibrated']:.1f}")
    add("CovLeThirtyTotal", f"{cov_total.get('<=30', float('nan')):.1f}")
    add("CovLeSixtyTotal", f"{cov_total.get('<=60 (cum)', float('nan')):.1f}")
    add("CovLeOneTwentyTotal", f"{cov_total.get('<=120 (cum)', float('nan')):.1f}")
    add("CovGtOneTwentyTotal", f"{cov_total.get('>120', float('nan')):.1f}")
    add("CovNoTimeTotal", f"{cov_total.get('sin_tiempo_estimable', float('nan')):.1f}")

    for dep, tag in [("TUMBES", "Tumbes"), ("AMAZONAS", "Amazonas"), ("CUSCO", "Cusco")]:
        c, wm = cov_dep(dep)
        add(f"MeanAccess{tag}", f"{wm:.1f}")
        add(f"CovLeThirty{tag}", f"{c.get('<=30', float('nan')):.1f}")
        add(f"CovLeSixty{tag}", f"{c.get('<=60 (cum)', float('nan')):.1f}")
        add(f"CovLeOneTwenty{tag}", f"{c.get('<=120 (cum)', float('nan')):.1f}")
        add(f"CovGtOneTwenty{tag}", f"{c.get('>120', float('nan')):.1f}")
        add(f"CovNoTime{tag}", f"{c.get('sin_tiempo_estimable', float('nan')):.1f}")

    # --- Critical gaps ---
    top1 = d["worst_computable"].iloc[0]
    add("TopOneDistrict", esc(top1["DIST"].title()))
    add("TopOneTime", f"{top1['weighted_mean_access_min']:.0f}")
    add("NWorstComputable", f"{len(d['worst_computable']):,}")
    add("NInsufficientData", f"{len(d['insufficient']):,}")

    # --- Gini ---
    add("GiniCalibrated", f"{ineq['gini']:.3f}")
    add("GiniPopIncluded", f"{ineq['population_included']:,.0f}")
    add("GiniPctOfUFour", f"{ineq['pct_of_u4_included']:.1f}")
    add("GiniPctExcluded", f"{ineq['pct_population_excluded']:.1f}")

    # --- Urban/rural ---
    add("UrbanMean", f"{ur.loc['urban', 'weighted_mean_access_min']:.1f}")
    add("RuralMean", f"{ur.loc['rural', 'weighted_mean_access_min']:.1f}")
    add("UrbanMedian", f"{ur.loc['urban', 'weighted_median_access_min']:.1f}")
    add("RuralMedian", f"{ur.loc['rural', 'weighted_median_access_min']:.1f}")
    add("UrbanRuralClassifiedPct", f"{100*(da['urban_rural'] != m.UNKNOWN_RURALITY).mean():.1f}")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Tablas LaTeX
# --------------------------------------------------------------------------

def table_data_sources() -> str:
    rows = [
        ("RENIPRESS / SUSALUD", "datosabiertos.gob.pe", "2026-08-31", "facility", "Facility locations, category, status", "Self-reported registry; active status does not guarantee real operational capacity"),
        ("SIGMED / MINEDU", "sigmed.minedu.gob.pe", "2020-02-05", "centro poblado", "Demand-point sampling frame (19{,}370 CP)", "Enumerates finer/informal localities than the official census CP catalogue"),
        ("IGN administrative boundaries", "datosabiertos.gob.pe", "2025-06-24", "polygon", "Department/district boundaries", "1:100{,}000 scale"),
        ("OpenStreetMap / Geofabrik", "download.geofabrik.de", "2026-09-10", "PBF snapshot", "Road network for routing", "Rural coverage in sierra/selva may be incomplete"),
        ("Census 2017 / INEI (via CENEPRED)", "sig.cenepred.gob.pe", "2026-09-11", "centro poblado", "Population per centro poblado", "Primary statistical source: INEI; CENEPRED is a government geospatial redistribution channel"),
        ("MINAM Geoservidor", "minam.gob.pe", "2026-09-11", "centro poblado", "Cross-validation + urban/rural (\\texttt{area\\_17})", "Same underlying Census 2017 product as CENEPRED (independently confirmed)"),
    ]
    lines = [
        r"\begin{tabular}{p{2.6cm}p{2.3cm}p{1.5cm}p{1.3cm}p{3.3cm}p{4.3cm}}",
        r"\toprule",
        r"Dataset & Source & Ref.\ date & Unit & Main use & Key limitation \\",
        r"\midrule",
    ]
    for name, src, date, unit, use, lim in rows:
        lines.append(f"{esc(name)} & \\url{{{src}}} & {date} & {esc(unit)} & {use} & {lim} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def table_access_by_department(d: dict) -> str:
    da = d["da"]
    rows = []
    for scope, sub in [("Total", da)] + [(dep.title(), da[da["DEP"] == dep]) for dep in DEPARTMENTS]:
        cov = m.compute_coverage_bands(sub, weight_col="calibrated_weight")["reading_b_cumulative"].set_index("band")["pct"]
        wm = m.weighted_mean_access(sub, None, weight_col="calibrated_weight")
        pop = wm["total_estimated_population"].iloc[0]
        mean = wm["weighted_mean_access_min"].iloc[0]
        rows.append((scope, pop, mean, cov.get("<=30", np.nan), cov.get("<=60 (cum)", np.nan), cov.get("<=120 (cum)", np.nan), cov.get(">120", np.nan), cov.get("sin_tiempo_estimable", np.nan)))

    lines = [
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r"Scope & Pop.\ frame & Mean (min) & $\leq$30\% & $\leq$60\%$^{\dagger}$ & $\leq$120\%$^{\dagger}$ & $>$120\% & No estimate\% \\",
        r"\midrule",
    ]
    for scope, pop, mean, c30, c60, c120, gt, nt in rows:
        bold = r"\bfseries " if scope == "Total" else ""
        lines.append(f"{bold}{scope} & {pop:,.0f} & {mean:.1f} & {c30:.1f} & {c60:.1f} & {c120:.1f} & {gt:.1f} & {nt:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def table_worst_districts(d: dict, top_n: int = 10) -> str:
    df = d["worst_computable"].head(top_n)
    lines = [
        r"\begin{tabular}{rlllrrr}",
        r"\toprule",
        r"Rank & Department & Province & District & Mean (min) & Pop.\ frame & Routed\% \\",
        r"\midrule",
    ]
    for _, r in df.iterrows():
        lines.append(f"{int(r['rank'])} & {esc(r['DEP'].title())} & {esc(r['PROV'].title())} & {esc(r['DIST'].title())} & {r['weighted_mean_access_min']:.1f} & {r['total_estimated_population']:,.0f} & {r['share_population_with_travel_time_pct']:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def table_data_quality(d: dict) -> str:
    fac = d["facilities"]
    resolutive = fac[fac["is_resolutive"]]
    p3 = d["phase3_summary"]
    rq = d["routing_quality"]
    rows = [
        ("Facilities in scope (3 departments)", f"{len(fac):,}"),
        ("Resolutive facilities", f"{len(resolutive):,}"),
        ("Resolutive facilities missing usable coordinates", f"{int(resolutive['lon'].isna().sum()):,}"),
        ("Resolutive facilities usable for routing", f"{int(resolutive['usable_for_routing'].sum()):,}"),
        ("All facilities: declared-district mismatch (flagged, not corrected)", f"{int(fac['qc_district_mismatch'].sum()):,}"),
        ("Demand points: car snap failed", f"{int(rq.get('car_snap_failed')):,} ({100*int(rq.get('car_snap_failed'))/int(rq.get('demand_total')):.1f}\\%)"),
        ("Demand points: no route within own department", f"{int(rq.get('car_no_route_same_department')):,} ({100*int(rq.get('car_no_route_same_department'))/int(rq.get('demand_total')):.1f}\\%)"),
        ("Census (U2) population reproduced by SIGMED frame (U4)", f"{p3['frame_coverage_u4_over_u2_pct']:.2f}\\%"),
        ("Population outside SIGMED frame (not redistributed)", f"{100 - p3['frame_coverage_u4_over_u2_pct']:.2f}\\%"),
    ]
    lines = [r"\begin{tabular}{p{9.5cm}r}", r"\toprule", r"Item & Value \\", r"\midrule"]
    for label, val in rows:
        lines.append(f"{esc(label)} & {val} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Figuras
# --------------------------------------------------------------------------

def figure_coverage_by_department(d: dict) -> None:
    da = d["da"]
    scopes = ["Total"] + [x.title() for x in DEPARTMENTS]
    data = {"<=30 min": [], "30-60 min": [], "60-120 min": [], ">120 min": [], "No time estimate": []}
    for dep in [None] + DEPARTMENTS:
        sub = da if dep is None else da[da["DEP"] == dep]
        c = m.compute_coverage_bands(sub, weight_col="calibrated_weight")["reading_b_cumulative"].set_index("band")["pct"]
        data["<=30 min"].append(c.get("<=30", 0.0))
        data["30-60 min"].append(c.get("<=60 (cum)", 0.0) - c.get("<=30", 0.0))
        data["60-120 min"].append(c.get("<=120 (cum)", 0.0) - c.get("<=60 (cum)", 0.0))
        data[">120 min"].append(c.get(">120", 0.0))
        data["No time estimate"].append(c.get("sin_tiempo_estimable", 0.0))

    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    bottom = np.zeros(len(scopes))
    x = np.arange(len(scopes))
    for label, color in BAND_COLORS.items():
        vals = np.array(data[label])
        ax.bar(x, vals, bottom=bottom, color=color, label=label, width=0.6)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(scopes)
    ax.set_ylabel("Share of population-frame (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Population coverage by access-time band (calibrated weights)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig1_coverage_by_department.pdf")
    plt.close(fig)


def figure_choropleth(d: dict) -> None:
    districts = gpd.read_file(PROC / "districts.gpkg")
    dm = d["dashboard_district_metrics"]
    merged = districts.merge(dm, on="UBIGEO", how="left")

    fig, ax = plt.subplots(figsize=(6.2, 7.5))
    computable = merged[merged["district_status"] == "computable"]
    insufficient = merged[merged["district_status"] != "computable"]

    insufficient.plot(ax=ax, color="#d9d9d9", edgecolor="white", linewidth=0.2)
    if len(computable):
        computable.plot(ax=ax, column="weighted_mean_access_min", cmap="RdYlGn_r", edgecolor="white", linewidth=0.2, legend=True,
                         legend_kwds={"label": "Weighted mean access time (min)", "shrink": 0.6})
    ax.set_axis_off()
    ax.set_title("Car access time to nearest resolutive facility, by district\n(gray = insufficient data, not zero/low time)", fontsize=10)
    gray_patch = mpatches.Patch(color="#d9d9d9", label="Insufficient data (not computable)")
    ax.legend(handles=[gray_patch], loc="lower left", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig2_choropleth_access.pdf")
    plt.close(fig)


def figure_lorenz(d: dict) -> None:
    lz = d["lorenz"]
    gini = d["inequality"]["gini"]
    fig, ax = plt.subplots(figsize=(4.6, 4.6))
    ax.plot(lz["cum_pop_share"] * 100, lz["cum_time_share"] * 100, color="#d73027", lw=2, label="Lorenz curve (calibrated)")
    ax.plot([0, 100], [0, 100], "--", color="gray", lw=1, label="Perfect equality")
    ax.fill_between(lz["cum_pop_share"] * 100, lz["cum_time_share"] * 100, lz["cum_pop_share"] * 100, color="#d73027", alpha=0.15)
    ax.set_xlabel("Cumulative population share (%, sorted by access time)")
    ax.set_ylabel("Cumulative access-time share (%)")
    ax.set_title(f"Lorenz curve of car access time\nGini = {gini:.3f}")
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig3_lorenz_curve.pdf")
    plt.close(fig)


def figure_urban_rural(d: dict) -> None:
    ur = d["urban_rural"]
    ur = ur[ur["urban_rural"].isin(["urban", "rural"])]
    bands = [("pct_le_30", "$\\leq$30"), ("pct_30_60", "30--60"), ("pct_60_120", "60--120"), ("pct_gt_120", "$>$120")]
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    x = np.arange(len(ur))
    bottom = np.zeros(len(ur))
    colors = ["#1a9850", "#91cf60", "#fee08b", "#d73027"]
    for (col, label), color in zip(bands, colors):
        vals = ur[col].values
        ax.bar(x, vals, bottom=bottom, label=f"{label} min", color=color, width=0.5)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels([u.title() for u in ur["urban_rural"]])
    ax.set_ylabel("% of routed population")
    ax.set_title("Coverage bands by urban/rural classification\n(among population with an estimable route)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=4, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig4_urban_rural.pdf")
    plt.close(fig)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    TAB_DIR.mkdir(parents=True, exist_ok=True)

    print("Cargando outputs...")
    d = load_all()

    print("Escribiendo macros -> report/generated/metrics.tex")
    (GEN / "metrics.tex").write_text(build_macros(d), encoding="utf-8")

    print("Escribiendo tablas...")
    (TAB_DIR / "data_sources.tex").write_text(table_data_sources(), encoding="utf-8")
    (TAB_DIR / "access_by_department.tex").write_text(table_access_by_department(d), encoding="utf-8")
    (TAB_DIR / "worst_districts.tex").write_text(table_worst_districts(d), encoding="utf-8")
    (TAB_DIR / "data_quality.tex").write_text(table_data_quality(d), encoding="utf-8")

    print("Generando figuras...")
    figure_coverage_by_department(d)
    figure_choropleth(d)
    figure_lorenz(d)
    figure_urban_rural(d)

    print("OK.")


if __name__ == "__main__":
    main()
