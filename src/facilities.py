"""Oferta — RENIPRESS/SUSALUD. Fase 1.

Procesa el CSV crudo de RENIPRESS: normaliza categorías y estado operativo de
forma **explícita** (ver `CATEGORY_MAP`, `ACTIVE_STATUS_VALUES` — construidos a
partir del catálogo real observado en el archivo, documentado en
docs/00_sources_inspection.md), aplica las 6 reglas de validación de
`src/validation.py` y marca qué establecimientos son **resolutivos**.

Columnas reales de `RENIPRESS_31-08-2026.csv` (verificadas por inspección, no
inventadas): separador `;`, encoding `utf-8-sig` (BOM), 31 columnas. Las que usa
este módulo: `COD_IPRESS` (clave única, 0 duplicados a nivel nacional),
`CATEGORIA`, `ESTADO`, `DEPARTAMENTO`/`PROVINCIA`/`DISTRITO`/`UBIGEO`,
`NORTE` (=latitud), `ESTE` (=longitud).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src import validation as val
from src.config import get_department_names, get_path, load_config

logger = logging.getLogger(__name__)

# --- Normalización explícita de categoría (regla del enunciado, config.md §3) ---
# Catálogo real observado en RENIPRESS_31-08-2026.csv (36 004 registros nacionales):
# {'I-1','I-2','I-3','I-4','II-1','II-2','II-E','III-1','III-2','III-E','0'}.
# Las 10 primeras ya vienen en formato canónico; "0" es el valor que usa RENIPRESS
# para "sin categoría asignada" (8552/36004 registros). Se documenta explícitamente
# en vez de asumir variantes de texto que no se observaron en el archivo real.
_CANONICAL = {"I-1", "I-2", "I-3", "I-4", "II-1", "II-2", "II-E", "III-1", "III-2", "III-E"}
_NO_CATEGORY_RAW = {"0", "", "NAN", "NONE", "SIN CATEGORIA", "SIN CATEGORÍA"}


def normalize_category(raw: Any) -> str:
    """Mapea un valor crudo de CATEGORIA a una etiqueta canónica.

    - Si ya es una de las 10 categorías canónicas (tolerando espacios extra
      alrededor del guion, p. ej. "II - 1"), se devuelve normalizada.
    - Si es uno de los valores observados de "sin categoría" (el más común: "0"),
      se devuelve "SIN_CATEGORIA" — se conserva en el dataset, nunca resolutiva.
    - Cualquier otro valor no visto en la inspección real se marca "DESCONOCIDA"
      (no resolutiva por defecto) y se registra — no se asume qué significa.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "SIN_CATEGORIA"
    s = str(raw).strip().upper()
    s_collapsed = re.sub(r"\s*-\s*", "-", s)  # "II - 1" -> "II-1"
    if s_collapsed in _CANONICAL:
        return s_collapsed
    if s in _NO_CATEGORY_RAW or s_collapsed in _NO_CATEGORY_RAW:
        return "SIN_CATEGORIA"
    logger.warning("CATEGORIA no reconocida en la inspección real: %r -> DESCONOCIDA", raw)
    return "DESCONOCIDA"


# --- Normalización explícita de estado operativo (config.md §3 / §6 regla activo) ---
# Catálogo real observado en ESTADO (36 004 registros nacionales):
#   ACTIVO (26901), CIERRE TEMPORAL DE OFICIO (4378), BAJA DEFINITIVA (3470),
#   BAJA PROVISIONAL (907), BAJA DEFINITIVA DE OFICIO (201),
#   BAJA PROVISIONAL DE OFICIO (119), CIERRE TEMPORAL DE PARTE (28).
# Solo "ACTIVO" representa un establecimiento operando hoy. Los "CIERRE TEMPORAL*"
# están cerrados AHORA (aunque no de forma definitiva) -> no pueden atender una
# emergencia en este momento -> se tratan como NO activos, igual que las "BAJA*".
ACTIVE_STATUS_VALUES = {"ACTIVO"}


