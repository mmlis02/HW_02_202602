"""Tests del motor de validación (Fase 1) — todo con datos sintéticos en memoria.

No descargan ni requieren ningún dataset real (política del enunciado: los
tests no dependen de tener los raw completos en disco).
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from src import validation as val

PERU_BBOX = [-81.4, -18.4, -68.6, 0.0]


def _gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    df = pd.DataFrame(rows)
    geometry = [Point(r["lon"], r["lat"]) if pd.notna(r["lon"]) and pd.notna(r["lat"]) else None for r in rows]
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")


# ------------------------------------------------------------- regla 1 ---
def test_coord_missing_flags_null_and_zero():
    gdf = _gdf([
        {"key": "a", "lon": -71.9, "lat": -13.5},
        {"key": "b", "lon": None, "lat": None},
        {"key": "c", "lon": 0, "lat": 0},
    ])
    outcome, mask = val.check_coord_missing(gdf, "lon", "lat", {"treat_zero_as_missing": True, "action": "keep_flag_exclude_from_routing"})
    assert mask.tolist() == [False, True, True]
    assert outcome.n_affected == 2
    assert outcome.n_dropped == 0  # no_silent_drops: se marca, no se borra


def test_coord_missing_zero_not_flagged_if_disabled():
    gdf = _gdf([{"key": "a", "lon": 0, "lat": 0}])
    _, mask = val.check_coord_missing(gdf, "lon", "lat", {"treat_zero_as_missing": False, "action": "x"})
    assert mask.tolist() == [False]


# ------------------------------------------------------------- regla 2 ---
def test_coord_out_of_bbox():
    gdf = _gdf([
        {"key": "inside", "lon": -71.9, "lat": -13.5},
        {"key": "outside", "lon": 10.0, "lat": 50.0},  # Europa, claramente fuera
    ])
    missing = pd.Series([False, False])
    outcome, mask = val.check_coord_out_of_bbox(gdf, "lon", "lat", PERU_BBOX, {"action": "keep_flag_exclude_from_routing"}, missing)
    assert mask.tolist() == [False, True]
    assert outcome.n_affected == 1


def test_coord_out_of_bbox_does_not_double_count_missing():
    gdf = _gdf([{"key": "a", "lon": None, "lat": None}])
    missing = pd.Series([True])
    _, mask = val.check_coord_out_of_bbox(gdf, "lon", "lat", PERU_BBOX, {"action": "x"}, missing)
    assert mask.tolist() == [False]  # ya contado en regla 1, no se duplica en regla 2


# ------------------------------------------------------------- regla 3 ---
def test_swapped_latlon_detected_and_ambiguous_without_districts():
    # Cusco real: lat=-13.52, lon=-71.97. Si vienen invertidas: lon=-13.52, lat=-71.97
    gdf = _gdf([{"key": "swapped", "lon": -13.52, "lat": -71.97, "UBIGEO": "080101"}])
    missing = pd.Series([False])
    _, out_mask = val.check_coord_out_of_bbox(gdf, "lon", "lat", PERU_BBOX, {"action": "x"}, missing)
    assert out_mask.tolist() == [True]  # el par original SÍ está fuera de bbox

    rule_cfg = {
        "enabled": True, "confirm_with_district_polygon": True,
        "action_if_unambiguous": "correct_with_audit", "action_if_ambiguous": "keep_warning",
    }
    outcome, corrected, ambiguous, gdf2 = val.check_swapped_latlon(gdf, "lon", "lat", PERU_BBOX, rule_cfg, out_mask)
    assert outcome.n_affected == 1
    assert ambiguous.tolist() == [True]     # sin límites de distrito, no se corrige a ciegas
    assert corrected.tolist() == [False]
    assert gdf2.loc[0, "lon"] == -13.52     # no se tocó


def test_swapped_latlon_corrected_when_district_confirms():
    gdf = _gdf([{"key": "swapped", "lon": -13.52, "lat": -71.97, "UBIGEO": "080101"}])
    missing = pd.Series([False])
    _, out_mask = val.check_coord_out_of_bbox(gdf, "lon", "lat", PERU_BBOX, {"action": "x"}, missing)

    # Polígono de distrito que SÍ cubre el punto corregido (lon=-71.97, lat=-13.52)
    poly = Polygon([(-72.5, -14.0), (-71.5, -14.0), (-71.5, -13.0), (-72.5, -13.0)])
    districts = gpd.GeoDataFrame({"UBIGEO": ["080101"]}, geometry=[poly], crs="EPSG:4326")

    rule_cfg = {
        "enabled": True, "confirm_with_district_polygon": True,
        "action_if_unambiguous": "correct_with_audit", "action_if_ambiguous": "keep_warning",
    }
    outcome, corrected, ambiguous, gdf2 = val.check_swapped_latlon(
        gdf, "lon", "lat", PERU_BBOX, rule_cfg, out_mask,
        districts_gdf=districts, declared_ubigeo_col="UBIGEO", containment_buffer_m=1000, metric_crs="EPSG:32718",
    )
    assert corrected.tolist() == [True]
    assert ambiguous.tolist() == [False]
    assert gdf2.loc[0, "lon"] == pytest.approx(-71.97)
    assert gdf2.loc[0, "lat"] == pytest.approx(-13.52)


def test_swapped_latlon_no_candidates_when_within_bbox():
    gdf = _gdf([{"key": "ok", "lon": -71.9, "lat": -13.5, "UBIGEO": "080101"}])
    out_mask = pd.Series([False])
    rule_cfg = {"enabled": True, "confirm_with_district_polygon": True, "action_if_unambiguous": "x", "action_if_ambiguous": "y"}
    outcome, corrected, ambiguous, _ = val.check_swapped_latlon(gdf, "lon", "lat", PERU_BBOX, rule_cfg, out_mask)
    assert outcome.n_affected == 0
    assert not corrected.any() and not ambiguous.any()


# ------------------------------------------------------------- regla 4 ---
def test_point_outside_declared_district():
    inside_poly = Polygon([(-72.5, -14.0), (-71.5, -14.0), (-71.5, -13.0), (-72.5, -13.0)])
    districts = gpd.GeoDataFrame({"UBIGEO": ["080101"]}, geometry=[inside_poly], crs="EPSG:4326")
    gdf = _gdf([
        {"key": "inside", "lon": -71.9, "lat": -13.5, "UBIGEO": "080101"},
        {"key": "outside", "lon": -60.0, "lat": -13.5, "UBIGEO": "080101"},  # muy lejos del polígono declarado
    ])
    valid = pd.Series([True, True])
    outcome, mismatch = val.check_point_outside_declared_district(
        gdf, districts, "UBIGEO", {"containment_buffer_m": 1000, "action": "keep_warning"}, valid, metric_crs="EPSG:32718",
    )
    assert mismatch.tolist() == [False, True]
    assert outcome.n_affected == 1


# ------------------------------------------------------------- regla 5 ---
def test_duplicate_key_exact_vs_conflicting():
    df = pd.DataFrame([
        {"key": "K1", "name": "A"},
        {"key": "K1", "name": "A"},   # duplicado EXACTO de la fila anterior
        {"key": "K2", "name": "B"},
        {"key": "K2", "name": "C"},   # mismo key, dato distinto -> conflicto
        {"key": "K3", "name": "D"},
    ])
    outcome, exact_drop, conflicting = val.check_duplicate_key(
        df, "key", {"exact_duplicate_action": "drop_duplicate_keep_first", "conflicting_duplicate_action": "keep_warning"}
    )
    assert exact_drop.tolist() == [False, True, False, False, False]
    assert conflicting.tolist() == [False, False, True, True, False]
    assert outcome.n_dropped == 1
    assert outcome.n_warnings == 2
    assert outcome.n_affected == 4  # K1 aparece 2 veces + K2 aparece 2 veces = 4 filas con key repetida


# ------------------------------------------------------------- regla 6 ---
def test_encoding_clean_text_passes():
    s = pd.Series(["SEÑOR DE LOS MILAGROS", "CHACHAPOYAS", "QUILLABAMBA"])
    outcome = val.check_encoding([s], {"max_mojibake_pct_alarm": 1.0, "action": "keep_warning"}, "utf-8-sig")
    assert outcome.n_affected == 0
    assert outcome.action == "verificado_ok"


def test_encoding_mojibake_detected():
    s = pd.Series(["SEÃ‘OR", "CHACHAPOYAS", "NIÃ‘O"])  # "Ñ" mal decodificada
    outcome = val.check_encoding([s], {"max_mojibake_pct_alarm": 1.0, "action": "keep_warning"}, "latin-1")
    assert outcome.n_affected == 2
    assert outcome.action == "keep_warning"


# ------------------------------------------------------------- alarma ---
def test_check_alarm_triggers_above_threshold():
    assert val.check_alarm(20, 100, 15.0, "x") is not None   # 20% > 15%
    assert val.check_alarm(10, 100, 15.0, "x") is None       # 10% <= 15%


# ------------------------------------------------------------- reporte ---
def test_build_quality_report_and_audit_detail():
    o = val.RuleOutcome("1. test", 2, "keep_warning", 0, 0, 2, "justificación", affected_index=[0, 1])
    report = val.build_quality_report([o])
    assert list(report.columns) == ["regla", "n_afectados", "accion", "n_corregidos", "n_eliminados", "n_warnings", "justificacion"]
    assert report.iloc[0]["n_afectados"] == 2

    gdf = _gdf([{"key": "a", "lon": -71.9, "lat": -13.5}, {"key": "b", "lon": -71.9, "lat": -13.5}])
    flags = {"qc_x": pd.Series([True, False])}
    audit = val.build_audit_detail(gdf, "key", flags, dataset_name="demo")
    assert len(audit) == 1
    assert audit.iloc[0]["record_key"] == "a"
