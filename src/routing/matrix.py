"""Cómputo de matrices de tiempo de viaje.

Estrategia (evita 5000×40 rutas independientes, ver docs): para cada
facility (destino), un único Dijkstra desde su nodo snapeado sobre el grafo
**invertido** da, en una pasada, el tiempo desde ESE nodo a todos los demás —
que es exactamente el tiempo de cualquier demand point hacia esa facility (la
dirección real del viaje es demanda -> facility; en el grafo invertido eso
equivale a un Dijkstra de fuente única partiendo de la facility). Unas pocas
decenas de Dijkstra por perfil, no miles de rutas punto a punto.

Caching: un chunk parquet por (perfil, hash-de-perfil, facility_id). Un
cambio de velocidades/reglas cambia el hash y por tanto invalida el cache
automáticamente — ver `src/routing/profiles.py::profile_hash`.

**Corrección de auditoría (2026-09-11) — `routing_status` explícito**: cada
fila del origin×facility ahora distingue `routed` / `snap_failed` /
`no_route_same_department` / `cross_department_not_evaluated` (ver
`src/routing/status.py`) en vez de un solo booleano `reachable` que mezclaba
las 4 situaciones. La matriz conserva TODAS las filas demand×facility,
incluidos los 326 demand points con snap fallido (antes ausentes por
completo) y los pares cross-departamento (antes indistinguibles de "sin
ruta"). No se construye ningún grafo nacional para evaluar los pares
cross-departamento — la auditoría demostró (comparación contra la cota
geodésica) que ningún nearest resolutive actual podría cambiar aunque se
evaluaran, así que se documentan como `cross_department_not_evaluated` en
vez de calcularse.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from src.routing import status as st

logger = logging.getLogger(__name__)


def _reverse_view(G: nx.DiGraph) -> nx.DiGraph:
    return G.reverse(copy=False)


def facility_centric_matrix(
    graph: nx.DiGraph,
    mode: str,
    facility_nodes: dict[str, int],
    facility_dept: dict[str, str],
    demand_nodes: dict[str, int | None],
    demand_dept: dict[str, str],
    cache_dir: str | Path,
    extra_cols: dict[str, dict[str, Any]] | None = None,
    cache_version: str = "v1",
) -> pd.DataFrame:
    """Matriz completa demand_id × facility_id para `mode`, TODOS los
    demand_id (incluidos los de snap fallido, con `node=None`).

    `extra_cols`: {facility_id: {col: value}} — p.ej. current_resolutive/
    upgrade_candidate — se añaden a cada fila de esa facility.

    Clave de cache: ``<cache_dir>/<mode>/<cache_version>/<facility_id>.parquet``.
    `cache_version` debe incluir `profile_hash(mode, cfg)` (ver
    `scripts/run_routing.py`) además del cutoff de OSM/buffer/snap — así un
    cambio de perfil invalida el cache solo, sin borrar carpetas a mano. Un
    chunk cacheado que no contenga exactamente el universo de `demand_nodes`
    vigente se descarta y se recalcula.
    """
    cache_dir = Path(cache_dir) / mode / cache_version
    cache_dir.mkdir(parents=True, exist_ok=True)
    rev = _reverse_view(graph)
    expected_demand_ids = set(demand_nodes.keys())

    n_dijkstra = 0
    cache_hits = 0
    chunks = []
    t_start = time.time()
    for i, (fid, fnode) in enumerate(facility_nodes.items(), start=1):
        chunk_path = cache_dir / f"{fid}.parquet"
        if chunk_path.exists():
            cached = pd.read_parquet(chunk_path)
            if set(cached["demand_id"]) == expected_demand_ids and "routing_status" in cached.columns:
                chunks.append(cached)
                cache_hits += 1
                continue
            logger.warning("[%s] cache de %s no coincide con el universo/esquema vigente -- recalculando", mode, fid)

        dep_fac = facility_dept.get(fid)
        times: dict[int, float] = {}
        dists: dict[int, float] = {}
        if fnode in graph:
            t0 = time.time()
            times = nx.single_source_dijkstra_path_length(rev, fnode, weight="time_s")
            dists = nx.single_source_dijkstra_path_length(rev, fnode, weight="length")
            n_dijkstra += 2
            dt = time.time() - t0
        else:
            dt = 0.0

        rows = []
        n_routed = 0
        for did, dnode in demand_nodes.items():
            dep_dem = demand_dept.get(did)
            snap_ok = dnode is not None
            same_dept = snap_ok and dep_dem == dep_fac
            t = times.get(dnode) if (snap_ok and same_dept) else None
            reachable = t is not None
            status = st.classify_pair(snap_ok=snap_ok, same_department=bool(same_dept), reachable=reachable)
            n_routed += int(status == st.ROUTED)
            rows.append({
                "demand_id": did, "facility_id": fid, "mode": mode,
                "distance_m": dists.get(dnode) if reachable else None,
                "travel_time_min": (t / 60.0) if reachable else None,
                "reachable": reachable,
                "routing_status": status,
                "origin_node": dnode, "dest_node": fnode,
            })
        chunk = pd.DataFrame(rows)
        if extra_cols and fid in extra_cols:
            for col, val in extra_cols[fid].items():
                chunk[col] = val
        chunk.to_parquet(chunk_path)
        chunks.append(chunk)
        logger.info(
            "[%s] facility %d/%d (%s): Dijkstra en %.1fs, %d/%d demand points routed",
            mode, i, len(facility_nodes), fid, dt, n_routed, len(demand_nodes),
        )

    result = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    if extra_cols:
        for col in {c for d in extra_cols.values() for c in d}:
            if col not in result.columns:
                result[col] = None
    logger.info(
        "[%s] matriz completa: %d filas (%d facilities x %d demand), %d Dijkstra ejecutados, %d chunks de cache reutilizados, %.1fs total",
        mode, len(result), len(facility_nodes), len(demand_nodes), n_dijkstra, cache_hits, time.time() - t_start,
    )
    return result


def nearest_facility_multi_source(
    graph: nx.DiGraph,
    mode: str,
    facility_nodes: dict[str, int],
    demand_nodes: dict[str, int],
    node_to_facility: dict[int, str],
) -> pd.DataFrame:
    """Nearest facility (cualquier categoría) para cada demand point, con UN
    solo multi-source Dijkstra sobre el grafo invertido (no una matriz completa).

    Implementación propia con heapq (2026-09-11) en vez de
    ``nx.multi_source_dijkstra``: esa función devuelve, para CADA nodo
    alcanzable de un grafo de millones de nodos, la ruta completa (lista de
    nodos) desde su fuente — con ~1.6M nodos alcanzables eso son millones de
    listas de Python en memoria simultáneamente, y fue la causa real de un
    OOM-kill (`Killed: 9`) en esta máquina. Aquí se sigue el mismo algoritmo de
    Dijkstra pero solo se guardan 3 escalares por nodo (tiempo acumulado,
    distancia acumulada, facility de origen) — memoria O(nodos alcanzables),
    no O(nodos alcanzables × longitud de ruta).

    Solo recibe `demand_nodes` ya snapeados con éxito — el llamador debe
    añadir aparte las filas `snap_failed` para los demand points sin nodo
    (ver `scripts/run_routing.py`).
    """
    import heapq

    rev = _reverse_view(graph)
    sources = {n: fid for fid, n in facility_nodes.items() if n in graph}
    if not sources:
        return pd.DataFrame([
            {"demand_id": did, "facility_id": None, "mode": mode, "distance_m": None, "travel_time_min": None, "reachable": False}
            for did in demand_nodes
        ])

    t0 = time.time()
    dist_time: dict[int, float] = {}
    dist_len: dict[int, float] = {}
    source_of: dict[int, str] = {}
    pq: list[tuple[float, int]] = []
    for node, fid in sources.items():
        if node not in dist_time:
            dist_time[node] = 0.0
            dist_len[node] = 0.0
            source_of[node] = fid
            heapq.heappush(pq, (0.0, node))

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist_time.get(u, float("inf")):
            continue
        for v, edge_data in rev.adj[u].items():
            nd = d + edge_data.get("time_s", 0.0)
            if nd < dist_time.get(v, float("inf")):
                dist_time[v] = nd
                dist_len[v] = dist_len[u] + edge_data.get("length", 0.0)
                source_of[v] = source_of[u]
                heapq.heappush(pq, (nd, v))

    logger.info(
        "[%s] multi-source Dijkstra propio (nearest-any) desde %d facilities en %.1fs, %d nodos alcanzados",
        mode, len(sources), time.time() - t0, len(dist_time),
    )

    rows = []
    for did, dnode in demand_nodes.items():
        t = dist_time.get(dnode)
        if t is None:
            rows.append({"demand_id": did, "facility_id": None, "mode": mode, "distance_m": None, "travel_time_min": None, "reachable": False})
            continue
        rows.append({
            "demand_id": did, "facility_id": source_of[dnode], "mode": mode,
            "distance_m": dist_len[dnode], "travel_time_min": t / 60.0, "reachable": True,
        })
    return pd.DataFrame(rows)
