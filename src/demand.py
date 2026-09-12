"""Demanda — SIGMED/MINEDU Centros Poblados. Fase 1 y 2 (muestreo aquí; Fase 2 = routing).

Columnas reales de `CP_P.shp` (verificadas contra el Diccionario oficial
`DICCIONARIO_CP_P.doc`, dentro de `CP_MED.zip`; no inventadas):
`UBIGEO` (distrito, 6 díg., INEI), `DEP`/`PROV`/`DIST` (nombres), `CODCP` (clave
única, 6 díg., 0 duplicados nacional), `NOMCP`/`MNOMCP` (nombre), `CAPITAL`
(0/1/2/3), `CON_IE`, `NIVEL`, `CPINEI`/`CPINEI2` (empate con INEI — útil en
Fase 3 para población), `FUENTE_G`, `Z` (altitud), `XGD`=longitud,
`YGD`=latitud (grados decimales), `geometry` (Point, EPSG:4326). **No trae
población** — confirmado por inspección del diccionario y de las columnas
reales; se deja pendiente para Fase 3 (unión con INEI), tal como ya declaraba
`config.md`.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from src import validation as val
from src.acquisition import extract_zip_if_needed
from src.config import get_department_names, get_path, load_config

logger = logging.getLogger(__name__)


def load_sigmed_raw(zip_path: str, extract_dir: str) -> gpd.GeoDataFrame:
    from pathlib import Path

    extract_zip_if_needed(zip_path, extract_dir)
    shp = next(Path(extract_dir).glob("*.shp"))
    return gpd.read_file(shp)


def _largest_remainder_round(raw: pd.Series, total: int) -> pd.Series:
    """Redondea `raw` (floats no-negativos) a enteros que suman exactamente `total`."""
    floor_vals = np.floor(raw).astype(int)
    remainder = int(total - floor_vals.sum())
    frac = (raw - floor_vals).sort_values(ascending=False)
    alloc = floor_vals.copy()
    for idx in frac.index[:max(remainder, 0)]:
        alloc.loc[idx] += 1
    return alloc


def capacity_constrained_proportional_allocation(sizes: pd.Series, n_target: int) -> pd.Series:
    """Cuota por estrato ∝ `sizes`, sin exceder la capacidad (`sizes`) de cada estrato.

    Water-filling: los estratos cuya cuota proporcional excedería su propio
    tamaño se "saturan" (cuota = su tamaño completo) y el remanente se
    reparte proporcionalmente entre los estratos no saturados. Determinista
    dados `sizes` y `n_target` (no usa aleatoriedad).
    """
    sizes = sizes.astype(float)
    quota = pd.Series(0, index=sizes.index, dtype=int)
    free = pd.Series(True, index=sizes.index)
    remaining = int(n_target)

    while remaining > 0 and free.any():
        capacity_free = sizes[free]
        weight_sum = capacity_free.sum()
        if weight_sum <= 0:
            break
        raw = capacity_free / weight_sum * remaining
        would_saturate = raw >= capacity_free
        if not would_saturate.any():
            alloc = _largest_remainder_round(raw, remaining)
            quota.loc[alloc.index] += alloc
            remaining = 0
            break
        sat_idx = capacity_free.index[would_saturate]
        quota.loc[sat_idx] = sizes.loc[sat_idx].astype(int)
        remaining -= int(sizes.loc[sat_idx].sum())
        free.loc[sat_idx] = False

    return quota


#: Columnas de diseño muestral persistidas (auditoría 2026-09-11). Son pesos del
#: DISEÑO MUESTRAL DE CENTROS POBLADOS (probabilidad de que ese asentamiento entre
#: a la muestra de 5000), NO pesos poblacionales — no se usan todavía para
#: población ponderada, cobertura, medias ni Gini (eso es Fase 3, con INEI).
DESIGN_WEIGHT_COLS = ["stratum_n", "stratum_sample_n", "inclusion_prob", "design_weight"]


def stratified_sample_by_district(gdf: gpd.GeoDataFrame, district_col: str, n_target: int, seed: int) -> gpd.GeoDataFrame:
    """Muestreo estratificado por distrito, cuota ∝ nº de centros poblados del distrito.

    NOTA metodológica (ver config.md `demand.sampling` y docs/00_sources_inspection.md):
    el esquema declarado en config.md pide ponderar por `estimated_population`, pero
    SIGMED no trae población y la fuente INEI se integra recién en Fase 3. Por eso
    este muestreo de Fase 1 usa como medida de tamaño el CONTEO de centros poblados
    por distrito (una cantidad real, no inventada) en vez de población. Es un
    muestreo PROVISIONAL: en Fase 3, con población ya unida, se reemplaza por el
    diseño ponderado por población declarado en config.md (Horvitz-Thompson), y los
    resultados de accesibilidad de Fase 1/2 basados en esta muestra se re-evalúan.

    Adjunta al resultado ``stratum_n``, ``stratum_sample_n``, ``inclusion_prob`` y
    ``design_weight`` (ver ``DESIGN_WEIGHT_COLS``) — deterministas a partir de
    (distrito, cuota, conteo), no requieren población.
    """
    rng = np.random.default_rng(seed)
    counts = gdf.groupby(district_col).size()
    quotas = capacity_constrained_proportional_allocation(counts, n_target)

    chosen_idx: list[Any] = []
    for district, quota in quotas.items():
        pool = gdf.index[gdf[district_col] == district]
        if quota >= len(pool):
            chosen_idx.extend(pool.tolist())
        else:
            chosen_idx.extend(rng.choice(pool.to_numpy(), size=int(quota), replace=False).tolist())

    out = gdf.loc[sorted(chosen_idx)].reset_index(drop=True)
    out["stratum_n"] = out[district_col].map(counts).astype(int)
    out["stratum_sample_n"] = out[district_col].map(quotas).astype(int)
    out["inclusion_prob"] = out["stratum_sample_n"] / out["stratum_n"]
    out["design_weight"] = 1.0 / out["inclusion_prob"]
    return out


def sample_if_needed(gdf: gpd.GeoDataFrame, district_col: str, max_points: int, seed: int) -> tuple[gpd.GeoDataFrame, bool]:
    """Aplica el muestreo SOLO si `len(gdf) > max_points`; si no, no muestrea.

    Cuando no hace falta muestrear, el "diseño" es un censo del pool usable:
    inclusion_prob=1.0, design_weight=1.0 para todos (misma semántica de columnas
    en ambos casos, ver DESIGN_WEIGHT_COLS).
    """
    if len(gdf) > max_points:
        return stratified_sample_by_district(gdf, district_col, max_points, seed), True

    out = gdf.copy()
    counts = out.groupby(district_col).size()
    out["stratum_n"] = out[district_col].map(counts).astype(int)
    out["stratum_sample_n"] = out["stratum_n"]
    out["inclusion_prob"] = 1.0
    out["design_weight"] = 1.0
    return out, False


def build_demand(cfg: dict[str, Any] | None = None, districts_gdf: gpd.GeoDataFrame | None = None) -> dict[str, Any]:
    """Lee el shapefile SIGMED de disco y delega en :func:`process_demand`."""
    cfg = cfg or load_config()
    sig = cfg["acquisition"]["sigmed_centros_poblados"]
    raw_dir = get_path("data_raw", cfg)
    zip_path = raw_dir / "sigmed" / sig["resource"]
    extract_dir = raw_dir / "sigmed" / "extracted"

    gdf = load_sigmed_raw(str(zip_path), str(extract_dir))
    return process_demand(gdf, cfg, districts_gdf=districts_gdf)


def process_demand(gdf: gpd.GeoDataFrame, cfg: dict[str, Any], districts_gdf: gpd.GeoDataFrame | None = None) -> dict[str, Any]:
    """Pipeline completo dado un GeoDataFrame SIGMED ya cargado (mismas columnas
    crudas: DEP, CODCP, UBIGEO, XGD, YGD, CPINEI, ...).

    Separado de :func:`build_demand` para poder testear la orquestación completa
    (filtro de ámbito -> las 6 reglas -> muestreo -> pesos de diseño) con datos
    sintéticos en memoria, sin necesitar el shapefile real de SIGMED en disco.
    """
    n_national = len(gdf)

    dept_names = {n.upper() for n in get_department_names(cfg)}
    gdf = gdf[gdf["DEP"].str.upper().isin(dept_names)].reset_index(drop=True)
    n_in_scope = len(gdf)
    logger.info("SIGMED: %d/%d centros poblados en el ámbito de estudio", n_in_scope, n_national)

    vcfg = cfg["validation"]["demand"]
    bbox = cfg["peru_bbox"]
    outcomes: list[val.RuleOutcome] = []
    flags: dict[str, pd.Series] = {}

    o5, exact_drop_mask, conflicting_mask = val.check_duplicate_key(gdf.drop(columns="geometry"), "CODCP", vcfg["duplicate_facility_code"])
    if exact_drop_mask.any():
        keep = ~exact_drop_mask
        gdf = gdf.loc[keep].reset_index(drop=True)
        conflicting_mask = conflicting_mask.loc[keep].reset_index(drop=True)
    outcomes.append(o5)
    flags["qc_duplicate_conflicting"] = conflicting_mask

    alarms: list[dict[str, Any]] = []

    o1, missing_mask = val.check_coord_missing(gdf, "XGD", "YGD", vcfg["coord_missing"])
    outcomes.append(o1)
    flags["qc_coord_missing"] = missing_mask
    a = val.check_alarm(o1.n_affected, len(gdf), vcfg["coord_missing"]["max_missing_pct_alarm"], "demand.coord_missing")
    if a:
        alarms.append(a)

    o2, out_of_bbox_mask = val.check_coord_out_of_bbox(gdf, "XGD", "YGD", bbox, vcfg["coord_out_of_bbox"], missing_mask)
    outcomes.append(o2)
    flags["qc_coord_out_of_bbox"] = out_of_bbox_mask
    a = val.check_alarm(o2.n_affected, len(gdf), vcfg["coord_out_of_bbox"]["max_out_of_bbox_pct_alarm"], "demand.coord_out_of_bbox")
    if a:
        alarms.append(a)

    o3, corrected_mask, ambiguous_mask, gdf = val.check_swapped_latlon(
        gdf, "XGD", "YGD", bbox, vcfg["swapped_latlon"], out_of_bbox_mask,
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

    o6 = val.check_encoding([gdf["NOMCP"], gdf["DIST"], gdf["PROV"]], vcfg.get("encoding_check", {"max_mojibake_pct_alarm": 1.0, "action": "keep_warning"}), cfg["acquisition"]["sigmed_centros_poblados"].get("encoding", "utf-8"))
    outcomes = [o1, o2, o3, o4, o5, o6]  # orden de reporte 1..6

    gdf["qc_excluded_from_routing"] = excluded_from_routing.values
    # CORREGIDO (auditoría 2026-09-11): se calculaba y auditaba pero no llegaba al
    # output final. keep_warning sin cambios: no se toca distrito/UBIGEO.
    gdf["qc_district_mismatch"] = mismatch_mask.values

    n_usable = int((~excluded_from_routing).sum())
    max_points = cfg["demand"]["max_points"]
    seed = cfg["demand"]["sampling"]["seed"]

    usable_pool = gdf.loc[~excluded_from_routing].reset_index(drop=True)
    sampled, was_sampled = sample_if_needed(usable_pool, "UBIGEO", max_points, seed)

    audit = val.build_audit_detail(gdf, "CODCP", flags, dataset_name="demand")

    keep_cols = [
        "CODCP", "NOMCP", "DEP", "PROV", "DIST", "UBIGEO", "CAPITAL", "CON_IE", "Z",
        "XGD", "YGD", "qc_district_mismatch", "geometry",
    ]
    # CORREGIDO (auditoría 2026-09-11): CPINEI/CPINEI2 son las claves de empate con
    # INEI que Fase 3 necesitará para unir población — se conservan SI existen en el
    # raw (no se inventan si algún corte futuro de SIGMED no las trajera).
    cpinei_cols = [c for c in ("CPINEI", "CPINEI2") if c in sampled.columns]
    keep_cols = keep_cols[:keep_cols.index("geometry")] + cpinei_cols + DESIGN_WEIGHT_COLS + ["geometry"]
    sampled_final = sampled[keep_cols].copy()
    sampled_final["estimated_population"] = pd.NA  # PENDIENTE Fase 3 (SIGMED no trae población)

    return {
        "gdf": sampled_final,
        "quality_outcomes": outcomes,
        "audit_detail": audit,
        "n_national": n_national,
        "n_in_scope": n_in_scope,
        "n_usable": n_usable,
        "n_final": len(sampled_final),
        "was_sampled": was_sampled,
        "seed": seed,
        "alarms": alarms,
    }
