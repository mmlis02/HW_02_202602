"""Procesamiento + validación de Fase 1: construye los datasets limpios.

Lee `data/raw/` (nunca lo modifica), procesa oferta (RENIPRESS), demanda
(SIGMED) y límites administrativos (IGN), aplica las 6 reglas de validación
obligatorias y escribe:

    data/processed/facilities.parquet   (incluye qc_district_mismatch)
    data/processed/demand.parquet       (incluye qc_district_mismatch, CPINEI/CPINEI2
                                          si existen, y los pesos de diseño muestral
                                          stratum_n/stratum_sample_n/inclusion_prob/
                                          design_weight — ver demand.py::DESIGN_WEIGHT_COLS)
    data/processed/departments.gpkg
    data/processed/provinces.gpkg
    data/processed/districts.gpkg
    data/outputs/data_quality_report.csv
    data/outputs/data_quality_audit_detail.csv      (para lectura humana)
    data/outputs/data_quality_audit_detail.parquet  (para re-unir por record_key)

No implementa routing, métricas, dashboard ni informe (fuera de alcance de
Fase 1).

Uso:
    conda activate ./.venv
    python -m scripts.validate_data
"""

from __future__ import annotations

import logging
import sys

import pandas as pd

from src.boundaries import build_study_boundaries
from src.config import get_path, load_config
from src.demand import build_demand
from src.facilities import build_facilities

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def main() -> None:
    cfg = load_config()
    processed_dir = get_path("data_processed", cfg)
    outputs_dir = get_path("data_outputs", cfg)
    processed_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Fase 1: límites administrativos (IGN) ===")
    boundaries = build_study_boundaries(cfg)
    boundaries["departments"].to_file(processed_dir / "departments.gpkg", driver="GPKG")
    boundaries["provinces"].to_file(processed_dir / "provinces.gpkg", driver="GPKG")
    boundaries["districts"].to_file(processed_dir / "districts.gpkg", driver="GPKG")
    logger.info(
        "departments=%d provinces=%d(derivadas) districts=%d -> data/processed/*.gpkg",
        len(boundaries["departments"]), len(boundaries["provinces"]), len(boundaries["districts"]),
    )

    logger.info("=== Fase 1: oferta (RENIPRESS) ===")
    fac = build_facilities(cfg, districts_gdf=boundaries["districts"])
    fac["gdf"].to_parquet(processed_dir / "facilities.parquet")
    logger.info(
        "facilities: %d en ámbito -> %d resolutivos (%d usables para routing) -> data/processed/facilities.parquet",
        fac["n_raw_in_scope"], int(fac["gdf"]["is_resolutive"].sum()), int(fac["gdf"]["usable_for_routing"].sum()),
    )
    for a in fac["alarms"]:
        logger.warning("ALARMA facilities.%s: %.2f%% > umbral %.1f%% (%d/%d)", a["label"], a["pct"], a["threshold_pct"], a["n_affected"], a["n_total"])
    vfac = cfg["validation"]["facilities"]
    assert fac["n_raw_in_scope"] >= vfac["min_records_total"], "facilities: por debajo de min_records_total"
    n_resolutive = int(fac["gdf"]["is_resolutive"].sum())
    if n_resolutive < vfac["min_resolutive_in_scope"]:
        logger.warning("ALARMA: solo %d resolutivos (< min_resolutive_in_scope=%d)", n_resolutive, vfac["min_resolutive_in_scope"])

    logger.info("=== Fase 1: demanda (SIGMED) ===")
    dem = build_demand(cfg, districts_gdf=boundaries["districts"])
    dem["gdf"].to_parquet(processed_dir / "demand.parquet")
    logger.info(
        "demand: nacional=%d en_ambito=%d usable=%d final=%d (muestreo=%s) -> data/processed/demand.parquet",
        dem["n_national"], dem["n_in_scope"], dem["n_usable"], dem["n_final"], dem["was_sampled"],
    )
    for a in dem["alarms"]:
        logger.warning("ALARMA demand.%s: %.2f%% > umbral %.1f%% (%d/%d)", a["label"], a["pct"], a["threshold_pct"], a["n_affected"], a["n_total"])

    logger.info("=== Fase 1: reporte de calidad ===")
    quality_rows = []
    for o in fac["quality_outcomes"]:
        row = o.as_row()
        row["dataset"] = "facilities"
        quality_rows.append(row)
    for o in dem["quality_outcomes"]:
        row = o.as_row()
        row["dataset"] = "demand"
        quality_rows.append(row)
    quality_df = pd.DataFrame(quality_rows)[
        ["dataset", "regla", "n_afectados", "accion", "n_corregidos", "n_eliminados", "n_warnings", "justificacion"]
    ]
    quality_df.to_csv(outputs_dir / "data_quality_report.csv", index=False)
    logger.info("data_quality_report.csv escrito (%d filas: 6 reglas x 2 datasets)", len(quality_df))

    audit_df = pd.concat([fac["audit_detail"], dem["audit_detail"]], ignore_index=True)
    assert not pd.api.types.is_numeric_dtype(audit_df["record_key"]), "record_key debe ser texto, no numérico"
    audit_df.to_csv(outputs_dir / "data_quality_audit_detail.csv", index=False)
    # CORREGIDO (auditoría 2026-09-11): el CSV por sí solo no preserva dtype — al
    # releerlo con pandas por defecto, "00016758" se infiere como int 16758 y se
    # pierden los ceros a la izquierda, rompiendo la unión con facilities/demand
    # .parquet. El .csv se conserva (formato pedido, legible en cualquier hoja de
    # cálculo) pero se añade un .parquet gemelo, que SÍ preserva el dtype string de
    # record_key, como el artefacto que debe usarse para volver a unir sin
    # ambigüedad. No se cambió el identificador original en ningún caso.
    audit_df.to_parquet(outputs_dir / "data_quality_audit_detail.parquet")
    logger.info(
        "data_quality_audit_detail.{csv,parquet} escritos (%d registros afectados por al menos una regla). "
        "Usar el .parquet para re-unir por record_key sin ambigüedad de ceros a la izquierda.",
        len(audit_df),
    )

    logger.info("=== Fase 1 completa. Nada de Fase 2 (routing/OSRM/OSM) fue tocado. ===")


if __name__ == "__main__":
    main()
