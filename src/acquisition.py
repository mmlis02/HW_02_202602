"""Adquisición reproducible de las fuentes oficiales (Fase 1).

Reglas que respeta este módulo (ver config.md §4 y README):

- Nunca sobrescribe un archivo ya presente en ``data/raw/``: si el destino existe,
  no se vuelve a descargar (idempotente / re-ejecutable sin costo de red).
- Cada archivo descargado queda acompañado de un ``<archivo>.manifest.json`` con
  URL, fecha de descarga, `Last-Modified` del servidor, tamaño y sha256 — así se
  puede auditar de dónde salió cada raw sin volver a tocar la red.
- Si un raw ya existe pero no tiene manifest (p. ej. se copió a mano), se genera
  el manifest post-hoc con una petición `HEAD` — no se re-descarga el contenido.
- El portal `datosabiertos.gob.pe` aplica un WAF que puede responder 418 a
  clientes sin `User-Agent` de navegador; por eso todas las peticiones fijan uno.
- No se implementa aquí nada de Fase 2 (no hay función para el PBF de OSM).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from src.config import REPO_ROOT, get_path, load_config

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQUEST_TIMEOUT_S = 120


@dataclass
class AcquisitionResult:
    source_name: str
    path: Path
    manifest: dict[str, Any]
    was_downloaded: bool  # False si ya existía (cache) o se adoptó


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(dest: Path) -> Path:
    return dest.with_name(dest.name + ".manifest.json")


def _write_manifest(dest: Path, manifest: dict[str, Any]) -> None:
    _manifest_path(dest).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def ensure_downloaded(
    url: str,
    dest_path: str | Path,
    *,
    source_name: str,
    cutoff_date: str,
    user_agent: str = DEFAULT_USER_AGENT,
    force: bool = False,
) -> AcquisitionResult:
    """Descarga ``url`` a ``dest_path`` si no existe ya; nunca sobrescribe.

    Si ``dest_path`` ya existe (típico en re-ejecuciones), NO se vuelve a
    descargar — se reutiliza y, si falta, se genera el manifest con un `HEAD`.
    """
    dest = Path(dest_path)
    manifest_file = _manifest_path(dest)

    if dest.exists() and not force:
        if manifest_file.exists():
            logger.info("[%s] raw ya existe (%s) y tiene manifest — no se descarga de nuevo.", source_name, dest)
            return AcquisitionResult(source_name, dest, json.loads(manifest_file.read_text()), was_downloaded=False)

        logger.info("[%s] raw ya existe (%s) sin manifest — generando manifest post-hoc (sin re-descargar).", source_name, dest)
        head_info: dict[str, Any] = {}
        try:
            resp = requests.head(url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT_S, allow_redirects=True)
            head_info = {
                "http_status_head": resp.status_code,
                "http_last_modified": resp.headers.get("Last-Modified"),
                "http_content_length": resp.headers.get("Content-Length"),
            }
        except requests.RequestException as exc:
            logger.warning("[%s] HEAD falló al generar manifest post-hoc (%s); se documenta y se continúa con el raw existente.", source_name, exc)
            head_info = {"http_head_error": str(exc)}

        manifest = {
            "source_name": source_name,
            "url": url,
            "adopted_existing_file": True,
            "adopted_at_utc": datetime.now(timezone.utc).isoformat(),
            "cutoff_date_declared": cutoff_date,
            "local_path": str(dest.relative_to(REPO_ROOT)) if dest.is_relative_to(REPO_ROOT) else str(dest),
            "local_size_bytes": dest.stat().st_size,
            "sha256": _sha256(dest),
            **head_info,
        }
        _write_manifest(dest, manifest)
        return AcquisitionResult(source_name, dest, manifest, was_downloaded=False)

    logger.info("[%s] descargando %s -> %s", source_name, url, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Portal no disponible y no hay cache previa: no se puede inventar el dato.
        raise RuntimeError(
            f"[{source_name}] no se pudo descargar {url} y no existe una copia en cache "
            f"({dest}). Error: {exc}"
        ) from exc

    dest.write_bytes(resp.content)
    manifest = {
        "source_name": source_name,
        "url": url,
        "adopted_existing_file": False,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff_date_declared": cutoff_date,
        "local_path": str(dest.relative_to(REPO_ROOT)) if dest.is_relative_to(REPO_ROOT) else str(dest),
        "local_size_bytes": dest.stat().st_size,
        "http_status": resp.status_code,
        "http_last_modified": resp.headers.get("Last-Modified"),
        "http_content_length": resp.headers.get("Content-Length"),
        "sha256": _sha256(dest),
    }
    _write_manifest(dest, manifest)
    logger.info("[%s] OK — %d bytes, sha256=%s", source_name, manifest["local_size_bytes"], manifest["sha256"][:12])
    return AcquisitionResult(source_name, dest, manifest, was_downloaded=True)


def acquire_all(cfg: dict[str, Any] | None = None) -> dict[str, AcquisitionResult]:
    """Descarga (o reutiliza) las 3 fuentes de Fase 1: RENIPRESS, SIGMED, IGN.

    No descarga OSM/OSRM (Fase 2, fuera de alcance).
    """
    cfg = cfg or load_config()
    acq = cfg["acquisition"]
    cutoff = cfg["data_cutoff"]
    raw_dir = get_path("data_raw", cfg)

    results: dict[str, AcquisitionResult] = {}

    ren = acq["renipress"]
    results["renipress"] = ensure_downloaded(
        ren["url"],
        raw_dir / "renipress" / ren["resource"],
        source_name="RENIPRESS",
        cutoff_date=cutoff["renipress"]["date"],
    )

    sig = acq["sigmed_centros_poblados"]
    results["sigmed_centros_poblados"] = ensure_downloaded(
        sig["url"],
        raw_dir / "sigmed" / sig["resource"],
        source_name="SIGMED Centros Poblados",
        cutoff_date=cutoff["sigmed_centros_poblados"]["date"],
    )

    ign = acq["ign_limites"]
    results["ign_departamentos"] = ensure_downloaded(
        ign["departamentos_url"],
        raw_dir / "ign" / ign["departamentos_resource"],
        source_name="IGN Límites Departamentales",
        cutoff_date=cutoff["limites_administrativos_ign"]["date"],
    )
    results["ign_distritos"] = ensure_downloaded(
        ign["distritos_url"],
        raw_dir / "ign" / ign["distritos_resource"],
        source_name="IGN Límites Distritales",
        cutoff_date=cutoff["limites_administrativos_ign"]["date"],
    )

    return results


def acquire_osm_pbf(cfg: dict[str, Any] | None = None) -> AcquisitionResult:
    """Descarga (o reutiliza) el PBF de OSM/Geofabrik para Perú — Fase 2.

    ``peru-latest.osm.pbf`` es en realidad un 302 a un snapshot fechado
    (`peru-YYMMDD.osm.pbf`); ``requests`` sigue redirecciones por defecto, así
    que el archivo guardado ya es el fechado — reproducible, no "-latest".
    """
    cfg = cfg or load_config()
    osm_cfg = cfg["routing"]["osm_pbf"]
    cutoff = cfg["data_cutoff"]["osm_geofabrik"]
    raw_dir = get_path("data_raw", cfg)
    dest = raw_dir / "osm" / osm_cfg["resolved_resource"]
    return ensure_downloaded(
        osm_cfg["url"], dest, source_name="OSM Geofabrik Peru", cutoff_date=cutoff["date"],
    )


def fetch_arcgis_layer_paginated(
    service_query_url: str,
    *,
    where: str,
    out_fields: str,
    page_size: int,
    user_agent: str = DEFAULT_USER_AGENT,
    order_by_field: str | None = None,
) -> list[dict]:
    """Pagina un endpoint ArcGIS REST `.../query` con `resultOffset` hasta
    agotar los resultados (Fase 3 — CENEPRED/MINAM centros poblados).

    No asume `objectIds`/`exceededTransferLimit` de una sola pasada: sigue
    pidiendo páginas de `page_size` hasta recibir 0 features. Determinista si
    `order_by_field` se fija (recomendado: la clave primaria) — si no se fija,
    ArcGIS no garantiza el mismo orden entre llamadas, pero el conjunto total
    de features no debería cambiar entre corridas si la capa no se actualiza.
    """
    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": page_size,
            "resultOffset": offset,
        }
        if order_by_field:
            params["orderByFields"] = order_by_field
        resp = requests.get(service_query_url, params=params, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"ArcGIS query error en {service_query_url}: {data['error']}")
        page = data.get("features", [])
        if not page:
            break
        features.extend(page)
        logger.info("[%s] página offset=%d -> +%d features (total=%d)", service_query_url, offset, len(page), len(features))
        if len(page) < page_size:
            break
        offset += page_size
    return features


def acquire_arcgis_ccpp(
    *,
    source_name: str,
    service_query_url: str,
    departments: list[str],
    dep_field: str,
    out_fields: str,
    id_field: str,
    dest_dir: str | Path,
    page_size: int = 2000,
    force: bool = False,
) -> AcquisitionResult:
    """Descarga (por departamento, paginado) una capa ArcGIS de centros
    poblados y la guarda RAW (una tabla combinada, sin transformar campos) +
    manifest con URL, query, fecha, N registros y sha256. Idempotente: si el
    parquet de destino ya existe, no vuelve a pedir la red."""
    import pandas as pd

    dest_dir = Path(dest_dir)
    dest = dest_dir / "ccpp_raw.parquet"
    manifest_file = _manifest_path(dest)

    if dest.exists() and manifest_file.exists() and not force:
        logger.info("[%s] raw ya existe (%s) — no se vuelve a consultar el servicio.", source_name, dest)
        return AcquisitionResult(source_name, dest, json.loads(manifest_file.read_text()), was_downloaded=False)

    dest_dir.mkdir(parents=True, exist_ok=True)
    all_features: list[dict] = []
    per_dep_counts: dict[str, int] = {}
    for dep in departments:
        where = f"{dep_field}='{dep}'"
        feats = fetch_arcgis_layer_paginated(service_query_url, where=where, out_fields=out_fields, page_size=page_size, order_by_field=id_field)
        per_dep_counts[dep] = len(feats)
        all_features.extend(feats)

    rows = [f["attributes"] for f in all_features]
    df = pd.DataFrame(rows)
    # Nunca convertir el identificador a entero (pierde ceros a la izquierda).
    if id_field in df.columns:
        df[id_field] = df[id_field].astype("string")
    df.to_parquet(dest, index=False)

    manifest = {
        "source_name": source_name,
        "service_query_url": service_query_url,
        "departments_queried": departments,
        "dep_field": dep_field,
        "out_fields": out_fields,
        "id_field": id_field,
        "page_size": page_size,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_records_total": len(df),
        "n_records_by_department": per_dep_counts,
        "n_duplicate_id": int(df[id_field].duplicated().sum()) if id_field in df.columns else None,
        "local_path": str(dest.relative_to(REPO_ROOT)) if dest.is_relative_to(REPO_ROOT) else str(dest),
        "sha256": _sha256(dest),
    }
    _write_manifest(dest, manifest)
    logger.info("[%s] OK — %d registros (%s), sha256=%s", source_name, len(df), per_dep_counts, manifest["sha256"][:12])
    return AcquisitionResult(source_name, dest, manifest, was_downloaded=True)


def extract_zip_if_needed(zip_path: str | Path, extract_dir: str | Path) -> Path:
    """Extrae ``zip_path`` en ``extract_dir`` si ese directorio aún no existe."""
    import zipfile

    extract_dir = Path(extract_dir)
    if extract_dir.exists() and any(extract_dir.iterdir()):
        logger.info("Ya extraído en %s — no se vuelve a extraer.", extract_dir)
        return extract_dir
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    return extract_dir
