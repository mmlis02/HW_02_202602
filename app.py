"""Dashboard Streamlit — Fase 4.

Acceso a atención resolutiva de emergencia — Tumbes, Amazonas, Cusco.

Consume EXCLUSIVAMENTE outputs precomputados de `data/processed/` y
`data/outputs/` (Fases 1-3 + `scripts/precompute_dashboard_outputs.py`).
No llama routing, no abre el PBF, no reconstruye grafos, no recalcula
matrices ni pesos estadísticos — ver `src/dashboard/` para la lógica
reutilizable (sin Streamlit, testeada en `tests/test_dashboard_*.py`).

Ejecutar:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import metrics as m
from src.dashboard import charts, data, filters, kpis, maps, quality
from src.dashboard.filters import TODOS
from src.dashboard.scenario import baseline_vs_scenario_summary, rank_candidates

st.set_page_config(page_title="Acceso a Salud Resolutiva — TAC", layout="wide", page_icon="🚑")

# Límite de establecimientos a embeber en el mapa principal (ver corrección
# 2026-09-12, docstring en el bloque "Mapa de acceso por distrito" más abajo):
# por encima de este umbral el payload del MarkerCluster puede volver a
# impedir el render (medido: Cusco con 1582 facilities ≈ +910 KB / +127%
# sobre el choropleth solo). 800 es un margen conservador frente al caso
# real que sí renderizaba (Amazonas, 791 facilities, ~991 KB totales).
MAX_FACILITIES_MAIN_MAP = 800

_APP_START = time.time()

# --------------------------------------------------------------------------
# Carga (cacheada) — ver src/dashboard/data.py
# --------------------------------------------------------------------------
da = data.load_demand_analysis()
district_metrics = data.load_district_metrics()
district_geom = data.load_district_geometries()
facilities = data.load_facilities()
worst_computable = data.load_worst_computable_districts()
insufficient = data.load_districts_with_insufficient_data()
urban_rural = data.load_urban_rural_summary()
phase3_summary = data.load_phase3_summary()
candidate_scores_all = data.load_candidate_scores()

_LOAD_TIME = time.time() - _APP_START

st.title("🚑 Acceso a atención resolutiva de emergencia")
st.caption("Tumbes · Amazonas · Cusco — tiempo en automóvil al establecimiento resolutivo más cercano (Censo 2017, pesos calibrados)")

# --------------------------------------------------------------------------
# Sidebar — filtros
# --------------------------------------------------------------------------
st.sidebar.header("Filtros geográficos")
dep_options = filters.options_with_todos(da["DEP"].unique().tolist())
sel_dep = st.sidebar.multiselect("Departamento", dep_options, default=[TODOS])

prov_options = filters.get_provinces_for_departments(da, sel_dep)
sel_prov = st.sidebar.multiselect("Provincia", prov_options, default=[TODOS])

dist_options = filters.get_districts_for(da, sel_dep, sel_prov)
sel_dist = st.sidebar.multiselect("Distrito", dist_options, default=[TODOS], help="209 distritos en total — usa Provincia para acotar la lista.")

st.sidebar.header("Filtros de establecimientos")
cat_options = filters.options_with_todos(facilities["CATEGORIA_NORM"].dropna().unique().tolist())
sel_cat = st.sidebar.multiselect("Categoría", cat_options, default=[TODOS])
inst_options = filters.options_with_todos(facilities["INSTITUCION"].dropna().unique().tolist())
sel_inst = st.sidebar.multiselect("Institución", inst_options, default=[TODOS])
sel_resolutive = st.sidebar.radio("Tipo de establecimiento", [TODOS, "Solo resolutivos", "Solo no resolutivos"])

st.sidebar.header("Umbral de tiempo")
threshold = st.sidebar.slider("Umbral para KPIs (min)", min_value=15, max_value=180, value=60, step=15)

st.sidebar.caption(f"⏱ Carga inicial (cache): {_LOAD_TIME:.2f}s")

# --------------------------------------------------------------------------
# Aplicar filtros (NUNCA recalibra pesos — solo selecciona un subconjunto)
# --------------------------------------------------------------------------
da_f = filters.apply_geographic_filter(da, departments=sel_dep, provinces=sel_prov, districts=sel_dist)
dm_f = filters.apply_geographic_filter(district_metrics, departments=sel_dep, provinces=sel_prov, districts=sel_dist)
worst_f = filters.apply_geographic_filter(worst_computable, departments=sel_dep, provinces=sel_prov, districts=sel_dist)
insufficient_f = filters.apply_geographic_filter(insufficient, departments=sel_dep, provinces=sel_prov, districts=sel_dist)

fac_f = filters.apply_geographic_filter(facilities, departments=sel_dep, provinces=sel_prov, districts=sel_dist, dep_col="DEPARTAMENTO", prov_col="PROVINCIA", dist_col="DISTRITO")
fac_f = filters.apply_facility_filters(fac_f, categories=sel_cat, institutions=sel_inst, resolutive_only=sel_resolutive)


def _no_data_message() -> None:
    st.info("No hay datos disponibles para esta selección.")


_map_key = filters.map_component_key  # ver src/dashboard/filters.py (testeado en tests/test_dashboard_filters.py)


tab1, tab_fac, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Panorama de acceso", "🏥 Establecimientos", "🗺️ Brechas territoriales", "🏘️ Urbano vs rural",
    "🔧 Simulador de upgrade", "🔍 Calidad y metodología",
])

# ==========================================================================
# TAB 1 — Panorama de acceso
# ==========================================================================
with tab1:
    if len(da_f) == 0:
        _no_data_message()
    else:
        header = kpis.kpi_header(da_f, worst_f, threshold_min=threshold)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Población ≤{threshold} min", f"{header['population_le_threshold']:,.0f}", f"{header['pct_le_threshold_of_frame']:.1f}% del frame filtrado")
        c2.metric(f"Población >{threshold} min (con ruta)", f"{header['population_gt_threshold_routed']:,.0f}", f"{header['pct_no_time_estimate_of_frame']:.1f}% adicional sin tiempo estimable", delta_color="off")
        worst = header["worst_district"]
        c3.metric("Distrito con mayor tiempo medio (computable)", worst["DIST"] if worst else "—", f"{worst['weighted_mean_access_min']:.0f} min" if worst else "sin distritos computables en el filtro")
        c4.metric("Mediana ponderada de acceso", f"{header['weighted_median_access_min']:.1f} min" if pd.notna(header["weighted_median_access_min"]) else "—", f"media: {header['weighted_mean_access_min']:.1f} min" if pd.notna(header["weighted_mean_access_min"]) else "")

        st.caption(
            f"Población total representada (frame U4 filtrado): **{header['total_population_frame']:,.0f}** habitantes. "
            "Los % usan siempre este denominador (nunca la población censal total sin filtrar)."
        )

        st.subheader("Cobertura poblacional por banda de tiempo")
        cov = m.compute_coverage_bands(da_f, weight_col="calibrated_weight")
        rb = cov["reading_b_cumulative"].set_index("band")["pct"]
        band_pcts = {
            "≤30 min": rb.get("<=30", 0.0),
            "30–60 min": rb.get("<=60 (cum)", 0.0) - rb.get("<=30", 0.0),
            "60–120 min": rb.get("<=120 (cum)", 0.0) - rb.get("<=60 (cum)", 0.0),
            ">120 min": rb.get(">120", 0.0),
            "Sin tiempo estimable": rb.get("sin_tiempo_estimable", 0.0),
        }
        st.plotly_chart(charts.coverage_bands_figure(band_pcts), width="stretch")
        with st.expander("Ver también: cobertura solo entre población con tiempo estimable (Reading A)"):
            ra = cov["reading_a_sobre_poblacion_con_tiempo_estimable"].set_index("band")["pct"]
            st.write({k: f"{v:.1f}%" for k, v in ra.to_dict().items()})
            st.caption("Estos % suman 100% de la población RUTEADA únicamente — no del frame completo.")

        st.subheader("Mapa de acceso por distrito")
        # Corrección 2026-09-12 (mapa no renderizaba para Cusco/Todos): la capa de
        # establecimientos, aunque oculta (`show=False`), se seguía CONSTRUYENDO y
        # embebiendo por completo en el HTML del mapa (cientos/miles de CircleMarker
        # dentro de MarkerCluster) -- "oculto" en Leaflet no significa "no se envía".
        # Medido: geometría+choropleth+leyenda de Cusco (112 distritos) = ~719 KB;
        # añadir la capa de establecimientos (aun oculta) la lleva a ~1.63 MB (+127%,
        # 1582 facilities) -- Amazonas con menos facilities (791) se queda en ~991 KB
        # y sí renderizaba. La solución NO es tocar el clustering ni los filtros:
        # es no construir esa capa en absoluto en este mapa salvo que el usuario la
        # pida explícitamente (los establecimientos ya tienen su propia pestaña).
        show_facilities_here = st.checkbox(
            "Mostrar establecimientos sobre este mapa (puede tardar más en departamentos con muchos establecimientos)",
            value=False, key="show_facilities_main_map",
        )
        fmap = maps.build_choropleth_map(district_geom, dm_f)
        if fmap is None:
            _no_data_message()
        else:
            # Guard adicional (2026-09-12): incluso con el checkbox activado, un
            # departamento con demasiados establecimientos (p.ej. Cusco/Todos)
            # puede volver a inflar el payload lo suficiente para repetir el bug
            # de render — se limita explícitamente en vez de confiar solo en que
            # el usuario recuerde acotar el filtro.
            if show_facilities_here:
                if len(fac_f) > MAX_FACILITIES_MAIN_MAP:
                    st.info(
                        "Hay demasiados establecimientos para mostrarlos en esta vista. "
                        "Selecciona un departamento/provincia o utiliza la pestaña "
                        "'Establecimientos'."
                    )
                else:
                    maps.add_facility_layer(fmap, fac_f, default_show=True)
            st_folium(
                fmap, key=_map_key("main_map", sel_dep, sel_prov, sel_dist, [str(show_facilities_here)]),
                use_container_width=True, height=560, returned_objects=[],
            )

# ==========================================================================
# TAB Establecimientos
# ==========================================================================
with tab_fac:
    st.subheader("Establecimientos de salud")
    st.caption("Agrupados en clusters por cercanía geográfica; se dividen automáticamente al hacer zoom. Filtra por categoría/institución/tipo desde el sidebar.")
    if len(fac_f) == 0:
        _no_data_message()
    else:
        fmap_fac = maps.build_choropleth_map(district_geom, dm_f) if len(dm_f) else None
        if fmap_fac is None:
            # Sin distritos en el filtro geográfico (pero sí facilities, p.ej. filtro solo por categoría):
            # usa el universo distrital completo únicamente para dar contexto geográfico al mapa.
            fmap_fac = maps.build_choropleth_map(district_geom, district_metrics)
        maps.add_facility_layer(fmap_fac, fac_f, default_show=True)
        st_folium(
            fmap_fac,
            key=_map_key("fac_map", sel_dep, sel_prov, sel_dist, sel_cat, sel_inst, [sel_resolutive]),
            use_container_width=True, height=560, returned_objects=[],
        )

# ==========================================================================
# TAB 2 — Brechas territoriales
# ==========================================================================
with tab2:
    st.subheader("Distribución poblacional ponderada del tiempo de acceso")
    dist_dim = st.radio("Agrupar por", ["Departamento", "Urbano/Rural"], horizontal=True, key="dist_dim")
    if len(da_f) == 0:
        _no_data_message()
    else:
        group_col = "DEP" if dist_dim == "Departamento" else "urban_rural"
        st.plotly_chart(charts.weighted_ecdf_figure(da_f, group_col=group_col), width="stretch")

    st.subheader("Ranking de distritos — peor acceso (solo distritos computables)")
    if len(worst_f) == 0:
        _no_data_message()
    else:
        display_cols = ["rank", "DEP", "PROV", "DIST", "weighted_mean_access_min", "total_estimated_population", "share_population_with_travel_time_pct", "district_status"]
        table = worst_f[[c for c in display_cols if c in worst_f.columns]].rename(columns={
            "weighted_mean_access_min": "Tiempo medio (min)", "total_estimated_population": "Población calibrada",
            "share_population_with_travel_time_pct": "% con tiempo estimable", "district_status": "Calidad",
        })
        st.dataframe(table, width="stretch", hide_index=True)
        st.download_button("⬇️ Download CSV", table.to_csv(index=False).encode("utf-8"), file_name="worst_computable_districts_filtered.csv", mime="text/csv")

    with st.expander(f"⚠️ Distritos con información insuficiente ({len(insufficient_f)}) — separados del ranking"):
        if len(insufficient_f) == 0:
            st.write("Ninguno en esta selección.")
        else:
            cols = ["DEP", "PROV", "DIST", "district_status", "n_cp", "known_population"]
            st.dataframe(insufficient_f[[c for c in cols if c in insufficient_f.columns]].rename(columns={"district_status": "Motivo"}), width="stretch", hide_index=True)
            st.caption("Estos distritos NUNCA aparecen en el ranking de \"peor acceso\" — no hay suficiente dato para compararlos, lo cual es distinto de tener buen o mal acceso.")

# ==========================================================================
# TAB 3 — Urbano vs rural
# ==========================================================================
with tab3:
    st.info("📌 Comparación descriptiva. No implica una relación causal.")
    if len(da_f) == 0:
        _no_data_message()
    else:
        ur_local = m.urban_rural_summary(da_f, weight_col="calibrated_weight")
        n_classified = int((da_f["urban_rural"] != m.UNKNOWN_RURALITY).sum())
        st.caption(f"Clasificación censal (MINAM, Censo 2017): {n_classified}/{len(da_f)} CP clasificados en esta selección. `unknown` se muestra por separado, nunca oculto.")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(charts.urban_rural_comparison_figure(ur_local), width="stretch")
        with c2:
            st.plotly_chart(charts.urban_rural_coverage_bands_figure(ur_local), width="stretch")
        st.dataframe(ur_local, width="stretch", hide_index=True)

# ==========================================================================
# TAB 4 — Simulador de upgrade
# ==========================================================================
with tab4:
    st.markdown("Selecciona uno o varios establecimientos **I-3/I-4** candidatos y simula que pasan a ser **resolutivos**.")
    st.caption("No se recalcula routing: se usa `min(tiempo actual, tiempo al candidato)` sobre matrices ya precomputadas de Fase 2.")

    if "scenario_selection" not in st.session_state:
        st.session_state["scenario_selection"] = []

    st.subheader("🏆 Candidatos con mayor ganancia potencial (precomputado)")
    rank_metric = st.selectbox("Ordenar por", ["pop_gain_le_60", "pop_gain_le_30", "pop_gain_le_120", "weighted_mean_reduction_min"], format_func=lambda x: {
        "pop_gain_le_60": "Ganancia poblacional ≤60 min", "pop_gain_le_30": "Ganancia poblacional ≤30 min",
        "pop_gain_le_120": "Ganancia poblacional ≤120 min", "weighted_mean_reduction_min": "Reducción de la media ponderada",
    }[x])
    top_candidates = rank_candidates(candidate_scores_all, by=rank_metric, top_n=15)
    st.dataframe(top_candidates[["rank", "NOMBRE", "DISTRITO", "PROVINCIA", "CATEGORIA_NORM", "pop_gain_le_30", "pop_gain_le_60", "pop_gain_le_120", "weighted_mean_reduction_min"]], width="stretch", hide_index=True)

    st.subheader("Selección manual")
    candidate_labels = candidate_scores_all.assign(label=lambda d: d["NOMBRE"].fillna("(sin nombre)") + " — " + d["DISTRITO"].fillna("") + " (" + d["facility_id"] + ")")
    label_to_id = dict(zip(candidate_labels["label"], candidate_labels["facility_id"]))

    def _reset_scenario() -> None:
        # Debe limpiarse vía on_click (ANTES de que el widget se vuelva a
        # instanciar en el rerun) -- asignar st.session_state[key] después
        # de que el widget con esa key ya se instanció en este mismo run
        # lanza StreamlitWidgetAlreadyInstantiatedError.
        st.session_state["scenario_multiselect"] = []

    col_sel, col_reset = st.columns([4, 1])
    with col_sel:
        selected_labels = st.multiselect("Establecimientos a simular como resolutivos", candidate_labels["label"].tolist(), key="scenario_multiselect")
    with col_reset:
        st.write("")
        st.button("🔄 Reset scenario", on_click=_reset_scenario)

    selected_ids = [label_to_id[label] for label in selected_labels]

    if not selected_ids:
        st.info("Sin selección — el escenario es idéntico al baseline (ganancia marginal = 0).")

    _scenario_t0 = time.time()
    upgrade_matrix = data.load_upgrade_matrix()
    result = baseline_vs_scenario_summary(da, upgrade_matrix, selected_ids)
    _scenario_time = time.time() - _scenario_t0
    st.caption(f"⏱ Cálculo del escenario: {_scenario_time:.2f}s ({len(selected_ids)} candidato(s) seleccionado(s))")

    b, s, gain = result["baseline"], result["scenario"], result["marginal_gain"]
    st.subheader("Baseline vs Escenario (universo completo, sin filtrar por sidebar)")
    bc1, bc2, bc3 = st.columns(3)
    bc1.metric("Media ponderada — baseline", f"{b['weighted_mean']:.1f} min")
    bc2.metric("Media ponderada — escenario", f"{s['weighted_mean']:.1f} min", f"-{gain['weighted_mean_reduction_min']:.1f} min" if pd.notna(gain["weighted_mean_reduction_min"]) else "—")
    bc3.metric("Población que gana ruta (antes sin tiempo estimable)", f"{gain['population_newly_routed']:,.0f}")

    comp_df = pd.DataFrame({
        "Métrica": ["Población ≤30 min", "Población ≤60 min (acum)", "Población ≤120 min (acum)", "Sin tiempo estimable"],
        "Baseline": [b["pop_le_30"], b["pop_le_60_cum"], b["pop_le_120_cum"], b["pop_no_time_estimate"]],
        "Escenario": [s["pop_le_30"], s["pop_le_60_cum"], s["pop_le_120_cum"], s["pop_no_time_estimate"]],
    })
    comp_df["Ganancia marginal"] = comp_df["Escenario"] - comp_df["Baseline"]
    st.dataframe(comp_df.style.format({"Baseline": "{:,.0f}", "Escenario": "{:,.0f}", "Ganancia marginal": "{:+,.0f}"}), width="stretch", hide_index=True)

    if selected_ids:
        st.subheader("Distritos que más mejoran con este escenario")
        da_idx = da.set_index("demand_id")
        from src.dashboard.scenario import compute_scenario_time
        scen_time = compute_scenario_time(da_idx["t_min"], upgrade_matrix, selected_ids)
        tmp = da[["demand_id", "DEP", "PROV", "DIST", "t_min", "calibrated_weight"]].copy()
        tmp["scenario_t_min"] = tmp["demand_id"].map(scen_time)
        by_dist_before = m.weighted_mean_access(tmp, ["DEP", "PROV", "DIST"], time_col="t_min", weight_col="calibrated_weight", population_col="calibrated_weight")
        by_dist_after = m.weighted_mean_access(tmp, ["DEP", "PROV", "DIST"], time_col="scenario_t_min", weight_col="calibrated_weight", population_col="calibrated_weight")
        improve = by_dist_before.merge(by_dist_after, on=["DEP", "PROV", "DIST"], suffixes=("_antes", "_despues"))
        improve["mejora_min"] = improve["weighted_mean_access_min_antes"] - improve["weighted_mean_access_min_despues"]
        improve = improve[improve["mejora_min"] > 0].sort_values("mejora_min", ascending=False).head(10)
        if len(improve):
            st.dataframe(improve[["DEP", "PROV", "DIST", "weighted_mean_access_min_antes", "weighted_mean_access_min_despues", "mejora_min"]], width="stretch", hide_index=True)
        else:
            st.write("Ningún distrito computable mejora de forma medible con esta selección.")

        st.subheader("Ubicación de los candidatos seleccionados")
        fmap_scenario = maps.build_choropleth_map(district_geom, district_metrics)
        if fmap_scenario is None:
            _no_data_message()
        else:
            maps.add_facility_layer(fmap_scenario, facilities[facilities["COD_IPRESS"].isin(selected_ids)], highlight_ids=set(selected_ids), default_show=True)
            st_folium(fmap_scenario, key=_map_key("scenario_map", sorted(selected_ids)), use_container_width=True, height=420, returned_objects=[])

# ==========================================================================
# TAB 5 — Calidad y metodología
# ==========================================================================
with tab5:
    st.subheader("Calidad de datos")
    dqr = data.load_data_quality_report()
    rqr = data.load_routing_quality_report()
    weight_diag = data.load_weight_diagnostics()
    weight_calib = data.load_weight_calibration_by_district()

    with st.expander("📋 Establecimientos (Fase 1)"):
        st.dataframe(quality.summarize_facility_quality(dqr), width="stretch", hide_index=True)

    with st.expander("🛣️ Routing (Fase 2)"):
        rq = quality.summarize_routing_quality(rqr)
        c1, c2, c3 = st.columns(3)
        c1.metric("Snap fallido (auto)", f"{rq['car_snap_failed']:,} ({rq['car_snap_failed_pct']:.1f}%)")
        c2.metric("Sin ruta en su departamento", f"{rq['car_no_route_same_department']:,} ({rq['car_no_route_same_department_pct']:.1f}%)")
        c3.metric("Pares cross-departamento no evaluados", f"{rq['car_matrix_cross_department_not_evaluated_pct']:.1f}%")
        st.caption(f"Supuesto de velocidad en vías `track`: {rq['car_track_fallback_speed_kmh']} km/h (no observado, decisión metodológica) — recuperó ruta a resolutiva para {rq['car_track_recovers_route_to_resolutive']} puntos.")

    with st.expander("👥 Población (Fase 3)"):
        pq = quality.summarize_population_quality(phase3_summary, weight_calib)
        c1, c2, c3 = st.columns(3)
        c1.metric("Población censal (U2, 3 departamentos)", f"{pq['u2_total_population']:,.0f}")
        c2.metric("Cubierta por frame SIGMED (U4)", f"{pq['frame_coverage_u4_over_u2_pct']:.2f}%")
        c3.metric("Fuera del frame SIGMED", f"{pq['outside_sigmed_frame_population']:,.0f}")
        st.caption(f"{pq['n_districts_calibration_impossible']} distrito(s) sin calibración posible (sin muestra con población), afectando {pq['population_calibration_impossible']:,.0f} habitantes — ver panel de limitaciones.")

    with st.expander("📐 Estadística (calibración de pesos)"):
        sq = quality.summarize_statistical_quality(phase3_summary, weight_diag, weight_calib)
        c1, c2 = st.columns(2)
        c1.metric("Media ponderada — HT sin calibrar", f"{sq['weighted_mean_access_min_ht']:.1f} min")
        c2.metric("Media ponderada — calibrado (usado en el dashboard)", f"{sq['weighted_mean_access_min_calibrated']:.1f} min")
        st.caption(f"Gini calibrado: {sq['weighted_gini_access']:.3f} ({sq['gini_pct_population_excluded']:.1f}% de población sin tiempo estimable, excluida del cálculo). n_eff total: HT={sq['n_eff_total_ht']:.1f} → calibrado={sq['n_eff_total_calibrated']:.1f}. Factores de calibración extremos: {sq['n_districts_extreme_calibration_factor_low']} distritos <0.5×, {sq['n_districts_extreme_calibration_factor_high']} distritos >2.0× (diagnóstico, ningún distrito se excluye por esto).")

    st.subheader("⚠️ Limitaciones")
    st.markdown("""
