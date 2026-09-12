"""Smoke tests de app.py vía `streamlit.testing.v1.AppTest` — ejecutan el
script real (con datos reales precomputados), a diferencia de
`tests/test_dashboard_*.py` que testean la lógica pura sin Streamlit. Más
lentos, pero son los únicos que hubieran detectado el guard de
`MAX_FACILITIES_MAIN_MAP` (lógica inline en `app.py`, corrección 2026-09-12).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _app_exists() -> bool:
    required = [
        REPO_ROOT / "data/outputs/dashboard_district_metrics.parquet",
        REPO_ROOT / "data/outputs/dashboard_district_geometries_simplified.parquet",
        REPO_ROOT / "data/outputs/dashboard_facilities.parquet",
    ]
    return all(p.exists() for p in required)


pytestmark = pytest.mark.skipif(not _app_exists(), reason="outputs precomputados de Fase 4 no disponibles en este entorno")


def _run(setup=None):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=120)
    at.run()
    if setup:
        setup(at)
        at.run()
    return at


def test_default_todos_no_exceptions():
    at = _run()
    assert list(at.exception) == []


def test_cusco_facilities_checkbox_blocked_over_threshold():
    # Cusco tiene 1582 establecimientos (real), muy por encima de
    # MAX_FACILITIES_MAIN_MAP=800 -- activar el checkbox debe mostrar el
    # aviso de "demasiados establecimientos", nunca intentar construir la
    # capa completa (eso es lo que rompía el render, ver corrección 2026-09-12).
    at = _run(lambda at: (
        at.sidebar.multiselect[0].set_value(["CUSCO"]).run(),
        at.checkbox(key="show_facilities_main_map").set_value(True).run(),
    ))
    assert list(at.exception) == []
    info_texts = [i.value for i in at.info]
    assert any("demasiados establecimientos" in t.lower() for t in info_texts)


def test_todos_facilities_checkbox_blocked_over_threshold():
    # "Todos" (2537 establecimientos) debe quedar bloqueado por el mismo
    # guard, sin necesidad de un caso especial para "Todos".
    at = _run(lambda at: at.checkbox(key="show_facilities_main_map").set_value(True).run())
    assert list(at.exception) == []
    info_texts = [i.value for i in at.info]
    assert any("demasiados establecimientos" in t.lower() for t in info_texts)


def test_amazonas_facilities_checkbox_allowed_under_threshold():
    # Amazonas tiene 791 establecimientos (real), por debajo del umbral de
    # 800 -- activar el checkbox NO debe mostrar el aviso de bloqueo.
    at = _run(lambda at: (
        at.sidebar.multiselect[0].set_value(["AMAZONAS"]).run(),
        at.checkbox(key="show_facilities_main_map").set_value(True).run(),
    ))
    assert list(at.exception) == []
    info_texts = [i.value for i in at.info]
    assert not any("demasiados establecimientos" in t.lower() for t in info_texts)


def test_facilities_checkbox_off_by_default_no_block_message():
    at = _run(lambda at: at.sidebar.multiselect[0].set_value(["CUSCO"]).run())
    info_texts = [i.value for i in at.info]
    assert not any("demasiados establecimientos" in t.lower() for t in info_texts)


def test_empty_geographic_selection_no_crash():
    at = _run(lambda at: (
        at.sidebar.multiselect[0].set_value(["TUMBES"]).run(),
        at.sidebar.multiselect[1].set_value(["CUSCO"]).run(),
    ))
    assert list(at.exception) == []
