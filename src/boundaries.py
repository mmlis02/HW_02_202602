"""Límites administrativos (IGN) — Fase 1.

Módulo añadido respecto al árbol original del enunciado (justificación en
README.md): ni `facilities.py` ni `demand.py` son el lugar natural para cargar,
derivar y recortar los límites oficiales que ambos necesitan (validación de
distrito declarado, agregación posterior). Fuente: IGN vía datosabiertos.gob.pe
(ver docs/00_sources_inspection.md).

No hay un shapefile de **provincias** publicado directamente — se deriva
disolviendo el shapefile de distritos por (CODDEP, CODPROV), que son campos
reales del shapefile del IGN, no inventados.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import geopandas as gpd

from src.acquisition import extract_zip_if_needed
from src.config import get_department_codes, get_path, load_config

logger = logging.getLogger(__name__)


def load_ign_departments(zip_path: str | Path, extract_dir: str | Path) -> gpd.GeoDataFrame:
    extract_zip_if_needed(zip_path, extract_dir)
    shp = next(Path(extract_dir).glob("*.shp"))
    gdf = gpd.read_file(shp)
    return gdf


def load_ign_districts(zip_path: str | Path, extract_dir: str | Path) -> gpd.GeoDataFrame:
    extract_zip_if_needed(zip_path, extract_dir)
    shp = next(Path(extract_dir).glob("*.shp"))
    gdf = gpd.read_file(shp)
    return gdf


def derive_provinces(districts_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Disuelve distritos por (CODDEP, CODPROV) -> polígono de provincia.

    CODDEP, CODPROV, PROVINCIA, DEPARTAMEN son campos reales del shapefile de
    distritos del IGN (ver docs/00_sources_inspection.md) — no se inventa nada,
    solo se agrega geometría.
    """
    prov = districts_gdf.dissolve(by=["CODDEP", "CODPROV"], as_index=False, aggfunc="first")
    prov["UBIGEO_PROV"] = prov["CODDEP"].astype(str) + prov["CODPROV"].astype(str)
    cols = ["CODDEP", "DEPARTAMEN", "CODPROV", "PROVINCIA", "UBIGEO_PROV", "geometry"]
    return prov[cols]


def filter_to_study_departments(gdf: gpd.GeoDataFrame, dept_codes: list[str], coddep_col: str = "CODDEP") -> gpd.GeoDataFrame:
    return gdf[gdf[coddep_col].isin(dept_codes)].copy().reset_index(drop=True)


def build_study_boundaries(cfg: dict[str, Any] | None = None) -> dict[str, gpd.GeoDataFrame]:
    """Devuelve {'departments','provinces','districts'} recortados a Tumbes/Cusco/Amazonas."""
    cfg = cfg or load_config()
    raw_dir = get_path("data_raw", cfg)
    ign = cfg["acquisition"]["ign_limites"]
    dep_codes = list(get_department_codes(cfg).values())

    dep_gdf = load_ign_departments(
        raw_dir / "ign" / ign["departamentos_resource"], raw_dir / "ign" / "extracted_dep"
    )
    dist_gdf = load_ign_districts(
        raw_dir / "ign" / ign["distritos_resource"], raw_dir / "ign" / "extracted_dist"
    )
    prov_gdf = derive_provinces(dist_gdf)

    return {
        "departments": filter_to_study_departments(dep_gdf, dep_codes, "CODDEP"),
        "provinces": filter_to_study_departments(prov_gdf, dep_codes, "CODDEP"),
        "districts": filter_to_study_departments(dist_gdf, dep_codes, "CODDEP"),
        "districts_national": dist_gdf,  # para el chequeo de UBIGEO nacional (regla 4), si hiciera falta
    }
