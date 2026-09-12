"""Tests de src/dashboard/filters.py — cascada de filtros del sidebar."""

from __future__ import annotations

import pandas as pd

from src.dashboard.filters import TODOS, apply_facility_filters, apply_geographic_filter, get_districts_for, get_provinces_for_departments, map_component_key, serialize_filter


def _df():
    return pd.DataFrame({
        "DEP": ["CUSCO", "CUSCO", "AMAZONAS", "TUMBES"],
        "PROV": ["CUSCO", "URUBAMBA", "BAGUA", "TUMBES"],
        "DIST": ["WANCHAQ", "URUBAMBA", "BAGUA", "TUMBES"],
    })


def test_province_cascading_excludes_other_departments():
    provs = get_provinces_for_departments(_df(), ["CUSCO"])
    assert TODOS in provs
    assert "URUBAMBA" in provs and "CUSCO" in provs
    assert "BAGUA" not in provs and "TUMBES" not in provs


def test_province_cascading_todos_returns_all():
    provs = get_provinces_for_departments(_df(), [TODOS])
    assert set(provs) == {TODOS, "CUSCO", "URUBAMBA", "BAGUA", "TUMBES"}


def test_district_cascading_depends_on_department_and_province():
    dists = get_districts_for(_df(), ["CUSCO"], ["URUBAMBA"])
    assert dists == [TODOS, "URUBAMBA"]


def test_apply_geographic_filter_empty_selection_returns_empty_df():
    out = apply_geographic_filter(_df(), departments=["TUMBES"], provinces=["BAGUA"], districts=None)
    assert len(out) == 0  # BAGUA no es provincia de TUMBES -> selección vacía, sin error


def test_apply_geographic_filter_todos_is_noop():
    out = apply_geographic_filter(_df(), departments=[TODOS], provinces=None, districts=None)
    assert len(out) == len(_df())


def test_serialize_filter_todos_and_empty_and_none_are_the_same_token():
    assert serialize_filter([TODOS]) == serialize_filter(None) == serialize_filter([]) == "todos"


def test_serialize_filter_order_independent():
    assert serialize_filter(["CUSCO", "AMAZONAS"]) == serialize_filter(["AMAZONAS", "CUSCO"])


def test_map_component_key_changes_across_todos_cusco_amazonas_transition():
    # Bug de viewport persistente: la key DEBE cambiar en cada paso de la
    # transicion Todos -> Cusco -> Amazonas -> Todos para que st_folium
    # remonte el componente y el fit_bounds recien calculado tenga efecto.
    k_todos = map_component_key("main_map", [TODOS], [TODOS], [TODOS])
    k_cusco = map_component_key("main_map", ["CUSCO"], [TODOS], [TODOS])
    k_amazonas = map_component_key("main_map", ["AMAZONAS"], [TODOS], [TODOS])
    k_todos_again = map_component_key("main_map", [TODOS], [TODOS], [TODOS])
    assert len({k_todos, k_cusco, k_amazonas}) == 3  # las 3 keys son distintas entre si
    assert k_todos == k_todos_again  # volver a "Todos" reproduce la misma key (determinismo)


def test_map_component_key_never_fixed_regardless_of_filter():
    # Nunca debe usarse una key fija tipo "main_map" para todos los filtros.
    keys = {map_component_key("main_map", [dep], [TODOS], [TODOS]) for dep in ["TUMBES", "AMAZONAS", "CUSCO"]}
    assert len(keys) == 3
    assert "main_map" not in keys


def test_map_component_key_independent_per_tab_prefix():
    k_main = map_component_key("main_map", ["CUSCO"], [TODOS], [TODOS])
    k_fac = map_component_key("fac_map", ["CUSCO"], [TODOS], [TODOS])
    assert k_main != k_fac


def test_apply_facility_filters_resolutive_only():
    df = pd.DataFrame({"CATEGORIA_NORM": ["I-3", "III-1"], "DEPARTAMENTO": ["MINSA", "MINSA"], "is_resolutive": [False, True]})
    out = apply_facility_filters(df, categories=None, institutions=None, resolutive_only="Solo resolutivos")
    assert len(out) == 1 and out.iloc[0]["CATEGORIA_NORM"] == "III-1"
