"""filters — cascada de filtros del sidebar (Fase 4). Python/pandas puro,
sin Streamlit — testeable sin lanzar la app.

Principio (enunciado, sección 23): los filtros seleccionan un SUBCONJUNTO
del universo ya calibrado — NUNCA recalculan ni recalibran pesos. Todas las
funciones de este módulo solo filtran filas; los `calibrated_weight` de cada
fila quedan tal cual vienen de Fase 3.
"""

from __future__ import annotations

import pandas as pd

TODOS = "Todos"


def options_with_todos(values: list[str]) -> list[str]:
    return [TODOS] + sorted(v for v in values if pd.notna(v))


def get_provinces_for_departments(df: pd.DataFrame, departments: list[str], *, dep_col: str = "DEP", prov_col: str = "PROV") -> list[str]:
    """Provincias disponibles dado el departamento seleccionado (`Todos` o
    una lista) — nunca muestra provincias de un departamento no seleccionado."""
    sub = df if TODOS in departments or not departments else df[df[dep_col].isin(departments)]
    return options_with_todos(sub[prov_col].unique().tolist())


def get_districts_for(df: pd.DataFrame, departments: list[str], provinces: list[str], *, dep_col: str = "DEP", prov_col: str = "PROV", dist_col: str = "DIST") -> list[str]:
    sub = df
    if departments and TODOS not in departments:
        sub = sub[sub[dep_col].isin(departments)]
    if provinces and TODOS not in provinces:
        sub = sub[sub[prov_col].isin(provinces)]
    return options_with_todos(sub[dist_col].unique().tolist())


def apply_geographic_filter(
    df: pd.DataFrame, *, departments: list[str] | None, provinces: list[str] | None, districts: list[str] | None,
    dep_col: str = "DEP", prov_col: str = "PROV", dist_col: str = "DIST",
) -> pd.DataFrame:
    out = df
    if departments and TODOS not in departments:
        out = out[out[dep_col].isin(departments)]
    if provinces and TODOS not in provinces:
        out = out[out[prov_col].isin(provinces)]
    if districts and TODOS not in districts:
        out = out[out[dist_col].isin(districts)]
    return out


def serialize_filter(values: list[str] | None) -> str:
    """Serialización determinística de un filtro (lista, `None`, vacía, o
    `["Todos"]`) para usar en una `st_folium` `key` — el orden de selección
    del usuario en el multiselect no debe importar (se ordena), y
    "Todos"/vacío/`None` producen siempre el mismo token."""
    if not values or list(values) == [TODOS]:
        return "todos"
    return "-".join(sorted(str(v) for v in values))


def map_component_key(prefix: str, *filter_groups: list[str] | None) -> str:
    """`key` de un componente `st_folium` dependiente del filtro activo
    (corrección del bug de viewport persistente, 2026-09-12): sin una key
    que cambie con el filtro, streamlit-folium preserva el pan/zoom anterior
    entre reruns aunque el `folium.Map` subyacente traiga un `fit_bounds()`
    nuevo — el componente debe REMONTARSE para que el fit_bounds recién
    calculado tenga efecto en el navegador."""
    return "_".join([prefix, *(serialize_filter(g) for g in filter_groups)])


def apply_facility_filters(
    df: pd.DataFrame, *, categories: list[str] | None, institutions: list[str] | None,
    resolutive_only: str = TODOS,  # TODOS | "Solo resolutivos" | "Solo no resolutivos"
    category_col: str = "CATEGORIA_NORM", institution_col: str = "INSTITUCION", resolutive_col: str = "is_resolutive",
) -> pd.DataFrame:
    out = df
    if categories and TODOS not in categories:
        out = out[out[category_col].isin(categories)]
    if institutions and TODOS not in institutions:
        out = out[out[institution_col].isin(institutions)]
    if resolutive_only == "Solo resolutivos":
        out = out[out[resolutive_col] == True]  # noqa: E712
    elif resolutive_only == "Solo no resolutivos":
        out = out[out[resolutive_col] == False]  # noqa: E712
    return out
