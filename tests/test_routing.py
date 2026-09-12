"""Tests del módulo de routing (Fase 2) — todo sintético, sin el PBF real."""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from src.routing import compare as cmp
from src.routing import matrix as mtx
from src.routing import profiles as prof
from src.routing import snapping as snap
from src.routing import status as st
from src.routing.graph_build import build_graph
from src.routing.osm_extract import merge_department_networks


# ------------------------------------------------------------- perfiles ---
class TestCarProfile:
    def test_motorway_no_maxspeed_uses_fallback(self):
        w = prof.car_edge_weight({"highway": "motorway"}, 1000)
        assert w.speed_kmh == 100

    def test_maxspeed_overrides_fallback(self):
        w = prof.car_edge_weight({"highway": "residential", "maxspeed": "50"}, 1000)
        assert w.speed_kmh == 50

    def test_excludes_footway(self):
        assert prof.car_edge_weight({"highway": "footway"}, 100) is None

    def test_excludes_no_access(self):
        assert prof.car_edge_weight({"highway": "residential", "access": "no"}, 100) is None

    def test_oneway_yes_is_forward_only(self):
        w = prof.car_edge_weight({"highway": "primary", "oneway": "yes"}, 100)
        assert w.forward and not w.backward

    def test_oneway_minus1_is_backward_only(self):
        w = prof.car_edge_weight({"highway": "primary", "oneway": "-1"}, 100)
        assert w.backward and not w.forward

    def test_no_oneway_is_bidirectional(self):
        w = prof.car_edge_weight({"highway": "residential"}, 100)
        assert w.forward and w.backward

    def test_roundabout_implies_oneway(self):
        w = prof.car_edge_weight({"highway": "residential", "junction": "roundabout"}, 100)
        assert w.forward and not w.backward

    # --- corrección de auditoría (2026-09-11): track habilitado en car ----
    def test_track_now_enabled_with_default_fallback(self):
        w = prof.car_edge_weight({"highway": "track"}, 1000)
        assert w is not None
        assert w.speed_kmh == prof.CAR_TRACK_FALLBACK_SPEED_KMH_DEFAULT

    def test_track_fallback_speed_is_configurable(self):
        w = prof.car_edge_weight({"highway": "track"}, 1000, track_fallback_speed_kmh=7.0)
        assert w.speed_kmh == 7.0

    def test_track_respects_valid_maxspeed_over_fallback(self):
        w = prof.car_edge_weight({"highway": "track", "maxspeed": "30"}, 1000, track_fallback_speed_kmh=12.0)
        assert w.speed_kmh == 30.0  # maxspeed real manda, no el fallback

    def test_path_still_excluded_from_car(self):
        assert prof.car_edge_weight({"highway": "path"}, 100) is None

    def test_footway_pedestrian_steps_cycleway_still_excluded_from_car(self):
        for hw in ("footway", "pedestrian", "steps", "cycleway"):
            assert prof.car_edge_weight({"highway": hw}, 100) is None

    def test_make_edge_weight_fn_reads_track_speed_from_cfg(self):
        fn = prof.make_edge_weight_fn("car", {"routing": {"car_track_fallback_speed_kmh": 20}})
        w = fn({"highway": "track"}, 1000)
        assert w.speed_kmh == 20


class TestProfileHash:
    def test_hash_is_deterministic(self):
        cfg = {"routing": {"car_track_fallback_speed_kmh": 12}}
        assert prof.profile_hash("car", cfg) == prof.profile_hash("car", cfg)

    def test_hash_changes_when_track_speed_changes(self):
        h1 = prof.profile_hash("car", {"routing": {"car_track_fallback_speed_kmh": 12}})
        h2 = prof.profile_hash("car", {"routing": {"car_track_fallback_speed_kmh": 20}})
        assert h1 != h2

    def test_hash_changes_when_accessibility_rules_change(self, monkeypatch):
        cfg = {"routing": {"car_track_fallback_speed_kmh": 12}}
        h1 = prof.profile_hash("car", cfg)
        monkeypatch.setattr(prof, "CAR_EXCLUDED_HIGHWAY", prof.CAR_EXCLUDED_HIGHWAY | {"service"})
        h2 = prof.profile_hash("car", cfg)
        assert h1 != h2

    def test_hash_unaffected_by_unrelated_mode(self):
        cfg = {"routing": {"car_track_fallback_speed_kmh": 12}}
        h1 = prof.profile_hash("bike", cfg)
        cfg2 = {"routing": {"car_track_fallback_speed_kmh": 999}}  # bike no usa este parámetro
        h2 = prof.profile_hash("bike", cfg2)
        assert h1 == h2


