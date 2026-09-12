"""Tests de normalización RENIPRESS — funciones puras, sin leer ningún archivo."""

from __future__ import annotations

import pandas as pd

from src.facilities import is_active, normalize_category

RESOLUTIVE = {"II-1", "II-2", "II-E", "III-1", "III-2", "III-E"}


def test_normalize_category_canonical_passthrough():
    for cat in ["I-1", "I-2", "I-3", "I-4", "II-1", "II-2", "II-E", "III-1", "III-2", "III-E"]:
        assert normalize_category(cat) == cat


def test_normalize_category_tolerates_spacing():
    assert normalize_category("II - 1") == "II-1"
    assert normalize_category(" iii-e ") == "III-E"


def test_normalize_category_zero_and_missing_are_sin_categoria():
    assert normalize_category("0") == "SIN_CATEGORIA"
    assert normalize_category(None) == "SIN_CATEGORIA"
    assert normalize_category(float("nan")) == "SIN_CATEGORIA"


def test_normalize_category_unknown_value_is_desconocida():
    assert normalize_category("IV-9") == "DESCONOCIDA"


def test_no_category_i_series_ever_maps_into_resolutive_set():
    for cat in ["I-1", "I-2", "I-3", "I-4", "0", None, "IV-9"]:
        assert normalize_category(cat) not in RESOLUTIVE


def test_is_active_only_activo():
    assert is_active("ACTIVO") is True
    assert is_active("activo") is True  # tolera minúsculas
    for other in ["BAJA DEFINITIVA", "BAJA PROVISIONAL", "CIERRE TEMPORAL DE OFICIO", "CIERRE TEMPORAL DE PARTE", "BAJA DEFINITIVA DE OFICIO", "BAJA PROVISIONAL DE OFICIO", None]:
        assert is_active(other) is False


def test_resolutive_definition_active_and_category():
    # Replica la fórmula usada en build_facilities: is_active & categoria in resolutive_categories
    df = pd.DataFrame([
        {"estado": "ACTIVO", "categoria": "II-1"},          # resolutivo
        {"estado": "ACTIVO", "categoria": "I-1"},            # no resolutivo (categoría nivel I)
        {"estado": "BAJA DEFINITIVA", "categoria": "III-1"},  # no resolutivo (inactivo)
        {"estado": "ACTIVO", "categoria": "0"},               # no resolutivo (sin categoría)
    ])
    df["cat_norm"] = df["categoria"].map(normalize_category)
    df["active"] = df["estado"].map(is_active)
    df["resolutive"] = df["active"] & df["cat_norm"].isin(RESOLUTIVE)
    assert df["resolutive"].tolist() == [True, False, False, False]
