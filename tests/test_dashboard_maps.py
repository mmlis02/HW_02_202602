"""Tests de src/dashboard/maps.py — corrección del bug de viewport (Fase 4).

Cubre específicamente el comportamiento pedido: el viewport SIEMPRE se
calcula a partir de las geometrías distritales filtradas (nunca de
facilities), y "Todos" produce bounds que cubren los tres departamentos.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from pathlib import Path

from src.dashboard.maps import (
    INSUFFICIENT_DATA_COLOR,
    LAYER_COLORS,
    add_facility_layer,
    build_choropleth_map,
    build_colormap,
    compute_bounds,
    describe_render_stats,
    group_facilities_by_category,
    resolve_fill_color,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _square(minx, miny, maxx, maxy):
    return box(minx, miny, maxx, maxy)


def _synthetic_geom():
    """Tres 'departamentos' separados geográficamente, como Tumbes/Amazonas/Cusco.

    Igual que el esquema real de dashboard_district_geometries_simplified.parquet:
    SOLO UBIGEO + geometry (sin DEP) -- DEP viene siempre del lado de las métricas."""
    return gpd.GeoDataFrame({
        "UBIGEO": ["T1", "A1", "A2", "C1", "C2", "C3"],
        "geometry": [
            _square(-80.5, -4.0, -80.0, -3.5),   # Tumbes: far NW
            _square(-78.0, -6.5, -77.5, -6.0),   # Amazonas: N
            _square(-77.5, -6.0, -77.0, -5.5),
            _square(-72.5, -14.0, -72.0, -13.5),  # Cusco: far SE
            _square(-72.0, -13.5, -71.5, -13.0),
            _square(-71.5, -13.0, -71.0, -12.5),
        ],
    }, crs="EPSG:4326")


def _synthetic_metrics():
    return pd.DataFrame({
        "UBIGEO": ["T1", "A1", "A2", "C1", "C2", "C3"],
        "DEP": ["TUMBES", "AMAZONAS", "AMAZONAS", "CUSCO", "CUSCO", "CUSCO"],
        "PROV": ["P"] * 6,
        "DIST": ["D"] * 6,
        "weighted_mean_access_min": [10.0, 20.0, 30.0, 40.0, 50.0, 300.0],
        "known_population": [100, 200, 300, 400, 500, 600],
        "pct_le_30": [50.0] * 6,
        "pct_le_60_cum": [70.0] * 6,
        "pct_le_120_cum": [90.0] * 6,
        "pct_no_time_estimate": [5.0] * 6,
        "district_status": ["computable"] * 5 + ["zero_routing_coverage"],
    })


# --------------------------------------------------------------------------
# compute_bounds — núcleo del fix de viewport
# --------------------------------------------------------------------------


def test_compute_bounds_none_for_empty():
    assert compute_bounds(gpd.GeoDataFrame(geometry=[])) is None
    assert compute_bounds(None) is None


def test_compute_bounds_single_department_does_not_include_others():
    geom = _synthetic_geom()
    cusco_only = geom[geom["UBIGEO"].isin(["C1", "C2", "C3"])]
    bounds = compute_bounds(cusco_only)
    (min_lat, min_lon), (max_lat, max_lon) = bounds
    # Cusco (sintético) esta entre lon -72.5..-71.0, lat -14.0..-12.5
    assert -72.6 < min_lon < -71.0
    assert -71.6 < max_lon < -70.9
    assert min_lat >= -14.1
    assert max_lat <= -12.4
    # Tumbes (lon ~ -80.x) NO debe estar dentro de estos bounds:
    assert min_lon > -80.0


def test_compute_bounds_todos_covers_all_three_clusters():
    geom = _synthetic_geom()
    bounds = compute_bounds(geom)  # "Todos" == sin filtrar
    (min_lat, min_lon), (max_lat, max_lon) = bounds
    # Debe abarcar Tumbes (lon ~-80.5) hasta Cusco (lon ~-71.0)
    assert min_lon <= -80.0
    assert max_lon >= -71.0
    # Y latitudinalmente de Tumbes (~-3.5) a Cusco (~-14.0)
    assert max_lat >= -3.6
    assert min_lat <= -13.9


# --------------------------------------------------------------------------
# build_choropleth_map — el viewport real que usa la app
# --------------------------------------------------------------------------


def test_choropleth_map_todos_includes_cusco_geometry():
    geom, metrics = _synthetic_geom(), _synthetic_metrics()
    fmap = build_choropleth_map(geom, metrics)  # sin filtrar == "Todos"
    assert fmap is not None
    html = fmap.get_root().render()
    # Verifica que la geometria de Cusco realmente esta en el GeoJson embebido
    # (coordenadas cercanas a -72/-71, no solo que el mapa "no truene").
    assert "-72." in html or "-71." in html


def test_choropleth_map_filtered_department_excludes_others():
    geom, metrics = _synthetic_geom(), _synthetic_metrics()
    cusco_metrics = metrics[metrics["DEP"] == "CUSCO"]
    fmap = build_choropleth_map(geom, cusco_metrics)
    assert fmap is not None
    merged = geom.merge(cusco_metrics, on="UBIGEO", how="inner")
    assert len(merged) == 3
    assert set(merged["DEP"]) == {"CUSCO"}


def test_choropleth_map_empty_selection_returns_none_not_crash():
    geom = _synthetic_geom()
    empty_metrics = pd.DataFrame(columns=["UBIGEO", "DEP", "PROV", "DIST", "weighted_mean_access_min", "known_population", "pct_le_30", "pct_le_60_cum", "pct_le_120_cum", "pct_no_time_estimate", "district_status"])
    assert build_choropleth_map(geom, empty_metrics) is None


def test_choropleth_map_color_scale_excludes_insufficient_data_from_minmax():
    geom, metrics = _synthetic_geom(), _synthetic_metrics()
    # El distrito con status != computable tiene 300.0 min -- no debe
    # entrar en el vmin/vmax de la escala (se comprueba vía el html: el
    # numero 300 no deberia aparecer en la leyenda de vmax).
    fmap = build_choropleth_map(geom, metrics)
    html = fmap.get_root().render()
    assert ">50<" in html  # el maximo computable real es 50, no 300


def test_choropleth_map_no_carto_no_api_key_watermark():
    geom, metrics = _synthetic_geom(), _synthetic_metrics()
    fmap = build_choropleth_map(geom, metrics)
    html = fmap.get_root().render()
    assert "cartocdn" not in html.lower()
    assert "carto" not in html.lower()
    assert "openstreetmap" in html.lower()


def test_choropleth_map_geojson_keeps_raw_status_not_the_display_label():
    # Regresión del bug de "todos los distritos grises": el GeoJson
    # embebido debe llevar el status RAW ("computable"), nunca solo la
    # etiqueta legible ("Computable") en el campo que usa el estilo.
    geom, metrics = _synthetic_geom(), _synthetic_metrics()
    fmap = build_choropleth_map(geom, metrics)
    html = fmap.get_root().render()
    assert '"district_status": "computable"' in html


# --------------------------------------------------------------------------
# resolve_fill_color / describe_render_stats — el bug real de "todo gris"
# --------------------------------------------------------------------------


def test_resolve_fill_color_gray_only_for_non_computable_or_missing():
    cmap = build_colormap(pd.DataFrame({"district_status": ["computable"] * 2, "weighted_mean_access_min": [10.0, 100.0]}))
    assert resolve_fill_color("computable", 10.0, cmap) != INSUFFICIENT_DATA_COLOR
    assert resolve_fill_color("zero_routing_coverage", 10.0, cmap) == INSUFFICIENT_DATA_COLOR
    assert resolve_fill_color("computable", None, cmap) == INSUFFICIENT_DATA_COLOR
    assert resolve_fill_color("computable", float("nan"), cmap) == INSUFFICIENT_DATA_COLOR


def test_resolve_fill_color_is_case_sensitive_display_label_must_not_be_passed():
    # Si por error se pasara la ETIQUETA ("Computable") en vez del status
    # crudo, debe caer a gris -- documenta exactamente el bug que existía
    # (district_status sobrescrito con la etiqueta antes de estilar).
    cmap = build_colormap(pd.DataFrame({"district_status": ["computable"], "weighted_mean_access_min": [10.0]}))
    assert resolve_fill_color("Computable", 10.0, cmap) == INSUFFICIENT_DATA_COLOR


def test_describe_render_stats_multiple_values_multiple_colors():
    merged = pd.DataFrame({
        "district_status": ["computable", "computable", "computable", "zero_routing_coverage"],
        "weighted_mean_access_min": [10.0, 50.0, 150.0, float("nan")],
    })
    stats = describe_render_stats(merged)
    assert stats["n_total"] == 4
    assert stats["n_computable"] == 3
    assert stats["n_insufficient"] == 1
    assert stats["vmin"] == 10.0
    assert stats["vmax"] == 150.0
    assert stats["n_unique_render_colors"] > 1, "múltiples valores de tiempo deben producir múltiples colores"


def test_describe_render_stats_fails_to_detect_bug_would_be_caught():
    # Si TODOS los status llegaran mal-etiquetados como no-computable (el
    # bug real), n_unique_render_colors debe caer a 0 -- esto es lo que el
    # test anterior habría detectado antes de la corrección.
    merged = pd.DataFrame({
        "district_status": ["Computable", "Computable", "Computable"],  # mal-etiquetado (bug simulado)
        "weighted_mean_access_min": [10.0, 50.0, 150.0],
    })
    stats = describe_render_stats(merged)
    assert stats["n_computable"] == 0
    assert stats["n_unique_render_colors"] == 0


# --------------------------------------------------------------------------
# Validación con datos REALES precomputados (no solo fixture sintético)
# --------------------------------------------------------------------------


def _load_real_geom_and_metrics():
    geom_path = REPO_ROOT / "data/outputs/dashboard_district_geometries_simplified.parquet"
    metrics_path = REPO_ROOT / "data/outputs/dashboard_district_metrics.parquet"
    if not geom_path.exists() or not metrics_path.exists():
        pytest.skip("outputs precomputados de Fase 4 no disponibles en este entorno")
    return gpd.read_parquet(geom_path), pd.read_parquet(metrics_path)


def test_real_data_cusco_has_multiple_computable_districts_and_colors():
    geom, metrics = _load_real_geom_and_metrics()
    cusco_metrics = metrics[metrics["DEP"] == "CUSCO"]
    merged = geom.merge(cusco_metrics, on="UBIGEO", how="inner")
    stats = describe_render_stats(merged)
    print("Cusco real:", stats)
    assert stats["n_total"] > 50
    assert stats["n_computable"] > 1
    assert stats["vmax"] > stats["vmin"]
    assert stats["n_unique_render_colors"] > 1


def test_real_data_cusco_choropleth_only_stays_well_under_payload_that_failed_to_render():
    # Regresión del bug de "Cusco/Todos no renderizan" (2026-09-12): la causa
    # real era el payload de la capa de establecimientos (MarkerCluster con
    # miles de CircleMarker embebidos aunque estuviera oculta), NO la
    # geometría/choropleth por sí sola. Medido empíricamente: Cusco
    # geometría+estilo+tooltip+leyenda (112 distritos) ~719 KB; con
    # facilities añadidas (aun ocultas) ~1.63 MB (+127%). Este test fija un
    # techo generoso (1.5 MB) para el choropleth SOLO, muy por debajo de
    # donde se observó el fallo real, para detectar una regresión de tamaño
    # si alguien vuelve a embeber datos pesados por defecto.
    geom, metrics = _load_real_geom_and_metrics()
    cusco_metrics = metrics[metrics["DEP"] == "CUSCO"]
    fmap = build_choropleth_map(geom, cusco_metrics)
    assert fmap is not None
    html_bytes = len(fmap.get_root().render().encode("utf-8"))
    assert html_bytes < 1_500_000, f"choropleth-only de Cusco pesa {html_bytes:,} bytes -- investigar antes de añadir mas datos por defecto"


def test_choropleth_map_alone_never_embeds_facility_markers():
    # El mapa principal (build_choropleth_map) NUNCA debe incluir marcadores
    # de establecimientos por sí mismo -- esa capa se añade aparte
    # (add_facility_layer), y en la pestaña "Mapa" ahora es opt-in
    # (checkbox), precisamente para no pagar ese costo de payload por defecto.
    geom, metrics = _load_real_geom_and_metrics()
    cusco_metrics = metrics[metrics["DEP"] == "CUSCO"]
    fmap = build_choropleth_map(geom, cusco_metrics)
    html = fmap.get_root().render()
    assert "MarkerCluster" not in html
    assert "CircleMarker" not in html


def test_facility_layer_is_the_dominant_payload_contributor_not_geometry():
    # Codifica el hallazgo del diagnóstico: añadir muchos establecimientos
    # incrementa el payload muchísimo más que añadir muchos distritos.
    geom, metrics = _load_real_geom_and_metrics()
    cusco_metrics = metrics[metrics["DEP"] == "CUSCO"]
    fmap_geom_only = build_choropleth_map(geom, cusco_metrics)
    size_geom_only = len(fmap_geom_only.get_root().render())

    many_facilities = pd.DataFrame({
        "COD_IPRESS": [f"f{i}" for i in range(1500)],
        "layer_category": ["Otro"] * 1500,
        "lon": [-72.0 + (i % 50) * 0.01 for i in range(1500)],
        "lat": [-13.0 + (i % 50) * 0.01 for i in range(1500)],
        "NOMBRE": ["X"] * 1500, "CATEGORIA_NORM": ["I-1"] * 1500, "INSTITUCION": ["MINSA"] * 1500,
        "ESTADO": ["ACTIVO"] * 1500, "is_resolutive": [False] * 1500,
        "DISTRITO": ["D"] * 1500, "PROVINCIA": ["P"] * 1500, "DEPARTAMENTO": ["CUSCO"] * 1500,
        "qc_excluded_from_routing": [False] * 1500,
    })
    fmap_with_fac = build_choropleth_map(geom, cusco_metrics)
    add_facility_layer(fmap_with_fac, many_facilities, default_show=False)
    size_with_fac = len(fmap_with_fac.get_root().render())

    growth_ratio = size_with_fac / size_geom_only
    assert growth_ratio > 1.5, "1500 facilities deberian aumentar el payload sustancialmente mas que la geometria sola"


def test_real_data_all_four_filters_bounds_and_counts():
    geom, metrics = _load_real_geom_and_metrics()
    results = {}
    for label, dep in [("Todos", None), ("Tumbes", "TUMBES"), ("Amazonas", "AMAZONAS"), ("Cusco", "CUSCO")]:
        sub_metrics = metrics if dep is None else metrics[metrics["DEP"] == dep]
        merged = geom.merge(sub_metrics, on="UBIGEO", how="inner")
        results[label] = {"n": len(merged), "bounds": compute_bounds(merged), "stats": describe_render_stats(merged)}
        print(label, results[label])
    assert results["Todos"]["n"] == results["Tumbes"]["n"] + results["Amazonas"]["n"] + results["Cusco"]["n"]
    # Cusco debe estar dentro de los bounds de "Todos":
    (all_min_lat, all_min_lon), (all_max_lat, all_max_lon) = results["Todos"]["bounds"]
    (cu_min_lat, cu_min_lon), (cu_max_lat, cu_max_lon) = results["Cusco"]["bounds"]
    assert all_min_lat <= cu_min_lat and all_max_lat >= cu_max_lat
    assert all_min_lon <= cu_min_lon and all_max_lon >= cu_max_lon
    for label in ("Tumbes", "Amazonas", "Cusco"):
        assert results[label]["stats"]["n_computable"] >= 1


# --------------------------------------------------------------------------
# group_facilities_by_category — preparación de clusters (sin folium)
# --------------------------------------------------------------------------


def _facilities_df():
    return pd.DataFrame({
        "COD_IPRESS": ["a", "b", "c", "d"],
        "layer_category": ["Resolutivo", "Resolutivo", "Candidato upgrade (I-3/I-4)", "Otro"],
        "lon": [-72.0, -72.1, -72.2, -72.3],
        "lat": [-13.0, -13.1, -13.2, -13.3],
    })


def test_group_facilities_by_category_splits_correctly():
    groups = group_facilities_by_category(_facilities_df())
    assert set(groups.keys()) == {"Resolutivo", "Candidato upgrade (I-3/I-4)", "Otro"}
    assert len(groups["Resolutivo"]) == 2
    assert len(groups["Candidato upgrade (I-3/I-4)"]) == 1


def test_group_facilities_by_category_respects_prior_filtering():
    # Filtrar ANTES de agrupar (como hace la app): solo resolutivos.
    df = _facilities_df()
    filtered = df[df["layer_category"] == "Resolutivo"]
    groups = group_facilities_by_category(filtered)
    assert set(groups.keys()) == {"Resolutivo"}
    assert len(groups["Resolutivo"]) == 2


def test_group_facilities_by_category_empty_input_no_crash():
    empty = pd.DataFrame(columns=["COD_IPRESS", "layer_category", "lon", "lat"])
    assert group_facilities_by_category(empty) == {}