class TestBikeProfile:
    def test_excludes_motorway_by_default(self):
        assert prof.bike_edge_weight({"highway": "motorway"}, 100) is None

    def test_motorway_allowed_if_bicycle_yes(self):
        w = prof.bike_edge_weight({"highway": "motorway", "bicycle": "yes"}, 100)
        assert w is not None

    def test_contraflow_bicycle_makes_bidirectional(self):
        w = prof.bike_edge_weight({"highway": "residential", "oneway": "yes", "oneway:bicycle": "no"}, 100)
        assert w.forward and w.backward

    def test_default_oneway_follows_car_like_rule(self):
        w = prof.bike_edge_weight({"highway": "residential", "oneway": "yes"}, 100)
        assert w.forward and not w.backward


class TestFootProfile:
    def test_ignores_vehicular_oneway(self):
        w = prof.foot_edge_weight({"highway": "residential", "oneway": "yes"}, 100)
        assert w.forward and w.backward  # regla explícita del enunciado

    def test_excludes_motorway_by_default(self):
        assert prof.foot_edge_weight({"highway": "motorway"}, 100) is None

    def test_motorway_allowed_if_foot_yes(self):
        w = prof.foot_edge_weight({"highway": "motorway", "foot": "yes"}, 100)
        assert w is not None

    def test_steps_are_slower(self):
        w_steps = prof.foot_edge_weight({"highway": "steps"}, 100)
        w_normal = prof.foot_edge_weight({"highway": "residential"}, 100)
        assert w_steps.speed_kmh < w_normal.speed_kmh


def test_maxspeed_parsing_variants():
    assert prof._parse_maxspeed("60") == 60
    assert prof._parse_maxspeed("60 km/h") == 60
    assert prof._parse_maxspeed("50;40") == 50
    assert prof._parse_maxspeed("signals") is None
    assert prof._parse_maxspeed(None) is None
    assert prof._parse_maxspeed("30 mph") == pytest.approx(48.28, rel=1e-2)


# ------------------------------------------------- merge de departamentos ---
def test_merge_keeps_all_segments_of_a_multi_segment_way():
    """Regresión (2026-09-11): deduplicar edges por 'id' (el ID de la WAY, no
    del segmento) colapsaba una way de N segmentos a 1 fila. La clave correcta
    es (id, u, v)."""
    dept_a_edges = pd.DataFrame([
        {"id": 999, "u": 1, "v": 2, "length": 100},
        {"id": 999, "u": 2, "v": 3, "length": 100},
        {"id": 999, "u": 3, "v": 4, "length": 100},
    ])
    dept_a_nodes = pd.DataFrame({"id": [1, 2, 3, 4], "lon": [0, 1, 2, 3], "lat": [0, 0, 0, 0]})
    nodes_df, edges_df = merge_department_networks([dept_a_nodes], [dept_a_edges])
    assert len(edges_df) == 3  # las 3 filas del mismo way id, no colapsadas a 1
    assert len(nodes_df) == 4


def test_merge_dedupes_true_duplicate_segments_across_departments():
    # mismo segmento exacto repetido (p.ej. por solape de buffer) SÍ se dedup.
    e1 = pd.DataFrame([{"id": 1, "u": 10, "v": 20, "length": 50}])
    e2 = pd.DataFrame([{"id": 1, "u": 10, "v": 20, "length": 50}])
    n1 = pd.DataFrame({"id": [10, 20], "lon": [0, 1], "lat": [0, 0]})
    nodes_df, edges_df = merge_department_networks([n1, n1], [e1, e2])
    assert len(edges_df) == 1
    assert len(nodes_df) == 2


# ------------------------------------------------------------- grafo ---
def _toy_edges() -> pd.DataFrame:
    # A -> B -> C, oneway car; D aislado (componente separada)
    return pd.DataFrame([
        {"u": "A", "v": "B", "highway": "residential", "oneway": "yes", "length": 1000, "maxspeed": None, "surface": None, "access": None, "bicycle": None, "foot": None, "footway": None, "motor_vehicle": None, "junction": None, "service": None, "tracktype": None},
        {"u": "B", "v": "C", "highway": "residential", "oneway": "yes", "length": 1000, "maxspeed": None, "surface": None, "access": None, "bicycle": None, "foot": None, "footway": None, "motor_vehicle": None, "junction": None, "service": None, "tracktype": None},
    ])


