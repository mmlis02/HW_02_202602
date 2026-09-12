"""Fase 2: routing y cómputo de tiempos de viaje (NetworkX local, ver
docs/01_routing_decision.md — NO OSRM, NO API remota).

Uso:
    conda activate ./.venv
    python -m scripts.run_routing --subset     # PRUEBA en subconjunto pequeño
    python -m scripts.run_routing              # corrida completa

No implementa Fase 3 (cobertura, Gini, INEI) ni el simulador ni Streamlit.

**Corrección de auditoría (2026-09-11)**:
1. `car` habilita `track` (velocidad configurable, ver `config.md`
   `routing.car_track_fallback_speed_kmh`).
2. El cache de grafos y matrices se versiona por `profile_hash(mode, cfg)` —
   un cambio de velocidades/reglas invalida el cache automáticamente, sin
   borrar carpetas a mano (ver `src/routing/profiles.py`).
3. Cada fila de la matriz y cada demand point llevan un `routing_status`
   explícito (`routed`/`snap_failed`/`no_route_same_department`/
   `cross_department_not_evaluated`) en vez de un solo booleano `reachable`
   que mezclaba las 4 situaciones — ver `src/routing/status.py`.
4. `car_vs_foot` usa categorías mutuamente excluyentes (no cuenta
   "reachability mixta" como "cambio de facility").
5. Regeneración selectiva: el grafo de bike/foot se REUTILIZA del cache (no
   se re-extrae OSM ni se reconstruye desde cero) porque su `profile_hash` no
   cambió; solo se re-ejecuta Dijkstra sobre ese grafo ya en memoria (barato,
   ver docs/01) porque el ESQUEMA de la matriz (routing_status, universo
   completo de 5000) cambió para los 3 modos por requisito de la Parte 1 de
   la corrección — no porque su perfil haya cambiado.
"""

from __future__ import annotations

import argparse
import gc
import logging
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src import routing as _routing_pkg  # noqa: F401
from src.acquisition import acquire_osm_pbf
from src.config import get_path, load_config
from src.routing import compare as cmp
from src.routing import status as st
from src.routing.graph_build import build_graph
from src.routing.matrix import facility_centric_matrix, nearest_facility_multi_source
from src.routing.osm_extract import (
    build_combined_network,
    combined_network_cache_paths,
    load_combined_edges,
    load_combined_nodes,
)
from src.routing.profiles import profile_hash
from src.routing.snapping import snap_points, snap_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def _snap_group(label: str, gdf: gpd.GeoDataFrame, id_col: str, node_ids, node_lons, node_lats, max_dist: float) -> pd.DataFrame:
    if len(gdf) == 0:
        return pd.DataFrame(columns=["point_id", "node_id", "snap_distance_m", "status", "fail_reason", "point_type"])
    df = snap_points(
        gdf[id_col].astype(str).tolist(),
        gdf.geometry.x.to_numpy(), gdf.geometry.y.to_numpy(),
        node_ids, node_lons, node_lats, max_dist,
    )
    df["point_type"] = label
    r = snap_report(df)
    logger.info(
        "[snap %s] N=%d fallidos=%d (%.1f%%) media=%.0fm mediana=%.0fm P95=%.0fm max=%.0fm",
        label, r["n_total"], r["n_failed"], r["pct_failed"],
        r["mean_snap_m"] or -1, r["median_snap_m"] or -1, r["p95_snap_m"] or -1, r["max_snap_m"] or -1,
    )
    return df


def _nodes_all(snap_df: pd.DataFrame) -> dict[str, int | None]:
    """point_id -> node_id (int) si snap OK, None si falló. TODOS los ids."""
    out = {}
    for _, row in snap_df.iterrows():
        out[row["point_id"]] = int(row["node_id"]) if row["status"] == "success" else None
    return out