def is_active(estado_raw: Any) -> bool:
    if estado_raw is None or (isinstance(estado_raw, float) and pd.isna(estado_raw)):
        return False
    return str(estado_raw).strip().upper() in ACTIVE_STATUS_VALUES


def load_renipress_raw(path: str, encoding: str, sep: str) -> pd.DataFrame:
    return pd.read_csv(path, sep=sep, encoding=encoding, dtype=str, low_memory=False)


def build_facilities(cfg: dict[str, Any] | None = None, districts_gdf: gpd.GeoDataFrame | None = None) -> dict[str, Any]:
    """Lee RENIPRESS crudo de disco y delega en :func:`process_facilities`."""
    cfg = cfg or load_config()
    acq = cfg["acquisition"]["renipress"]
    raw_path = get_path("data_raw", cfg) / "renipress" / acq["resource"]
    df = load_renipress_raw(str(raw_path), encoding=acq["encoding"], sep=acq["sep"])
    return process_facilities(df, cfg, districts_gdf=districts_gdf)


def process_facilities(df: pd.DataFrame, cfg: dict[str, Any], districts_gdf: gpd.GeoDataFrame | None = None) -> dict[str, Any]:
    """Pipeline completo dado un DataFrame RENIPRESS ya cargado (mismas columnas
    crudas: DEPARTAMENTO, COD_IPRESS, CATEGORIA, ESTADO, UBIGEO, NORTE, ESTE, ...).

    Separado de :func:`build_facilities` para poder testear la orquestación
    completa (normalización -> las 6 reglas -> resolutivo) con datos sintéticos en
    memoria, sin necesitar el CSV real de RENIPRESS en disco.

    Devuelve un dict con: ``gdf`` (GeoDataFrame final), ``quality_outcomes``
    (lista de `RuleOutcome`), ``audit_detail`` (DataFrame por registro afectado).
    """
    dept_names = {n.upper() for n in get_department_names(cfg)}
    df = df[df["DEPARTAMENTO"].str.upper().isin(dept_names)].reset_index(drop=True)
    logger.info("RENIPRESS: %d registros en el ámbito de estudio (%s)", len(df), ", ".join(sorted(dept_names)))

    vcfg = cfg["validation"]["facilities"]

    # Regla 5 primero (duplicados), sobre el DataFrame crudo, para que el resto de
    # reglas trabaje ya sobre índices estables (sin reindexar tras un drop).
    o5, exact_drop_mask, conflicting_mask = val.check_duplicate_key(df, "COD_IPRESS", vcfg["duplicate_facility_code"])
    if exact_drop_mask.any():
        keep_mask = ~exact_drop_mask
        df = df.loc[keep_mask].reset_index(drop=True)
        conflicting_mask = conflicting_mask.loc[keep_mask].reset_index(drop=True)

    df["lon"] = pd.to_numeric(df["ESTE"], errors="coerce")
    df["lat"] = pd.to_numeric(df["NORTE"], errors="coerce")
    df["CATEGORIA_NORM"] = df["CATEGORIA"].map(normalize_category)
    df["is_active"] = df["ESTADO"].map(is_active)

    geometry = [Point(xy) if pd.notna(xy[0]) and pd.notna(xy[1]) else None for xy in zip(df["lon"], df["lat"])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

    bbox = cfg["peru_bbox"]
    outcomes: list[val.RuleOutcome] = [o5]
    flags: dict[str, pd.Series] = {"qc_duplicate_conflicting": conflicting_mask}

    alarms: list[dict[str, Any]] = []

    o1, missing_mask = val.check_coord_missing(gdf, "lon", "lat", vcfg["coord_missing"])
    outcomes.append(o1)
    flags["qc_coord_missing"] = missing_mask
    a = val.check_alarm(o1.n_affected, len(gdf), vcfg["coord_missing"]["max_missing_pct_alarm"], "facilities.coord_missing")
    if a:
        alarms.append(a)

    o2, out_of_bbox_mask = val.check_coord_out_of_bbox(gdf, "lon", "lat", bbox, vcfg["coord_out_of_bbox"], missing_mask)
    outcomes.append(o2)
    flags["qc_coord_out_of_bbox"] = out_of_bbox_mask
    a = val.check_alarm(o2.n_affected, len(gdf), vcfg["coord_out_of_bbox"]["max_out_of_bbox_pct_alarm"], "facilities.coord_out_of_bbox")
    if a:
        alarms.append(a)

    o3, corrected_mask, ambiguous_mask, gdf = val.check_swapped_latlon(
        gdf, "lon", "lat", bbox, vcfg["swapped_latlon"], out_of_bbox_mask,
        districts_gdf=districts_gdf, declared_ubigeo_col="UBIGEO",
        containment_buffer_m=vcfg["point_outside_declared_district"]["containment_buffer_m"],
        metric_crs=cfg["crs"]["metric_clip"],
    )
    outcomes.append(o3)
    flags["qc_latlon_swap_corrected"] = corrected_mask
    flags["qc_latlon_swap_ambiguous"] = ambiguous_mask

    excluded_from_routing = missing_mask | (out_of_bbox_mask & ~corrected_mask)
    usable_coords = ~missing_mask & (~out_of_bbox_mask | corrected_mask)

    if districts_gdf is not None:
        o4, mismatch_mask = val.check_point_outside_declared_district(
            gdf, districts_gdf, "UBIGEO", vcfg["point_outside_declared_district"], usable_coords,
            metric_crs=cfg["crs"]["metric_clip"],
        )
    else:
        o4 = val.RuleOutcome("4. punto fuera de su distrito declarado", 0, "n/a (sin límites IGN)", 0, 0, 0, "No se proporcionaron límites administrativos.")
        mismatch_mask = pd.Series(False, index=gdf.index)
    outcomes.append(o4)
    flags["qc_district_mismatch"] = mismatch_mask

    o6 = val.check_encoding([gdf["NOMBRE"], gdf["DIRECCION"], gdf["DISTRITO"], gdf["PROVINCIA"]], vcfg["encoding_check"], cfg["acquisition"]["renipress"]["encoding"])
    outcomes = [o1, o2, o3, o4, o5, o6]  # orden de reporte 1..6

    gdf["qc_excluded_from_routing"] = excluded_from_routing.values
    # CORREGIDO (auditoría 2026-09-11): antes se calculaba y auditaba pero se perdía
    # al armar el output final. Política keep_warning sin cambios: no se toca
    # distrito/provincia/departamento, solo se conserva la bandera.
    gdf["qc_district_mismatch"] = mismatch_mask.values
    gdf["is_resolutive"] = gdf["is_active"] & gdf["CATEGORIA_NORM"].isin(cfg["facilities"]["resolutive_categories"])
    gdf["usable_for_routing"] = gdf["is_resolutive"] & ~gdf["qc_excluded_from_routing"]

    audit = val.build_audit_detail(gdf, "COD_IPRESS", flags, dataset_name="facilities")

    keep_cols = [
        "COD_IPRESS", "NOMBRE", "DEPARTAMENTO", "PROVINCIA", "DISTRITO", "UBIGEO",
        "CATEGORIA", "CATEGORIA_NORM", "ESTADO", "is_active", "is_resolutive",
        "usable_for_routing", "qc_excluded_from_routing", "qc_district_mismatch",
        "lon", "lat", "geometry",
    ]
    gdf_final = gdf[keep_cols].copy()

    return {"gdf": gdf_final, "quality_outcomes": outcomes, "audit_detail": audit, "n_raw_in_scope": len(df), "alarms": alarms}