def test_graph_cache_invalidated_by_profile_hash_change(tmp_path):
    """Dos hashes de perfil distintos deben resultar en archivos de cache
    DISTINTOS -- un cambio de perfil nunca reutiliza silenciosamente el grafo
    del perfil anterior."""
    edges = _toy_edges()
    h1 = prof.profile_hash("car", {"routing": {"car_track_fallback_speed_kmh": 12}})
    h2 = prof.profile_hash("car", {"routing": {"car_track_fallback_speed_kmh": 20}})
    assert h1 != h2
    p1 = tmp_path / f"graph_car_{h1}.pkl"
    p2 = tmp_path / f"graph_car_{h2}.pkl"
    build_graph(edges, "car", p1, cfg={"routing": {"car_track_fallback_speed_kmh": 12}})
    build_graph(edges, "car", p2, cfg={"routing": {"car_track_fallback_speed_kmh": 20}})
    assert p1.exists() and p2.exists()
    assert p1 != p2  # nombres distintos -> nunca se pisan ni se confunden


def test_build_graph_does_not_call_lazy_loader_on_cache_hit(tmp_path):
    """Regresión (2026-09-11): mantener edges_df en memoria durante todo el
    bucle de perfiles, incluso cuando el grafo ya está cacheado, causó un
    OOM-kill real. build_graph no debe materializar edges_df si hay cache."""
    cache_path = tmp_path / "graph_car.pkl"
    build_graph(_toy_edges(), "car", cache_path)  # primera vez: construye y cachea

    def _boom():
        raise AssertionError("no debería cargar edges_df: el grafo ya está cacheado")

    graph2 = build_graph(_boom, "car", cache_path)  # segunda vez: debe usar el cache sin invocar _boom
    assert graph2.number_of_edges() > 0


def test_build_graph_car_respects_oneway():
    G = build_graph(_toy_edges(), "car")
    assert G.has_edge("A", "B") and not G.has_edge("B", "A")
    assert G.has_edge("B", "C") and not G.has_edge("C", "B")


def test_build_graph_foot_ignores_oneway():
    G = build_graph(_toy_edges(), "foot")
    assert G.has_edge("A", "B") and G.has_edge("B", "A")


def test_dijkstra_shortest_path_time():
    G = build_graph(_toy_edges(), "car")
    t = nx.single_source_dijkstra_path_length(G, "A", weight="time_s")
    assert t["C"] == pytest.approx(t["B"] * 2, rel=1e-6)


def test_unreachable_when_disconnected():
    G = build_graph(_toy_edges(), "car")
    G.add_node("D")  # componente aislada, sin aristas
    lengths = nx.single_source_dijkstra_path_length(G.reverse(copy=False), "D", weight="time_s")
    assert "A" not in lengths  # no alcanzable, no se inventa un valor


# ------------------------------------------------------------- snapping ---
def test_snap_success_within_threshold():
    node_ids = np.array([1, 2, 3])
    node_lons = np.array([-71.0, -71.01, -71.5])
    node_lats = np.array([-13.0, -13.0, -13.0])
    result = snap.snap_points(["d1"], np.array([-71.0001]), np.array([-13.0]), node_ids, node_lons, node_lats, max_distance_m=500)
    assert result.iloc[0]["status"] == "success"
    assert result.iloc[0]["node_id"] == 1


def test_snap_failure_beyond_threshold():
    node_ids = np.array([1])
    node_lons = np.array([-71.0])
    node_lats = np.array([-13.0])
    result = snap.snap_points(["d1"], np.array([-75.0]), np.array([-13.0]), node_ids, node_lons, node_lats, max_distance_m=500)
    assert result.iloc[0]["status"] == "failure"
    assert "umbral" in result.iloc[0]["fail_reason"]


def test_snap_report_summary_stats():
    df = pd.DataFrame([
        {"point_id": "a", "node_id": 1, "snap_distance_m": 10.0, "status": "success", "fail_reason": None},
        {"point_id": "b", "node_id": 2, "snap_distance_m": 3000.0, "status": "failure", "fail_reason": "x"},
    ])
    r = snap.snap_report(df)
    assert r["n_total"] == 2 and r["n_failed"] == 1 and r["pct_failed"] == 50.0
    assert r["max_snap_m"] == 3000.0