- Base poblacional: **Censo 2017 INEI** (vía CENEPRED, validado cruzadamente con MINAM) — no incluye crecimiento poblacional posterior a 2017.
- Cobertura de OSM en zonas rurales de sierra/selva alta puede ser incompleta; algunas vías rurales están mapeadas como `track` con velocidad **modelada, no observada** (12 km/h).
- Los establecimientos vienen de **RENIPRESS** — estar activo/resolutivo en el registro **no garantiza** personal, equipamiento o insumos operativos reales el día de una emergencia.
- No se modela disponibilidad de ambulancias ni tiempo de traslado puerta-a-puerta real.
- El routing **no evalúa rutas cross-departamento** (arquitectura de grafos separados por departamento — auditoría demostró que esto no cambia el resolutivo más cercano de ningún punto ya ruteado).
- La calibración de pesos por distrito tiene **factores extremos** en estratos con muestra muy pequeña (hasta 177×) — diagnóstico, no corregido.
- **2 distritos** (Wanchaq, Luya Viejo) no tienen calibración posible — 0 CP de la muestra con población válida, pese a tener población censal conocida.
- **0.49%** de la población censal (U2−U4, ~8,915 personas) queda fuera del frame SIGMED — nunca redistribuida a otros CP.
- Una parte adicional de la población del frame (U4) no tiene tiempo estimable por `snap_failed`/`no_route_same_department` — ver bandas "sin tiempo estimable" en cada vista.
    """)

    st.subheader("📖 Metodología")
    with st.expander("Ver definiciones"):
        st.markdown("""
**Establecimiento resolutivo**: activo (`ESTADO=ACTIVO`) y categoría en {II-1, II-2, II-E, III-1, III-2, III-E}.

**Tiempo de acceso**: tiempo de viaje en auto por la red vial (OSM) al establecimiento resolutivo más cercano — precomputado (Fase 2), nunca recalculado por este dashboard.

**Población**: Censo Nacional 2017 (INEI), obtenida vía el servicio CENEPRED/SIGRID, validada cruzadamente al 100% contra MINAM Geoservidor (12,312 registros comparables, población idéntica).

**Pesos**: `design_weight` (diseño muestral estratificado) combinado con `population` (Censo 2017) para obtener un peso Horvitz-Thompson, luego **calibrado por distrito** contra la población censal real conocida (`calibrated_weight` — el peso usado por defecto en todo este dashboard).

**Routing**: grafo vial NetworkX construido desde extractos OSM/Geofabrik por departamento — todo precomputado en Fase 2, este dashboard solo lee los resultados.
        """)

st.sidebar.caption(f"⏱ Tiempo total de renderizado: {time.time() - _APP_START:.2f}s")
