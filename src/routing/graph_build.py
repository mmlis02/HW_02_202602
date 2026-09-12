"""Construcción del grafo dirigido (NetworkX) por perfil, a partir de la red
combinada extraída de OSM (`osm_extract.py`).

Un `networkx.DiGraph` por perfil (car/bike/foot), con peso `time_s` (segundos,
usado para el routing) y `length` (metros, para distancia). Se cachea a pickle
por perfil — reconstruir el grafo desde los edges ya extraídos es barato, pero
evitar repetirlo en cada corrida ahorra minutos.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from src.routing.profiles import make_edge_weight_fn

logger = logging.getLogger(__name__)

_TAG_COLS = [
    "highway", "oneway", "maxspeed", "surface", "access", "bicycle", "foot",
    "footway", "motor_vehicle", "junction", "service", "tracktype",
]


def build_graph(edges_df, mode: str, cache_path: str | Path | None = None, cfg: dict | None = None) -> nx.DiGraph:
    """Construye el DiGraph del perfil `mode` ("car"/"bike"/"foot").

    `edges_df` puede ser un DataFrame ya cargado, o un `callable` sin
    argumentos que lo cargue perezosamente (p.ej. `lambda: pd.read_parquet(...)`)
    — importante en esta máquina con RAM limitada: si el grafo ya está
    cacheado, `edges_df` **nunca se materializa** (evita mantener ~3.47M filas
    en memoria solo para descartarlas sin usarlas; esto causó un OOM-kill real
    el 2026-09-11 al mantener `edges_df` vivo durante todo el bucle de perfiles
    mientras además se cargaba el grafo cacheado de bike/foot).

    `cache_path` debe incluir el hash de perfil vigente en su nombre (ver
    `src/routing/profiles.py::profile_hash` y `scripts/run_routing.py`) — así
    un cambio de velocidades/reglas invalida el cache automáticamente en vez
    de depender de borrar la carpeta a mano.

    Si dos edges compiten por el mismo (u,v) dirigido, se conserva el de menor
    `time_s` (ruta más rápida entre ellas) — simplificación documentada, no
    inventa una vía nueva.
    """
    cache_path = Path(cache_path) if cache_path else None
    if cache_path and cache_path.exists():
        logger.info("[%s] grafo ya cacheado -- reutilizando %s (edges_df NO se carga)", mode, cache_path)
        with open(cache_path, "rb") as fh:
            return pickle.load(fh)

    if callable(edges_df):
        edges_df = edges_df()

    weight_fn = make_edge_weight_fn(mode, cfg)
    tag_cols = [c for c in _TAG_COLS if c in edges_df.columns]

    G = nx.DiGraph()
    n_kept = 0
    n_excluded = 0
    for row in edges_df.itertuples(index=False):
        row_d = row._asdict()
        tags = {c: row_d.get(c) for c in tag_cols}
        length_m = row_d.get("length") or 0.0
        if length_m <= 0:
            n_excluded += 1
            continue
        w = weight_fn(tags, length_m)
        if w is None:
            n_excluded += 1
            continue
        u, v = row_d["u"], row_d["v"]
        if w.forward:
            if not G.has_edge(u, v) or G[u][v]["time_s"] > w.time_s:
                G.add_edge(u, v, time_s=w.time_s, length=w.length_m, speed_kmh=w.speed_kmh)
        if w.backward:
            if not G.has_edge(v, u) or G[v][u]["time_s"] > w.time_s:
                G.add_edge(v, u, time_s=w.time_s, length=w.length_m, speed_kmh=w.speed_kmh)
        n_kept += 1

    logger.info(
        "[%s] grafo construido: %d nodos, %d aristas dirigidas (%d vías OSM usadas, %d excluidas por el perfil)",
        mode, G.number_of_nodes(), G.number_of_edges(), n_kept, n_excluded,
    )
    largest_cc = max(nx.weakly_connected_components(G), key=len) if G.number_of_nodes() else set()
    logger.info("[%s] componente conexa más grande: %d/%d nodos (%.1f%%)", mode, len(largest_cc), G.number_of_nodes(), 100 * len(largest_cc) / max(G.number_of_nodes(), 1))

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "wb") as fh:
            pickle.dump(G, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return G


def build_all_profiles(edges_df: pd.DataFrame, cache_dir: str | Path, cfg: dict | None = None) -> dict[str, nx.DiGraph]:
    from src.routing.profiles import profile_hash

    cache_dir = Path(cache_dir)
    return {
        mode: build_graph(edges_df, mode, cache_dir / f"graph_{mode}_{profile_hash(mode, cfg)}.pkl", cfg=cfg)
        for mode in ("car", "bike", "foot")
    }