# ------------------------------------------------------------- matrix ---
def _star_graph_car() -> nx.DiGraph:
    """demand D1,D2,D3 conectados a facility F por vías de distinta velocidad."""
    G = nx.DiGraph()
    G.add_edge("D1", "F", time_s=60, length=500)
    G.add_edge("F", "D1", time_s=60, length=500)
    G.add_edge("D2", "F", time_s=600, length=5000)
    G.add_edge("F", "D2", time_s=600, length=5000)
    # D3 sin conexión a F
    G.add_node("D3")
    return G


# Departamentos de prueba: D1/D2/F en "TUMBES"; D3 en "CUSCO" (cross-dept);
# D4 no aparece en el diccionario de nodos -> snap_failed.
_FAC_DEPT = {"FAC1": "TUMBES"}
_DEM_DEPT = {"D1": "TUMBES", "D2": "TUMBES", "D3": "CUSCO", "D4": "TUMBES"}


def test_facility_centric_matrix_full_shape_and_status(tmp_path):
    G = _star_graph_car()
    demand_nodes = {"D1": "D1", "D2": "D2", "D3": "D3", "D4": None}  # D4 snap_failed
    result = mtx.facility_centric_matrix(
        G, "car", facility_nodes={"FAC1": "F"}, facility_dept=_FAC_DEPT,
        demand_nodes=demand_nodes, demand_dept=_DEM_DEPT, cache_dir=tmp_path,
    )
    assert len(result) == 4  # TODOS los demand, incluido el snap_failed
    by_id = result.set_index("demand_id")
    assert by_id.loc["D1", "routing_status"] == st.ROUTED
    assert by_id.loc["D1", "reachable"] and by_id.loc["D1", "travel_time_min"] == pytest.approx(1.0)
    # D3 es mismo grafo pero OTRO departamento -> cross_department_not_evaluated,
    # NUNCA no_route_same_department (aunque el grafo sí lo alcance técnicamente)
    assert by_id.loc["D3", "routing_status"] == st.CROSS_DEPT_NOT_EVALUATED
    assert not by_id.loc["D3", "reachable"]
    # D4 no tiene nodo (snap fallido) -> snap_failed, distinto de no_route_same_department
    assert by_id.loc["D4", "routing_status"] == st.SNAP_FAILED
    assert pd.isna(by_id.loc["D4", "travel_time_min"])


def test_no_route_same_department_when_disconnected_but_same_dept(tmp_path):
    """Un nodo del MISMO departamento pero desconectado del grafo -> no_route_same_department, no cross-department ni snap_failed."""
    G = _star_graph_car()
    G.add_node("D5")  # existe en el grafo, sin aristas -- "snap exitoso pero sin arista transitable"
    demand_nodes = {"D5": "D5"}
    demand_dept = {"D5": "TUMBES"}
    result = mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, demand_nodes, demand_dept, cache_dir=tmp_path)
    assert result.iloc[0]["routing_status"] == st.NO_ROUTE_SAME_DEPT
    assert not result.iloc[0]["reachable"]


def test_matrix_caching_resumes_without_recompute(tmp_path, monkeypatch):
    G = _star_graph_car()
    mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D1": "D1"}, _DEM_DEPT, cache_dir=tmp_path)

    def _boom(*a, **kw):
        raise AssertionError("no debería recalcular: el chunk ya está cacheado")

    monkeypatch.setattr(mtx.nx, "single_source_dijkstra_path_length", _boom)
    result2 = mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D1": "D1"}, _DEM_DEPT, cache_dir=tmp_path)
    assert len(result2) == 1  # no lanzó AssertionError -> reutilizó el cache


def test_matrix_cache_invalidated_when_demand_set_changes(tmp_path):
    """Un chunk cacheado para OTRO conjunto de demand points no debe reutilizarse."""
    G = _star_graph_car()
    mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D1": "D1"}, _DEM_DEPT, cache_dir=tmp_path)
    result2 = mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D2": "D2"}, _DEM_DEPT, cache_dir=tmp_path)
    assert set(result2["demand_id"]) == {"D2"}  # no se coló D1 del cache viejo


