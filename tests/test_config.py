"""Tests de la Fase 0: config.md se parsea y expone los parámetros esperados."""

from __future__ import annotations

from src.config import (
    get_department_codes,
    get_department_names,
    get_departments,
    load_config,
)

EXPECTED_DEPARTMENTS = ["Tumbes", "Cusco", "Amazonas"]
EXPECTED_RESOLUTIVE = {"II-1", "II-2", "II-E", "III-1", "III-2", "III-E"}
EXPECTED_NONRESOLUTIVE = {"I-1", "I-2", "I-3", "I-4"}


def test_config_loads():
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert "departments" in cfg


def test_three_mandatory_departments():
    assert get_department_names() == EXPECTED_DEPARTMENTS


def test_department_codes_present_and_two_digits():
    codes = get_department_codes()
    assert set(codes) == set(EXPECTED_DEPARTMENTS)
    for name, code in codes.items():
        assert isinstance(code, str) and len(code) == 2 and code.isdigit(), (name, code)


def test_each_department_has_region():
    regions = {d["name"]: d["region"] for d in get_departments()}
    assert regions == {"Tumbes": "Costa", "Cusco": "Andes", "Amazonas": "Amazonía"}


def test_resolutive_category_sets():
    cfg = load_config()
    fac = cfg["facilities"]
    assert set(fac["resolutive_categories"]) == EXPECTED_RESOLUTIVE
    assert set(fac["nonresolutive_categories"]) == EXPECTED_NONRESOLUTIVE
    # I-* nunca puede colarse como resolutivo
    assert EXPECTED_NONRESOLUTIVE.isdisjoint(set(fac["resolutive_categories"]))


def test_demand_cap_is_5000():
    assert load_config()["demand"]["max_points"] == 5000


def test_access_thresholds():
    assert load_config()["access_thresholds_min"] == [30, 60, 120]


def test_sampling_seed_is_42():
    assert load_config()["demand"]["sampling"]["seed"] == 42


def test_crs_keys():
    crs = load_config()["crs"]
    assert crs["geographic"] == "EPSG:4326"
    assert crs["metric_clip"].startswith("EPSG:")
    # metric_area es una cónica de área equivalente (código ESRI), no EPSG
    assert crs["metric_area"] == "ESRI:102033"


def test_crs_values_resolve_in_pyproj():
    from pyproj import CRS

    crs = load_config()["crs"]
    for key in ("geographic", "metric_clip", "metric_area"):
        CRS.from_user_input(crs[key])  # no debe lanzar excepción


def test_paths_section_resolves():
    from src.config import get_path

    p = get_path("data_raw")
    assert p.name == "raw" and p.parent.name == "data"


def test_data_cutoff_dates_present():
    cutoff = load_config()["data_cutoff"]
    # Fechas ya fijadas (formato ISO), no "latest"
    for src_key in ("renipress", "sigmed_centros_poblados", "limites_administrativos_ign"):
        date = cutoff[src_key]["date"]
        assert date.count("-") == 2 and date[:4].isdigit(), (src_key, date)
    # OSM se descargó en Fase 2: fecha real (Last-Modified verificado), no inventada
    assert cutoff["osm_geofabrik"]["date"] == "2026-09-10"


def test_validation_rules_declared_for_all_six_checks():
    fac = load_config()["validation"]["facilities"]
    for rule in (
        "coord_missing",
        "coord_out_of_bbox",
        "swapped_latlon",
        "point_outside_declared_district",
        "duplicate_facility_code",
        "encoding_check",
    ):
        assert rule in fac, f"falta la regla de validación: {rule}"


def test_validation_policy_is_no_silent_drops():
    assert load_config()["validation"]["policy"] == "no_silent_drops"


def test_fase1_resolved_values_from_real_inspection():
    # Estos ya no son TBD: se resolvieron inspeccionando los archivos reales en Fase 1.
    cfg = load_config()
    assert cfg["validation"]["facilities"]["duplicate_facility_code"]["key_field"] == "COD_IPRESS"
    assert cfg["validation"]["demand"]["duplicate_facility_code"]["key_field"] == "CODCP"
    assert cfg["acquisition"]["renipress"]["encoding"] == "utf-8-sig"
    assert cfg["acquisition"]["renipress"]["sep"] == ";"
    assert cfg["acquisition"]["sigmed_centros_poblados"]["url"].endswith("CP_MED.zip")
    assert cfg["facilities"]["active_status_values"] == ["ACTIVO"]


def test_osm_cutoff_resolved_in_phase2():
    # Fase 2 descargó el PBF real; ya no es TBD.
    cutoff = load_config()["data_cutoff"]["osm_geofabrik"]
    assert cutoff["date"] == "2026-09-10"
    assert cutoff["resource"] == "peru-260910.osm.pbf"


def test_routing_engine_is_the_validated_decision():
    # Decisión validada con el usuario (2026-09-11): NetworkX local, no OSRM,
    # no API remota. Ver docs/01_routing_decision.md.
    assert load_config()["routing"]["engine"] == "networkx_local"
