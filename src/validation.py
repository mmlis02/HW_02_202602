"""Motor de validación — Fase 1.

Implementa las 6 reglas obligatorias declaradas en ``config.md`` §6 / §7
(`validation:`), de forma genérica para poder aplicarse tanto a establecimientos
(RENIPRESS) como a demanda (SIGMED). Política `no_silent_drops` (config.md
`validation.policy`): ninguna regla borra un registro sin dejar rastro en el
detalle de auditoría; el `data_quality_report.csv` resume conteos y acción.

Cada función de chequeo devuelve un ``RuleOutcome`` (fila del reporte) y dos
cosas más: una máscara booleana de afectados y, cuando aplica, un `GeoDataFrame`
corregido. Nada se "arregla" silenciosamente: toda corrección queda además en
`audit_detail` con el valor original y el corregido.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

logger = logging.getLogger(__name__)

# Patrones típicos de "mojibake" (texto mal decodificado): UTF-8 leído como
# Latin-1/CP1252 produce secuencias como "Ã±", "Ã©"; un encoding roto también
# puede dejar el carácter de reemplazo U+FFFD.
_MOJIBAKE_PATTERNS = re.compile(r"Ã.|Â.|â€.|�")


@dataclass
class RuleOutcome:
    rule: str
    n_affected: int
    action: str
    n_corrected: int
    n_dropped: int
    n_warnings: int
    justification: str
    affected_index: list = field(default_factory=list, repr=False)

    def as_row(self) -> dict[str, Any]:
        return {
            "regla": self.rule,
            "n_afectados": self.n_affected,
            "accion": self.action,
            "n_corregidos": self.n_corrected,
            "n_eliminados": self.n_dropped,
            "n_warnings": self.n_warnings,
            "justificacion": self.justification,
        }


# ---------------------------------------------------------------- Regla 1 ---
def check_coord_missing(gdf: gpd.GeoDataFrame, lon_col: str, lat_col: str, rule_cfg: dict) -> tuple[RuleOutcome, pd.Series]:
    """Regla 1. ``zero_tolerance_deg`` (default 0.0 = igualdad exacta, retrocompatible)
    trata como "cero/ausente" cualquier punto con ``|lon|<=tol`` Y ``|lat|<=tol`` —
    no solo ``lon==0 and lat==0`` exacto. Corrección de auditoría (2026-09-11):
    con tolerancia 0 exacta, coordenadas como ``(-7.8e-07, -6e-08)`` (ruido de
    punto flotante de un "cero" mal escrito por la fuente) no se detectaban aquí y
    terminaban mal clasificadas en la regla 2 (fuera de bbox). Es una tolerancia
    parametrizada y documentada como decisión del proyecto (config.md §6), no un
    valor observado en los datos.
    """
    lon = pd.to_numeric(gdf[lon_col], errors="coerce")
    lat = pd.to_numeric(gdf[lat_col], errors="coerce")
    missing = lon.isna() | lat.isna()
    if rule_cfg.get("treat_zero_as_missing", True):
        tol = float(rule_cfg.get("zero_tolerance_deg", 0.0))
        missing = missing | ((lon.abs() <= tol) & (lat.abs() <= tol))
    n = int(missing.sum())
    outcome = RuleOutcome(
        rule="1. coordenadas ausentes/null/cero",
        n_affected=n,
        action=rule_cfg["action"],
        n_corrected=0,
        n_dropped=0,
        n_warnings=n,  # se conservan, marcados, excluidos del cálculo espacial
        justification=(
            "No se puede inventar una coordenada faltante. Se conserva el registro "
            "(no_silent_drops) y se excluye del cálculo espacial/routing. "
            f"zero_tolerance_deg={rule_cfg.get('zero_tolerance_deg', 0.0)} (decisión del proyecto)."
        ),
        affected_index=list(gdf.index[missing]),
    )
    return outcome, missing


# ---------------------------------------------------------------- Regla 2 ---
def check_coord_out_of_bbox(gdf: gpd.GeoDataFrame, lon_col: str, lat_col: str, bbox: list[float], rule_cfg: dict, already_missing: pd.Series) -> tuple[RuleOutcome, pd.Series]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lon = pd.to_numeric(gdf[lon_col], errors="coerce")
    lat = pd.to_numeric(gdf[lat_col], errors="coerce")
    within = lon.between(min_lon, max_lon) & lat.between(min_lat, max_lat)
    out = (~within) & (~already_missing)  # no doble-contar las que ya son "missing"
    n = int(out.sum())
    outcome = RuleOutcome(
        rule="2. coordenadas fuera del bbox de Perú",
        n_affected=n,
        action=rule_cfg["action"],
        n_corrected=0,
        n_dropped=0,
        n_warnings=n,
        justification=(
            f"peru_bbox={bbox}, tolerancia 0°. Un punto fuera de Perú no es "
            "utilizable para rutear en el país; se conserva marcado, no se borra."
        ),
        affected_index=list(gdf.index[out]),
    )
    return outcome, out


# ---------------------------------------------------------------- Regla 3 ---
def check_swapped_latlon(
    gdf: gpd.GeoDataFrame,
    lon_col: str,
    lat_col: str,
    bbox: list[float],
    rule_cfg: dict,
    out_of_bbox_mask: pd.Series,
    districts_gdf: gpd.GeoDataFrame | None = None,
    declared_ubigeo_col: str | None = None,
    district_ubigeo_field: str = "UBIGEO",
    containment_buffer_m: float = 1000.0,
    metric_crs: str = "EPSG:32718",
) -> tuple[RuleOutcome, pd.Series, pd.Series, gpd.GeoDataFrame]:
    """Detecta pares (lon,lat) intercambiados entre los que fallan el bbox.

    Detección: swap_test_against_bbox — si el par original falla el bbox pero el
    par invertido cae dentro, es candidato. Se confirma (y se corrige) solo si,
    además, el punto invertido cae dentro de su distrito declarado (± buffer);
    si no hay forma de confirmar, se deja como advertencia (no se corrige solo).
    """
    out_gdf = gdf.copy()
    lon = pd.to_numeric(out_gdf[lon_col], errors="coerce")
    lat = pd.to_numeric(out_gdf[lat_col], errors="coerce")
    min_lon, min_lat, max_lon, max_lat = bbox

    swap_within = lon.between(min_lat, max_lat) & lat.between(min_lon, max_lon)
    # candidato: el original está fuera de bbox, pero invertido (lat<->lon) cae dentro
    candidate = out_of_bbox_mask & swap_within.fillna(False)

    corrected = pd.Series(False, index=out_gdf.index)
    ambiguous = pd.Series(False, index=out_gdf.index)

    if not rule_cfg.get("enabled", True) or candidate.sum() == 0:
        outcome = RuleOutcome(
            rule="3. lat/lon intercambiadas",
            n_affected=int(candidate.sum()),
            action="n/a",
            n_corrected=0,
            n_dropped=0,
            n_warnings=int(candidate.sum()),
            justification="Detección por prueba de swap contra peru_bbox (rangos de lat/lon no se solapan).",
            affected_index=list(out_gdf.index[candidate]),
        )
        return outcome, corrected, ambiguous, out_gdf

    buffered_by_ubigeo: dict[str, Any] = {}
    if districts_gdf is not None and declared_ubigeo_col is not None and rule_cfg.get("confirm_with_district_polygon", True):
        d_metric = districts_gdf.to_crs(metric_crs)
        d_metric = d_metric.assign(geometry=d_metric.geometry.buffer(containment_buffer_m))
        d_buffered_4326 = d_metric.to_crs(gdf.crs or "EPSG:4326")
        buffered_by_ubigeo = dict(zip(d_buffered_4326[district_ubigeo_field], d_buffered_4326.geometry))

    for idx in out_gdf.index[candidate]:
        new_lon, new_lat = lat.at[idx], lon.at[idx]  # invertidos
        confirm = False
        if buffered_by_ubigeo and declared_ubigeo_col is not None:
            declared = out_gdf.at[idx, declared_ubigeo_col]
            poly = buffered_by_ubigeo.get(declared)
            if poly is not None:
                confirm = poly.contains(Point(new_lon, new_lat))
        if confirm:
            corrected.at[idx] = True
        else:
            ambiguous.at[idx] = True

    if corrected.any():
        out_gdf.loc[corrected, lon_col] = lat.loc[corrected].values
        out_gdf.loc[corrected, lat_col] = lon.loc[corrected].values
        out_gdf.loc[corrected, "geometry"] = [Point(xy) for xy in zip(out_gdf.loc[corrected, lon_col], out_gdf.loc[corrected, lat_col])]

    n = int(candidate.sum())
    outcome = RuleOutcome(
        rule="3. lat/lon intercambiadas",
        n_affected=n,
        action=f"{rule_cfg['action_if_unambiguous']} / {rule_cfg['action_if_ambiguous']}",
        n_corrected=int(corrected.sum()),
        n_dropped=0,
        n_warnings=int(ambiguous.sum()),
        justification=(
            "Perú: los rangos de lat (0..-18.4) y lon (-68.6..-81.4) de peru_bbox no se "
            "solapan, así que el swap es detectable sin ver los datos reales. Se corrige "
            "solo cuando el punto invertido cae dentro de su distrito declarado (± "
            f"{containment_buffer_m:.0f} m); si no hay límites o no confirma, queda como "
            "warning y se excluye del cálculo — no se corrige a ciegas."
        ),
        affected_index=list(out_gdf.index[candidate]),
    )
    return outcome, corrected, ambiguous, out_gdf


# ---------------------------------------------------------------- Regla 4 ---
def check_point_outside_declared_district(
    gdf: gpd.GeoDataFrame,
    districts_gdf: gpd.GeoDataFrame,
    declared_ubigeo_col: str,
    rule_cfg: dict,
    valid_point_mask: pd.Series,
    district_ubigeo_field: str = "UBIGEO",
    metric_crs: str = "EPSG:32718",
) -> tuple[RuleOutcome, pd.Series]:
    buffer_m = rule_cfg.get("containment_buffer_m", 1000.0)
    d_metric = districts_gdf.to_crs(metric_crs)
    d_metric = d_metric.assign(geometry=d_metric.geometry.buffer(buffer_m))
    d_buffered = d_metric.to_crs(gdf.crs or "EPSG:4326")
    buffered_by_ubigeo = dict(zip(d_buffered[district_ubigeo_field], d_buffered.geometry))

    mismatch = pd.Series(False, index=gdf.index)
    for idx in gdf.index[valid_point_mask]:
        declared = gdf.at[idx, declared_ubigeo_col]
        poly = buffered_by_ubigeo.get(declared)
        pt = gdf.geometry.at[idx]
        if poly is None or pt is None or pt.is_empty:
            continue  # UBIGEO declarado no existe en los límites o punto inválido -> no evaluable aquí
        if not poly.contains(pt):
            mismatch.at[idx] = True

    n = int(mismatch.sum())
    outcome = RuleOutcome(
        rule="4. punto fuera de su distrito declarado",
        n_affected=n,
        action=rule_cfg["action"],
        n_corrected=0,
        n_dropped=0,
        n_warnings=n,
        justification=(
            f"Unión espacial contra distritos IGN, buffer {buffer_m:.0f} m (tolerancia por "
            "la escala 1:100 000 de los polígonos). No se auto-corrige: podría ser el "
            "UBIGEO declarado el que está mal, no la coordenada. La pertenencia "
            "departamental para el análisis se decide por unión espacial (config.md §3), "
            "esta columna declarada queda solo como verificación cruzada."
        ),
        affected_index=list(gdf.index[mismatch]),
    )
    return outcome, mismatch


# ---------------------------------------------------------------- Regla 5 ---
def check_duplicate_key(df: pd.DataFrame, key_field: str, rule_cfg: dict) -> tuple[RuleOutcome, pd.Series, pd.Series]:
    dup_any = df[key_field].duplicated(keep=False) & df[key_field].notna()
    exact = df.duplicated(keep=False) & dup_any  # fila 100% idéntica en TODAS las columnas
    exact_drop = df.duplicated(keep="first") & exact  # las copias a eliminar (se queda la primera)
    conflicting = dup_any & ~exact

    n = int(dup_any.sum())
    outcome = RuleOutcome(
        rule="5. códigos de establecimiento duplicados",
        n_affected=n,
        action=f"{rule_cfg['exact_duplicate_action']} / {rule_cfg['conflicting_duplicate_action']}",
        n_corrected=0,
        n_dropped=int(exact_drop.sum()),
        n_warnings=int(conflicting.sum()),
        justification=(
            f"key_field='{key_field}'. Duplicado exacto (fila idéntica) -> se conserva la "
            "primera y se elimina la copia (no pierde información). Mismo código con datos "
            "distintos -> no se decide solo cuál fila es correcta, queda como warning."
        ),
        affected_index=list(df.index[dup_any]),
    )
    return outcome, exact_drop, conflicting


# ---------------------------------------------------------------- Regla 6 ---
def check_encoding(text_series_list: list[pd.Series], rule_cfg: dict, encoding_used: str) -> RuleOutcome:
    total = 0
    flagged = 0
    for s in text_series_list:
        s = s.dropna().astype(str)
        total += len(s)
        flagged += int(s.str.contains(_MOJIBAKE_PATTERNS, regex=True, na=False).sum())
    pct = (100.0 * flagged / total) if total else 0.0
    threshold = rule_cfg.get("max_mojibake_pct_alarm", 1.0)
    ok = pct <= threshold
    outcome = RuleOutcome(
        rule="6. problemas de encoding",
        n_affected=flagged,
        action="verificado_ok" if ok else rule_cfg["action"],
        n_corrected=0,
        n_dropped=0,
        n_warnings=0 if ok else flagged,
        justification=(
            f"Encoding efectivamente usado: '{encoding_used}'. Se buscaron patrones de "
            f"mojibake (Ã.., Â.., U+FFFD) en columnas de texto: {flagged}/{total} valores "
            f"({pct:.3f}%) — umbral de alarma {threshold}%. "
            + ("Sin problemas detectados." if ok else "Por encima del umbral: revisar encoding.")
        ),
        affected_index=[],
    )
    return outcome


def check_alarm(n_affected: int, n_total: int, threshold_pct: float, label: str) -> dict[str, Any] | None:
    """Umbral agregado (circuit-breaker de calidad, no una acción por registro).

    Devuelve un dict de alarma si `n_affected/n_total` supera `threshold_pct`;
    ``None`` si está por debajo. No detiene el proceso (el pipeline sigue,
    con no_silent_drops), pero la alarma se registra y se reporta al usuario
    en vez de pasar inadvertida.
    """
    if n_total == 0:
        return None
    pct = 100.0 * n_affected / n_total
    if pct > threshold_pct:
        logger.warning("ALARMA [%s]: %d/%d (%.2f%%) supera el umbral configurado (%.1f%%)", label, n_affected, n_total, pct, threshold_pct)
        return {"label": label, "n_affected": n_affected, "n_total": n_total, "pct": pct, "threshold_pct": threshold_pct}
    return None


def build_quality_report(outcomes: list[RuleOutcome]) -> pd.DataFrame:
    return pd.DataFrame([o.as_row() for o in outcomes])


def build_audit_detail(
    gdf: gpd.GeoDataFrame,
    key_field: str,
    flags: dict[str, pd.Series],
    dataset_name: str,
) -> pd.DataFrame:
    """Une todas las máscaras de reglas en un detalle por registro (solo afectados)."""
    any_flag = pd.Series(False, index=gdf.index)
    for m in flags.values():
        any_flag = any_flag | m.reindex(gdf.index, fill_value=False)

    cols = {"dataset": dataset_name, "record_key": gdf[key_field]}
    for name, mask in flags.items():
        cols[name] = mask.reindex(gdf.index, fill_value=False)
    detail = pd.DataFrame(cols, index=gdf.index)
    return detail.loc[any_flag].reset_index(drop=True)
