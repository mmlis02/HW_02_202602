"""Adquisición reproducible de Fase 1: RENIPRESS, SIGMED, límites IGN.

No descarga nada de Fase 2 (no toca el PBF de OSM). Re-ejecutable: si un raw ya
existe, no se vuelve a descargar (ver `src/acquisition.py`).

Uso:
    conda activate ./.venv
    python -m scripts.download_data
"""

from __future__ import annotations

import logging
import sys

from src.acquisition import acquire_all
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def main() -> None:
    cfg = load_config()
    logger.info("=== Fase 1: adquisición de datos ===")
    results = acquire_all(cfg)
    logger.info("--- Resumen ---")
    for name, res in results.items():
        estado = "DESCARGADO" if res.was_downloaded else "REUTILIZADO (cache)"
        size_mb = res.manifest.get("local_size_bytes", 0) / (1024 * 1024)
        logger.info("%-28s %-22s %8.2f MB  %s", name, estado, size_mb, res.path)
    logger.info("=== Adquisición completa. data/raw/ no se sobrescribe en re-ejecuciones. ===")


if __name__ == "__main__":
    main()
