"""Extracción del extracto vial de OSM para Tumbes, Cusco y Amazonas.

**Adaptación documentada respecto al plan original**: se procesa **por
departamento**, no con un único recorte de la unión de los 3 + buffer. Un
primer intento con la unión buffered (~201 600 km², ~16% de Perú) en un solo
paso de `pyrosm.get_network()` agotó la RAM de esta máquina (8 GB, ya bajo
presión — ver `docs/01_routing_decision.md`) y forzó al sistema a crecer
archivos de swap hasta dejar ~1.2 GB libres en disco; se abortó el proceso
antes de agotarlo por completo. Procesar departamento por departamento (con su
propio buffer) y liberar memoria explícitamente entre uno y otro evita
repetir eso — es la instrucción del enunciado ("procesa por departamento... si
eso reduce de manera material el consumo") aplicada porque el bloqueo fue real
y verificable, no una elección arbitraria.

Cada extracción por departamento se cachea en `data/cache/osm_network/` para
no volver a tocar el PBF de 244 MB en re-ejecuciones.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

logger = logging.getLogger(__name__)

_EDGE_COLS = [
    "id", "u", "v", "highway", "oneway", "maxspeed", "surface", "access",
    "bicycle", "foot", "footway", "motor_vehicle", "junction", "service",
    "tracktype", "length",
]
_NODE_COLS = ["id", "lon", "lat"]


def extract_department_network(
    pbf_path: str | Path,
    department_geom_4326,
    buffer_km: float,
    cache_dir: str | Path,
    dept_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extrae nodos/edges de OSM dentro de un departamento + buffer (km).

    Cachea en ``<cache_dir>/<dept_name>_{nodes,edges}.parquet``; si ya existen,
    no se vuelve a tocar el PBF ni a llamar a pyrosm.
    """
    cache_dir = Path(cache_dir)
    nodes_path = cache_dir / f"{dept_name}_nodes.parquet"
    edges_path = cache_dir / f"{dept_name}_edges.parquet"
    if nodes_path.exists() and edges_path.exists():
        logger.info("[%s] OSM ya extraído -- reutilizando cache (%s)", dept_name, edges_path)
        return pd.read_parquet(nodes_path), pd.read_parquet(edges_path)

    from pyrosm import OSM  # import perezoso: evita cargarlo si todo está cacheado

    geom_m = gpd.GeoSeries([department_geom_4326], crs="EPSG:4326").to_crs("EPSG:32718")
    geom_buffered = geom_m.buffer(buffer_km * 1000).to_crs("EPSG:4326").iloc[0]

    logger.info("[%s] extrayendo de %s (buffer %d km) -- puede tardar 1-3 min...", dept_name, pbf_path, buffer_km)
    osm = OSM(str(pbf_path), bounding_box=geom_buffered)
    nodes, edges = osm.get_network(network_type="all", nodes=True)
    del osm
    gc.collect()

    edge_cols = [c for c in _EDGE_COLS if c in edges.columns]
    edges_small = pd.DataFrame(edges[edge_cols])
    edges_small["geometry_wkb"] = edges.geometry.to_wkb()
    del edges
    gc.collect()

    node_cols = [c for c in _NODE_COLS if c in nodes.columns]
    nodes_small = pd.DataFrame(nodes[node_cols])
    del nodes
    gc.collect()

    cache_dir.mkdir(parents=True, exist_ok=True)
    nodes_small.to_parquet(nodes_path)
    edges_small.to_parquet(edges_path)
    logger.info("[%s] OK: %d nodos, %d edges -> cache", dept_name, len(nodes_small), len(edges_small))
    return nodes_small, edges_small


def merge_department_networks(all_nodes: list[pd.DataFrame], all_edges: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combina listas de nodos/edges por departamento en una sola red.

    Nodos: únicos por `id` (el ID real de nodo OSM). Edges: únicos por
    `(id, u, v)` — **no** por `id` solo, porque `id` en `edges` es el ID de la
    WAY de OSM, no del segmento; una way con N segmentos aporta N filas que
    comparten el mismo `id` (ver CORRECCIÓN 2026-09-11 en `build_combined_network`).
    """
    nodes_df = pd.concat(all_nodes, ignore_index=True).drop_duplicates(subset="id").reset_index(drop=True)
    edges_df = pd.concat(all_edges, ignore_index=True).drop_duplicates(subset=["id", "u", "v"]).reset_index(drop=True)
    return nodes_df, edges_df


def combined_network_cache_paths(cache_dir: str | Path) -> tuple[Path, Path]:
    cache_dir = Path(cache_dir)
    return cache_dir / "combined_nodes.parquet", cache_dir / "combined_edges.parquet"


def load_combined_nodes(cache_dir: str | Path) -> pd.DataFrame:
    """Lee SOLO los nodos combinados cacheados (liviano, necesario para snapping
    incluso cuando los 3 grafos ya están cacheados y no hace falta `edges_df`)."""
    nodes_path, _ = combined_network_cache_paths(cache_dir)
    return pd.read_parquet(nodes_path)


def load_combined_edges(cache_dir: str | Path) -> pd.DataFrame:
    """Lee los edges combinados cacheados. Pensada para pasarse como *lazy
    loader* a `build_graph`, para no materializarlos si el grafo de ese perfil
    ya está cacheado (ver graph_build.py)."""
    _, edges_path = combined_network_cache_paths(cache_dir)
    return pd.read_parquet(edges_path)


def build_combined_network(cfg: dict[str, Any], pbf_path: str | Path, cache_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extrae los 3 departamentos por separado y los combina (dedup por nodo/edge id).

    Devuelve (nodes_df, edges_df) combinados, y también los cachea combinados en
    ``<cache_dir>/combined_{nodes,edges}.parquet``.
    """
    cache_dir = Path(cache_dir)
    combined_nodes_path = cache_dir / "combined_nodes.parquet"
    combined_edges_path = cache_dir / "combined_edges.parquet"
    if combined_nodes_path.exists() and combined_edges_path.exists():
        logger.info("Red combinada ya cacheada -- reutilizando (%s)", combined_edges_path)
        return pd.read_parquet(combined_nodes_path), pd.read_parquet(combined_edges_path)

    departments = gpd.read_file(cache_dir.parent / "processed" / "departments.gpkg") if (cache_dir.parent / "processed" / "departments.gpkg").exists() else None
    if departments is None:
        from src.boundaries import build_study_boundaries
        departments = build_study_boundaries(cfg)["departments"]

    buffer_km = cfg["routing"]["clip_buffer_km"]
    all_nodes, all_edges = [], []
    for _, row in departments.iterrows():
        dept_name = row["DEPARTAMEN"]
        n, e = extract_department_network(pbf_path, row.geometry, buffer_km, cache_dir, dept_name)
        all_nodes.append(n)
        all_edges.append(e)
        gc.collect()

    nodes_df, edges_df = merge_department_networks(all_nodes, all_edges)
    del all_nodes, all_edges
    gc.collect()

    cache_dir.mkdir(parents=True, exist_ok=True)
    nodes_df.to_parquet(combined_nodes_path)
    edges_df.to_parquet(combined_edges_path)
    logger.info("Red combinada: %d nodos, %d edges (tras deduplicar solapes de buffer)", len(nodes_df), len(edges_df))
    return nodes_df, edges_df