def test_matrix_cache_version_isolates_runs_by_profile_hash(tmp_path):
    """El cache_version debe incorporar el profile_hash: dos perfiles
    distintos (aquí simulados con cache_version distinto) nunca comparten
    chunk -- corrección directa del hallazgo de auditoría (grafo/matriz sin
    versión, tuvimos que borrar caches a mano)."""
    G = _star_graph_car()
    h_old = prof.profile_hash("car", {"routing": {"car_track_fallback_speed_kmh": 12}})
    h_new = prof.profile_hash("car", {"routing": {"car_track_fallback_speed_kmh": 20}})
    assert h_old != h_new
    mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D1": "D1"}, _DEM_DEPT, cache_dir=tmp_path, cache_version=f"v__{h_old}")
    mtx.facility_centric_matrix(G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D1": "D1"}, _DEM_DEPT, cache_dir=tmp_path, cache_version=f"v__{h_new}")
    assert (tmp_path / "car" / f"v__{h_old}" / "FAC1.parquet").exists()
    assert (tmp_path / "car" / f"v__{h_new}" / "FAC1.parquet").exists()


def test_upgrade_candidate_extra_columns(tmp_path):
    G = _star_graph_car()
    result = mtx.facility_centric_matrix(
        G, "car", {"FAC1": "F"}, _FAC_DEPT, {"D1": "D1"}, _DEM_DEPT, cache_dir=tmp_path,
        extra_cols={"FAC1": {"current_resolutive": False, "upgrade_candidate": True}},
    )
    assert result.iloc[0]["upgrade_candidate"] == True  # noqa: E712
    assert result.iloc[0]["current_resolutive"] == False  # noqa: E712


def test_demand_and_facility_ids_with_leading_zeros_preserved(tmp_path):
    G = _star_graph_car()
    result = mtx.facility_centric_matrix(
        G, "car", {"00000001": "F"}, {"00000001": "TUMBES"}, {"000042": "D1"}, {"000042": "TUMBES"}, cache_dir=tmp_path,
    )
    assert result.iloc[0]["facility_id"] == "00000001"
    assert result.iloc[0]["demand_id"] == "000042"


def test_nearest_facility_multi_source_picks_closest():
    G = nx.DiGraph()
    G.add_edge("D1", "FA", time_s=600, length=1000)
    G.add_edge("FA", "D1", time_s=600, length=1000)
    G.add_edge("D1", "FB", time_s=60, length=100)
    G.add_edge("FB", "D1", time_s=60, length=100)
    result = mtx.nearest_facility_multi_source(
        G, "foot", facility_nodes={"FAC_A": "FA", "FAC_B": "FB"}, demand_nodes={"D1": "D1"},
        node_to_facility={"FA": "FAC_A", "FB": "FAC_B"},
    )
    assert result.iloc[0]["facility_id"] == "FAC_B"
    assert result.iloc[0]["travel_time_min"] == pytest.approx(1.0)


# --------------------------------------------------- compare (regresión) ---
def test_car_vs_foot_handles_all_unreachable_mode_without_typeerror():
    """Regresión: en un subconjunto pequeño, un modo puede quedar con 0 pares
    alcanzables -> la columna travel_time_min se relee como object/None (no
    NaN), y None/None lanzaba TypeError antes del fix."""
    nearest_df = pd.DataFrame([
        {"demand_id": "D1", "facility_id": "F1", "mode": "car", "distance_m": 1000.0, "travel_time_min": 2.0, "reachable": True},
    ]).astype(object)
    result = cmp.car_vs_foot(nearest_df)
    assert result["n_total"] == 0  # "foot" ni aparece -> sin intersección de demand_id
    assert result["table"].empty


def test_car_vs_foot_five_mutually_exclusive_categories():
    """Corrección de auditoría (2026-09-11): el % de "cambia de facility"
    debe excluir la reachability mixta (antes 66.8% inflado -> 24.5% real)."""
    nearest_df = pd.DataFrame([
        # D1: ambos alcanzables, MISMA facility
        {"demand_id": "D1", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D1", "facility_id": "FA", "mode": "foot", "distance_m": 100.0, "travel_time_min": 10.0, "reachable": True},
        # D2: ambos alcanzables, DISTINTA facility
        {"demand_id": "D2", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D2", "facility_id": "FB", "mode": "foot", "distance_m": 200.0, "travel_time_min": 20.0, "reachable": True},
        # D3: solo car alcanzable
        {"demand_id": "D3", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D3", "facility_id": None, "mode": "foot", "distance_m": None, "travel_time_min": None, "reachable": False},
        # D4: solo foot alcanzable
        {"demand_id": "D4", "facility_id": None, "mode": "car", "distance_m": None, "travel_time_min": None, "reachable": False},
        {"demand_id": "D4", "facility_id": "FB", "mode": "foot", "distance_m": 100.0, "travel_time_min": 10.0, "reachable": True},
        # D5: ninguno alcanzable
        {"demand_id": "D5", "facility_id": None, "mode": "car", "distance_m": None, "travel_time_min": None, "reachable": False},
        {"demand_id": "D5", "facility_id": None, "mode": "foot", "distance_m": None, "travel_time_min": None, "reachable": False},
    ])
    result = cmp.car_vs_foot(nearest_df)
    assert result["n_total"] == 5
    assert result["counts"] == {
        cmp.BOTH_SAME: 1, cmp.BOTH_DIFFERENT: 1, cmp.CAR_ONLY: 1, cmp.FOOT_ONLY: 1, cmp.BOTH_UNREACHABLE: 1,
    }
    # denominador correcto: solo D1+D2 (ambos alcanzables) = 2, de los cuales 1 es distinta facility
    assert result["n_both_reachable"] == 2
    assert result["pct_different_nearest_of_both_reachable"] == pytest.approx(50.0)


def test_three_mode_comparison_handles_object_dtype_none():
    nearest_df = pd.DataFrame([
        {"demand_id": "D1", "facility_id": "F1", "mode": "car", "distance_m": 1000.0, "travel_time_min": 2.0, "reachable": True},
    ])
    out = cmp.three_mode_comparison(nearest_df, ["D1"])
    assert out.loc[0, "reachable_foot"] == False  # noqa: E712
    assert pd.isna(out.loc[0, "foot_over_car_ratio"])  # no explota con None/None


def test_three_mode_comparison_reachability_categories():
    nearest_df = pd.DataFrame([
        {"demand_id": "D1", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D1", "facility_id": "FA", "mode": "bike", "distance_m": 100.0, "travel_time_min": 3.0, "reachable": True},
        {"demand_id": "D1", "facility_id": "FA", "mode": "foot", "distance_m": 100.0, "travel_time_min": 10.0, "reachable": True},
        {"demand_id": "D2", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D2", "facility_id": "FB", "mode": "bike", "distance_m": 200.0, "travel_time_min": 8.0, "reachable": True},
        {"demand_id": "D3", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
    ])
    out = cmp.three_mode_comparison(nearest_df, ["D1", "D2", "D3", "D4"]).set_index("demand_id")
    assert out.loc["D1", "reachability_category"] == cmp.ALL_THREE
    assert out.loc["D1", "n_modes_reachable"] == 3
    assert out.loc["D2", "reachability_category"] == cmp.EXACTLY_TWO
    assert out.loc["D3", "reachability_category"] == cmp.EXACTLY_ONE
    assert out.loc["D4", "reachability_category"] == cmp.NONE_REACHABLE
    assert out.loc["D4", "n_modes_reachable"] == 0


def test_three_mode_comparison_same_facility_is_na_not_false_when_one_unreachable():
    """No debe llamarse 'distinta facility' a un caso donde un modo no tiene nearest."""
    nearest_df = pd.DataFrame([
        {"demand_id": "D1", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        # sin fila foot para D1 -> foot unreachable
    ])
    out = cmp.three_mode_comparison(nearest_df, ["D1"]).set_index("demand_id")
    assert pd.isna(out.loc["D1", "car_foot_same_facility"])  # NA, no False
    assert out.loc["D1", "car_foot_same_facility"] is not False


def test_three_mode_comparison_same_facility_true_and_false_when_both_reachable():
    nearest_df = pd.DataFrame([
        {"demand_id": "D1", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D1", "facility_id": "FA", "mode": "bike", "distance_m": 100.0, "travel_time_min": 3.0, "reachable": True},
        {"demand_id": "D2", "facility_id": "FA", "mode": "car", "distance_m": 100.0, "travel_time_min": 1.0, "reachable": True},
        {"demand_id": "D2", "facility_id": "FB", "mode": "bike", "distance_m": 100.0, "travel_time_min": 3.0, "reachable": True},
    ])
    out = cmp.three_mode_comparison(nearest_df, ["D1", "D2"]).set_index("demand_id")
    assert out.loc["D1", "car_bike_same_facility"] == True  # noqa: E712
    assert out.loc["D2", "car_bike_same_facility"] == False  # noqa: E712


# ------------------------------------------------------- status.py ---
class TestRoutingStatus:
    def test_snap_failed_takes_precedence(self):
        assert st.classify_pair(snap_ok=False, same_department=True, reachable=True) == st.SNAP_FAILED
        assert st.classify_pair(snap_ok=False, same_department=False, reachable=False) == st.SNAP_FAILED

    def test_cross_department_not_evaluated_regardless_of_reachable_flag(self):
        # aunque "reachable" viniera True por error, cross-dept nunca se evalúa de verdad
        assert st.classify_pair(snap_ok=True, same_department=False, reachable=False) == st.CROSS_DEPT_NOT_EVALUATED
        assert st.classify_pair(snap_ok=True, same_department=False, reachable=True) == st.CROSS_DEPT_NOT_EVALUATED

    def test_routed_vs_no_route_same_department(self):
        assert st.classify_pair(snap_ok=True, same_department=True, reachable=True) == st.ROUTED
        assert st.classify_pair(snap_ok=True, same_department=True, reachable=False) == st.NO_ROUTE_SAME_DEPT

    def test_snap_failed_is_distinct_from_no_route_same_department(self):
        """snap_failed (nunca se ubicó en la red) es conceptualmente distinto
        de no_route_same_department (se ubicó, pero sin ruta) -- no deben
        colapsarse al mismo valor."""
        a = st.classify_demand(snap_ok=False, reachable_same_dept=False)
        b = st.classify_demand(snap_ok=True, reachable_same_dept=False)
        assert a == st.SNAP_FAILED
        assert b == st.NO_ROUTE_SAME_DEPT
        assert a != b


# --------------------------------------------- snap_report: IDs con ceros ---
def test_snap_report_parquet_roundtrip_preserves_leading_zeros(tmp_path):
    """Regresión (2026-09-11): snap_report.csv released con pandas por
    defecto pierde los ceros a la izquierda de point_id (se infiere int64).
    El Parquet, tipado explícitamente como string, no tiene ese problema."""
    df = pd.DataFrame([{"point_id": "00007874", "node_id": 1, "snap_distance_m": 10.0, "status": "success", "fail_reason": None, "point_type": "resolutive_facility"}])
    df["point_id"] = df["point_id"].astype(str)

    csv_path = tmp_path / "snap_report.csv"
    parquet_path = tmp_path / "snap_report.parquet"
    df.to_csv(csv_path, index=False)
    df.to_parquet(parquet_path)

    reread_csv_naive = pd.read_csv(csv_path)  # sin dtype explícito -- reproduce el bug
    assert reread_csv_naive["point_id"].iloc[0] != "00007874"  # se perdieron los ceros (comportamiento conocido de CSV)

    reread_parquet = pd.read_parquet(parquet_path)
    assert reread_parquet["point_id"].iloc[0] == "00007874"  # el parquet SÍ preserva el string exacto

    reread_csv_typed = pd.read_csv(csv_path, dtype={"point_id": str})
    assert reread_csv_typed["point_id"].iloc[0] == "00007874"  # el CSV es correcto SI se especifica dtype


def test_car_nearest_differs_from_foot_nearest():
    """Escenario donde el auto llega más rápido a F1 (vía rápida) pero a pie F2
    es más cercano (F1 solo accesible por una vía sin acceso peatonal)."""
    G_car = nx.DiGraph()
    G_car.add_edge("D1", "F1", time_s=60, length=2000)
    G_car.add_edge("F1", "D1", time_s=60, length=2000)
    G_foot = nx.DiGraph()
    G_foot.add_edge("D1", "F2", time_s=300, length=250)  # F1 no está en el grafo peatonal (vía no caminable)
    G_foot.add_edge("F2", "D1", time_s=300, length=250)

    car_nearest = mtx.nearest_facility_multi_source(G_car, "car", {"F1": "F1"}, {"D1": "D1"}, {"F1": "F1"})
    foot_nearest = mtx.nearest_facility_multi_source(G_foot, "foot", {"F2": "F2"}, {"D1": "D1"}, {"F2": "F2"})
    assert car_nearest.iloc[0]["facility_id"] == "F1"
    assert foot_nearest.iloc[0]["facility_id"] == "F2"
    assert car_nearest.iloc[0]["facility_id"] != foot_nearest.iloc[0]["facility_id"]
