"""Carga de configuración del proyecto.

Toda la configuración modificable vive en ``config.md`` (raíz del repo), dentro
de un único bloque cercado ```yaml ... ```. Este módulo lo extrae y lo parsea.

El resto del código Python debe obtener parámetros llamando a :func:`load_config`
(o a los ayudantes de este módulo) y **nunca** hardcodeando valores. En
particular, la lista de departamentos se obtiene con :func:`get_departments`.

Uso::

    from src.config import load_config, get_departments

    cfg = load_config()
    for dep in get_departments(cfg):
        print(dep["name"], dep["ubigeo_dep"])
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Raíz del repositorio = carpeta padre de src/
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config.md"

# Captura el primer bloque ```yaml ... ``` del Markdown.
_YAML_BLOCK_RE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)


def _extract_yaml_block(markdown_text: str) -> str:
    match = _YAML_BLOCK_RE.search(markdown_text)
    if match is None:
        raise ValueError(
            "config.md no contiene un bloque cercado ```yaml ... ```. "
            "La configuración legible por máquina debe ir en ese bloque."
        )
    return match.group(1)


@lru_cache(maxsize=1)
def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Lee ``config.md``, parsea su bloque YAML y devuelve un dict.

    El resultado se cachea; pásale un ``config_path`` distinto (o limpia la
    caché con ``load_config.cache_clear()``) para recargar.
    """
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")

    raw = path.read_text(encoding="utf-8")
    block = _extract_yaml_block(raw)
    cfg = yaml.safe_load(block)
    if not isinstance(cfg, dict):
        raise ValueError("El bloque YAML de config.md no es un mapeo (dict).")
    return cfg


def get_departments(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Lista de departamentos de estudio, tal cual está en config.md.

    Cada elemento es un dict con al menos ``name``, ``region`` y ``ubigeo_dep``.
    Cambiar los departamentos se hace SOLO editando config.md.
    """
    cfg = cfg or load_config()
    deps = cfg.get("departments")
    if not deps:
        raise ValueError("config.md no define 'departments'.")
    return deps


def get_department_names(cfg: dict[str, Any] | None = None) -> list[str]:
    return [d["name"] for d in get_departments(cfg)]


def get_department_codes(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Mapa {nombre_departamento: código UBIGEO de 2 dígitos}."""
    return {d["name"]: str(d["ubigeo_dep"]) for d in get_departments(cfg)}


def get_path(key: str, cfg: dict[str, Any] | None = None) -> Path:
    """Devuelve una ruta de ``paths:`` resuelta contra la raíz del repo."""
    cfg = cfg or load_config()
    paths = cfg.get("paths", {})
    if key not in paths:
        raise KeyError(f"paths.{key} no está definido en config.md")
    return (REPO_ROOT / paths[key]).resolve()


if __name__ == "__main__":  # pragma: no cover - inspección manual
    _cfg = load_config()
    print(f"config.md OK — {len(_cfg)} secciones de nivel superior")
    for _d in get_departments(_cfg):
        print(f"  - {_d['name']:9s} ({_d['region']}) UBIGEO {_d['ubigeo_dep']}")
    print("categorías resolutivas:", _cfg["facilities"]["resolutive_categories"])
    print("límite demand points:", _cfg["demand"]["max_points"])