def _track_recovery_diagnostic(car_graph, prior_isolated_nodes: set[int], demand_nodes_all: dict, demand_dept, resolutive_matrix_car: pd.DataFrame) -> dict:
    """Cuántos de los nodos antes aislados (sin track) recuperan aristas /
    ruta con track habilitado — para el quality report (Parte 11)."""
    routed_by_demand = set(resolutive_matrix_car.loc[resolutive_matrix_car["routing_status"] == st.ROUTED, "demand_id"])
    n_recovers_edges = 0
    n_recovers_route = 0
    n_still_isolated = 0
    for did, node in demand_nodes_all.items():
        if node not in prior_isolated_nodes:
            continue
        has_edges_now = node in car_graph and car_graph.degree(node) > 0
        if has_edges_now:
            n_recovers_edges += 1
        else:
            n_still_isolated += 1
        if did in routed_by_demand:
            n_recovers_route += 1
    return {
        "n_previously_isolated": len(prior_isolated_nodes),
        "n_recovers_edges": n_recovers_edges,
        "n_recovers_route_to_resolutive": n_recovers_route,
        "n_still_isolated": n_still_isolated,
    }


def main(subset: bool = False) -> None:
    t_start = time.time()
    cfg = load_config()
    processed_dir = get_path("data_processed", cfg)
    outputs_dir = get_path("data_outputs", cfg)
    cache_dir = get_path("data_cache", cfg)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Fase 2 (%s): adquisición OSM ===", "SUBSET" if subset else "COMPLETA")
    osm_res = acquire_osm_pbf(cfg)
    pbf_path = osm_res.path

    logger.info("=== Extracción de red vial (por departamento) ===")
    t0 = time.time()
    nodes_cache, edges_cache = combined_network_cache_paths(cache_dir / "osm_network")
    if nodes_cache.exists() and edges_cache.exists():
        nodes_df = load_combined_nodes(cache_dir / "osm_network")
        edges_source = lambda: load_combined_edges(cache_dir / "osm_network")  # noqa: E731
        logger.info("red combinada (cache): %d nodos; edges se cargan perezosamente solo si algún grafo falta en cache", len(nodes_df))
    else:
        nodes_df, edges_df_eager = build_combined_network(cfg, pbf_path, cache_dir / "osm_network")
        edges_source = edges_df_eager
        logger.info("red combinada: %d nodos, %d edges en %.1fs", len(nodes_df), len(edges_df_eager), time.time() - t0)

    logger.info("=== Cargando facilities/demand procesados de Fase 1 ===")
    facilities = gpd.read_parquet(processed_dir / "facilities.parquet")
    demand = gpd.read_parquet(processed_dir / "demand.parquet")

    resolutive = facilities[facilities["usable_for_routing"]].copy()
    upgrade_candidates = facilities[
        facilities["CATEGORIA_NORM"].isin(["I-3", "I-4"]) & facilities["is_active"] & ~facilities["qc_excluded_from_routing"]
    ].copy()
    any_facility_foot_pool = facilities[~facilities["qc_excluded_from_routing"]].copy()

    if subset:
        logger.info("--- MODO SUBSET ---")
        demand = demand[demand["DEP"].str.upper() == "TUMBES"].head(20).copy()
        resolutive_subset = resolutive[resolutive["DEPARTAMENTO"] == "TUMBES"].head(5).copy()
        resolutive = resolutive_subset if len(resolutive_subset) else resolutive.head(5).copy()
        upgrade_candidates = upgrade_candidates[upgrade_candidates["DEPARTAMENTO"] == "TUMBES"].head(5).copy()
        any_facility_foot_pool = any_facility_foot_pool[any_facility_foot_pool["DEPARTAMENTO"] == "TUMBES"].head(30).copy()

    logger.info(
        "ámbito: %d demand (muestra completa, NO se cambia), %d resolutivos, %d candidatos I-3/I-4, %d facilities para foot",
        len(demand), len(resolutive), len(upgrade_candidates), len(any_facility_foot_pool),
    )

    dep_of_demand = dict(zip(demand["CODCP"].astype(str), demand["DEP"]))
    dep_of_resolutive = dict(zip(resolutive["COD_IPRESS"].astype(str), resolutive["DEPARTAMENTO"]))
    dep_of_upgrade = dict(zip(upgrade_candidates["COD_IPRESS"].astype(str), upgrade_candidates["DEPARTAMENTO"]))

    node_ids = nodes_df["id"].to_numpy()
    node_lons = nodes_df["lon"].to_numpy()
    node_lats = nodes_df["lat"].to_numpy()
    snap_max = cfg["routing"]["snap_max_distance_m"]

    logger.info("=== Snapping (independiente del perfil: mismo pool de nodos candidatos) ===")
    snap_demand = _snap_group("demand", demand, "CODCP", node_ids, node_lons, node_lats, snap_max)
    snap_resolutive = _snap_group("resolutive_facility", resolutive, "COD_IPRESS", node_ids, node_lons, node_lats, snap_max)
    snap_upgrade = _snap_group("upgrade_candidate_facility", upgrade_candidates, "COD_IPRESS", node_ids, node_lons, node_lats, snap_max)
    snap_anyfac = _snap_group("any_facility_foot", any_facility_foot_pool, "COD_IPRESS", node_ids, node_lons, node_lats, snap_max)
    del node_ids, node_lons, node_lats
    gc.collect()

    # --- Corrección de auditoría: snap_report con IDs tipados como string,
    # CSV (inspección manual) + Parquet (canónico para cruces) ---
    snap_all = pd.concat([snap_demand, snap_resolutive, snap_upgrade, snap_anyfac], ignore_index=True)
    snap_all["point_id"] = snap_all["point_id"].astype(str)
    snap_all.to_csv(outputs_dir / "snap_report.csv", index=False)
    snap_all.to_parquet(outputs_dir / "snap_report.parquet")

    demand_nodes_all = _nodes_all(snap_demand)          # TODOS los 5000, None si snap_failed
    resolutive_nodes = {r["point_id"]: int(r["node_id"]) for _, r in snap_resolutive.iterrows() if r["status"] == "success"}
    upgrade_nodes = {r["point_id"]: int(r["node_id"]) for _, r in snap_upgrade.iterrows() if r["status"] == "success"}
    anyfac_nodes = {r["point_id"]: int(r["node_id"]) for _, r in snap_anyfac.iterrows() if r["status"] == "success"}
    demand_nodes_success = {k: v for k, v in demand_nodes_all.items() if v is not None}
    node_to_resolutive = {n: fid for fid, n in resolutive_nodes.items()}
    node_to_anyfac = {n: fid for fid, n in anyfac_nodes.items()}

    logger.info(
        "snap OK -> demand=%d/%d resolutivos=%d/%d upgrade=%d/%d any_foot=%d/%d",
        len(demand_nodes_success), len(demand), len(resolutive_nodes), len(resolutive),
        len(upgrade_nodes), len(upgrade_candidates), len(anyfac_nodes), len(any_facility_foot_pool),
    )

    # Diagnóstico "aislado por exclusión de track" — se mide ANTES de tocar
    # el grafo car nuevo, usando el grafo car cacheado de la corrida previa
    # (perfil sin track) si existe, para poder reportar antes/después.
    prior_isolated_car_nodes: set[int] = set()
    old_car_hash_glob = list((cache_dir / "graphs").glob("graph_car_*.pkl")) if (cache_dir / "graphs").exists() else []
    legacy_car_pkl = cache_dir / "graphs" / "graph_car.pkl"
    old_car_path = legacy_car_pkl if legacy_car_pkl.exists() else (old_car_hash_glob[0] if old_car_hash_glob else None)
    if old_car_path is not None:
        import pickle
        with open(old_car_path, "rb") as fh:
            old_car_graph = pickle.load(fh)
        for did, node in demand_nodes_success.items():
            if node not in old_car_graph or old_car_graph.degree(node) == 0:
                prior_isolated_car_nodes.add(node)
        del old_car_graph
        gc.collect()
        logger.info("[diagnóstico track] %d demand points estaban aislados en el car ANTERIOR (sin track)", len(prior_isolated_car_nodes))

    resolutive_matrices = []
    nearest_resolutive_rows = []
    routing_matrix_upgrade = None
    nearest_any_facility_foot = None
    n_dijkstra_total = 0
    hashes_used: dict[str, str] = {}
    track_diag: dict | None = None

    for mode in ("car", "bike", "foot"):
        phash = profile_hash(mode, cfg)
        hashes_used[mode] = phash
        cache_version = f"osm{cfg['data_cutoff']['osm_geofabrik']['date']}_buf{cfg['routing']['clip_buffer_km']}_snap{int(snap_max)}__{phash}"

        logger.info("=== Perfil %s (profile_hash=%s): grafo ===", mode, phash)
        t0 = time.time()
        graph = build_graph(edges_source, mode, cache_dir / "graphs" / f"graph_{mode}_{phash}.pkl", cfg=cfg)
        logger.info("[%s] grafo listo en %.1fs (%d nodos, %d aristas)", mode, time.time() - t0, graph.number_of_nodes(), graph.number_of_edges())

        m = facility_centric_matrix(
            graph, mode, resolutive_nodes, dep_of_resolutive, demand_nodes_all, dep_of_demand,
            cache_dir / "routing_matrix_resolutive", cache_version=cache_version,
        )
        resolutive_matrices.append(m)
        n_dijkstra_total += len(resolutive_nodes)

        if mode == "car":
            track_diag = _track_recovery_diagnostic(graph, prior_isolated_car_nodes, demand_nodes_success, dep_of_demand, m)
            logger.info("[track] previamente aislados=%d recupera_edges=%d recupera_ruta=%d sigue_aislado=%d", *track_diag.values())

        r = nearest_facility_multi_source(graph, mode, resolutive_nodes, demand_nodes_success, node_to_resolutive)
        # completar con snap_failed para el universo completo de 5000
        failed_ids = [did for did, n in demand_nodes_all.items() if n is None]
        if failed_ids:
            r_failed = pd.DataFrame([{"demand_id": did, "facility_id": None, "mode": mode, "distance_m": None, "travel_time_min": None, "reachable": False} for did in failed_ids])
            r = pd.concat([r, r_failed], ignore_index=True)
        r["routing_status"] = np.where(
            r["demand_id"].isin(failed_ids), st.SNAP_FAILED,
            np.where(r["reachable"].astype(bool), st.ROUTED, st.NO_ROUTE_SAME_DEPT),
        )
        nearest_resolutive_rows.append(r)

        if mode == "car":
            extra_cols = {fid: {"current_resolutive": False, "upgrade_candidate": True} for fid in upgrade_nodes}
            routing_matrix_upgrade = facility_centric_matrix(
                graph, "car", upgrade_nodes, dep_of_upgrade, demand_nodes_all, dep_of_demand,
                cache_dir / "routing_matrix_upgrade", extra_cols=extra_cols, cache_version=cache_version,
            )
        if mode == "foot":
            nearest_any_facility_foot = nearest_facility_multi_source(graph, "foot", anyfac_nodes, demand_nodes_success, node_to_anyfac)
            failed_any = [did for did, n in demand_nodes_all.items() if n is None]
            if failed_any:
                naf_failed = pd.DataFrame([{"demand_id": did, "facility_id": None, "mode": "foot", "distance_m": None, "travel_time_min": None, "reachable": False} for did in failed_any])
                nearest_any_facility_foot = pd.concat([nearest_any_facility_foot, naf_failed], ignore_index=True)

        del graph
        gc.collect()
        logger.info("[%s] liberado de memoria antes del siguiente perfil", mode)

    routing_matrix_resolutive = pd.concat(resolutive_matrices, ignore_index=True)
    routing_matrix_resolutive.to_parquet(outputs_dir / "routing_matrix_resolutive.parquet")
    logger.info("routing_matrix_resolutive.parquet: %d filas", len(routing_matrix_resolutive))

    routing_matrix_upgrade.to_parquet(outputs_dir / "routing_matrix_upgrade_candidates_car.parquet")
    logger.info("routing_matrix_upgrade_candidates_car.parquet: %d filas", len(routing_matrix_upgrade))

    nearest_resolutive_by_mode = pd.concat(nearest_resolutive_rows, ignore_index=True)
    nearest_resolutive_by_mode.to_parquet(outputs_dir / "nearest_resolutive_by_mode.parquet")
    logger.info("nearest_resolutive_by_mode.parquet: %d filas", len(nearest_resolutive_by_mode))

    nearest_any_facility_foot.to_parquet(outputs_dir / "nearest_any_facility_foot.parquet")
    logger.info("nearest_any_facility_foot.parquet: %d filas", len(nearest_any_facility_foot))

    # --- Output consolidado por demand point (Parte 1) ---
    logger.info("=== Construyendo demand_routing_status.parquet ===")
    demand_status_rows = []
    snap_dem_idx = snap_demand.set_index(snap_demand["point_id"].astype(str))
    nr_idx = {mode: nearest_resolutive_by_mode[nearest_resolutive_by_mode["mode"] == mode].set_index("demand_id") for mode in ("car", "bike", "foot")}
    for did in demand["CODCP"].astype(str):
        srow = snap_dem_idx.loc[did] if did in snap_dem_idx.index else None
        row = {
            "demand_id": did,
            "dep": dep_of_demand.get(did),
            "snap_status": srow["status"] if srow is not None else "failure",
            "snap_distance_m": srow["snap_distance_m"] if srow is not None else None,
        }
        for mode in ("car", "bike", "foot"):
            nrow = nr_idx[mode].loc[did] if did in nr_idx[mode].index else None
            row[f"routing_status_{mode}"] = nrow["routing_status"] if nrow is not None else st.SNAP_FAILED
            row[f"nearest_facility_{mode}"] = nrow["facility_id"] if nrow is not None else None
            row[f"travel_time_min_{mode}"] = nrow["travel_time_min"] if nrow is not None else None
            row[f"distance_m_{mode}"] = nrow["distance_m"] if nrow is not None else None
        demand_status_rows.append(row)
    demand_routing_status = pd.DataFrame(demand_status_rows)
    demand_routing_status.to_parquet(outputs_dir / "demand_routing_status.parquet")
    logger.info("demand_routing_status.parquet: %d filas (universo completo, incluye snap_failed)", len(demand_routing_status))

    logger.info("=== Comparaciones diagnósticas ===")
    demand_coords = dict(zip(demand["CODCP"].astype(str), zip(demand.geometry.x, demand.geometry.y)))
    facility_coords = dict(zip(resolutive["COD_IPRESS"].astype(str), zip(resolutive.geometry.x, resolutive.geometry.y)))

    cvf = cmp.car_vs_foot(nearest_resolutive_by_mode)
    logger.info(
        "car vs foot: total=%d both_reachable=%d different(of both reachable)=%.1f%% counts=%s",
        cvf["n_total"], cvf["n_both_reachable"], cvf["pct_different_nearest_of_both_reachable"] or -1, cvf["counts"],
    )
    cvf["table"].to_parquet(outputs_dir / "comparison_car_vs_foot.parquet")

    three_mode = cmp.three_mode_comparison(nearest_resolutive_by_mode, demand["CODCP"].astype(str).tolist())
    three_mode.to_parquet(outputs_dir / "comparison_car_bike_foot.parquet")

    straight_car = cmp.straight_line_vs_network(nearest_resolutive_by_mode, demand_coords, facility_coords, "car")
    straight_car.to_parquet(outputs_dir / "comparison_straight_vs_network_car.parquet")

    # --- Quality report ampliado (Parte 11) ---
    total_time_s = time.time() - t_start
    quality_rows = [
        {"metric": "osm_pbf_downloaded", "value": str(osm_res.was_downloaded)},
        {"metric": "osm_cutoff_date", "value": cfg["data_cutoff"]["osm_geofabrik"]["date"]},
        {"metric": "network_nodes", "value": len(nodes_df)},
        {"metric": "profile_hash_car", "value": hashes_used["car"]},
        {"metric": "profile_hash_bike", "value": hashes_used["bike"]},
        {"metric": "profile_hash_foot", "value": hashes_used["foot"]},
        {"metric": "car_track_fallback_speed_kmh", "value": cfg["routing"]["car_track_fallback_speed_kmh"]},
        {"metric": "demand_total", "value": len(demand)},
        {"metric": "resolutive_facilities_routable", "value": len(resolutive_nodes)},
        {"metric": "upgrade_candidates_routable", "value": len(upgrade_nodes)},
        {"metric": "any_facility_foot_routable", "value": len(anyfac_nodes)},
        {"metric": "resolutive_matrix_rows", "value": len(routing_matrix_resolutive)},
        {"metric": "upgrade_matrix_rows", "value": len(routing_matrix_upgrade)},
        {"metric": "nearest_resolutive_rows", "value": len(nearest_resolutive_by_mode)},
        {"metric": "nearest_any_foot_rows", "value": len(nearest_any_facility_foot)},
        {"metric": "n_dijkstra_facility_centric_approx", "value": n_dijkstra_total},
        {"metric": "total_runtime_s", "value": round(total_time_s, 1)},
        {"metric": "mode", "value": "subset" if subset else "full"},
    ]
    for mode in ("car", "bike", "foot"):
        sub = nearest_resolutive_by_mode[nearest_resolutive_by_mode["mode"] == mode]
        counts = sub["routing_status"].value_counts().to_dict()
        quality_rows += [
            {"metric": f"{mode}_snap_failed", "value": counts.get(st.SNAP_FAILED, 0)},
            {"metric": f"{mode}_snap_success", "value": len(demand) - counts.get(st.SNAP_FAILED, 0)},
            {"metric": f"{mode}_routed", "value": counts.get(st.ROUTED, 0)},
            {"metric": f"{mode}_no_route_same_department", "value": counts.get(st.NO_ROUTE_SAME_DEPT, 0)},
        ]
    mat_car = routing_matrix_resolutive[routing_matrix_resolutive["mode"] == "car"]
    cross_dept_cells = int((mat_car["routing_status"] == st.CROSS_DEPT_NOT_EVALUATED).sum())
    quality_rows.append({"metric": "car_matrix_cross_department_not_evaluated_cells", "value": cross_dept_cells})
    quality_rows.append({"metric": "car_matrix_cross_department_pct", "value": round(100 * cross_dept_cells / len(mat_car), 2)})
    if track_diag:
        quality_rows += [
            {"metric": "car_track_previously_isolated", "value": track_diag["n_previously_isolated"]},
            {"metric": "car_track_recovers_edges", "value": track_diag["n_recovers_edges"]},
            {"metric": "car_track_recovers_route_to_resolutive", "value": track_diag["n_recovers_route_to_resolutive"]},
            {"metric": "car_track_still_isolated", "value": track_diag["n_still_isolated"]},
        ]
    pd.DataFrame(quality_rows).to_csv(outputs_dir / "routing_quality_report.csv", index=False)
    logger.info("=== Fase 2 (%s) completa en %.1fs ===", "SUBSET" if subset else "COMPLETA", total_time_s)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", action="store_true")
    args = parser.parse_args()
    main(subset=args.subset)
