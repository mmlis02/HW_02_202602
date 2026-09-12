"""Tests de integración de Fase 1 (auditoría 2026-09-11).

Ejercitan la orquestación completa (`process_facilities`, `process_demand`,
`load_ign_departments`+`load_ign_districts`+`derive_provinces`) con datos
sintéticos en memoria — sin descargar ni leer el CSV/shapefile real. Cubren
específicamente las correcciones de la Parte A: propagación de
`qc_district_mismatch`, conservación de `CPINEI`/`CPINEI2`, `record_key` con
ceros a la izquierda, coordenada "casi cero", y `inclusion_prob`/`design_weight`.
"""

from __future__ import annotations

import copy

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from src import validation as val
from src.boundaries import derive_provinces, filter_to_study_departments
from src.config import load_config
from src.demand import DESIGN_WEIGHT_COLS, process_demand
from src.facilities import process_facilities

# Dos distritos de Tumbes, sintéticos pero con UBIGEO/CODDEP reales de la
# configuración (24 = Tumbes), adyacentes y bien separados (>1 km) para que la
# regla 4 no dependa de casos límite de buffer.
DIST_A = box(-80.60, -3.60, -80.50, -3.50)   # UBIGEO 240101
DIST_B = box(-80.50, -3.60, -80.40, -3.50)   # UBIGEO 240102
POINT_IN_A = (-80.55, -3.55)
POINT_IN_B = (-80.45, -3.55)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def districts_gdf():
    return gpd.GeoDataFrame(
        {
            "UBIGEO": ["240101", "240102"],
            "CODDEP": ["24", "24"],
            "DEPARTAMEN": ["TUMBES", "TUMBES"],
            "CODPROV": ["01", "01"],
            "PROVINCIA": ["TUMBES", "TUMBES"],
            "CODDIST": ["01", "02"],
            "DISTRITO": ["TUMBES", "CORRALES"],
        },
        geometry=[DIST_A, DIST_B],
        crs="EPSG:4326",
    )


def _renipress_row(**kw) -> dict:
    base = dict(
        INSTITUCION="PRIVADO", NOMBRE="X", CLASIFICACION="X", TIPO_ESTABLECIMIENTO="X",
        DEPARTAMENTO="TUMBES", PROVINCIA="TUMBES", DISTRITO="TUMBES", UBIGEO="240101",
        DIRECCION="X", CATEGORIA="I-1", ESTADO="ACTIVO", NORTE=None, ESTE=None,
    )
    base.update(kw)
    return base


class TestProcessFacilitiesIntegration:
    def test_district_mismatch_propagates_to_output(self, cfg, districts_gdf):
        lon_a, lat_a = POINT_IN_A
        lon_b, lat_b = POINT_IN_B
        df = pd.DataFrame([
            _renipress_row(COD_IPRESS="00000001", CATEGORIA="II-1", UBIGEO="240101", NORTE=lat_a, ESTE=lon_a),
            # declara distrito 240101 pero las coordenadas caen en 240102 (>1km, no es borde)
            _renipress_row(COD_IPRESS="00000002", CATEGORIA="II-2", UBIGEO="240101", NORTE=lat_b, ESTE=lon_b),
        ])
        result = process_facilities(df, cfg, districts_gdf=districts_gdf)
        gdf = result["gdf"]
        assert "qc_district_mismatch" in gdf.columns  # se conserva en el output, no solo en el audit
        row1 = gdf[gdf["COD_IPRESS"] == "00000001"].iloc[0]
        row2 = gdf[gdf["COD_IPRESS"] == "00000002"].iloc[0]
        assert row1["qc_district_mismatch"] is False or row1["qc_district_mismatch"] == False  # noqa: E712
        assert bool(row2["qc_district_mismatch"]) is True
        # keep_warning: NO se cambió el distrito/UBIGEO declarado
        assert row2["UBIGEO"] == "240101"
        assert bool(row2["is_resolutive"]) is True  # la bandera no excluye del cálculo (política keep_warning)

    def test_record_key_keeps_leading_zeros_through_pipeline(self, cfg, districts_gdf):
        lon_a, lat_a = POINT_IN_A
        df = pd.DataFrame([_renipress_row(COD_IPRESS="00000007", NORTE=lat_a, ESTE=lon_a)])
        result = process_facilities(df, cfg, districts_gdf=districts_gdf)
        assert result["gdf"]["COD_IPRESS"].iloc[0] == "00000007"
        assert len(result["gdf"]["COD_IPRESS"].iloc[0]) == 8

    def test_near_zero_coordinate_classified_as_rule1_not_rule2(self, cfg, districts_gdf):
        df = pd.DataFrame([
            _renipress_row(COD_IPRESS="00000009", NORTE=-6e-8, ESTE=-7.8e-7),
        ])
        result = process_facilities(df, cfg, districts_gdf=districts_gdf)
        by_rule = {o.rule: o for o in result["quality_outcomes"]}
        assert by_rule["1. coordenadas ausentes/null/cero"].n_affected == 1
        assert by_rule["2. coordenadas fuera del bbox de Perú"].n_affected == 0
        assert bool(result["gdf"]["qc_excluded_from_routing"].iloc[0]) is True


class TestProcessDemandIntegration:
    def _sigmed_row(self, **kw) -> dict:
        base = dict(
            UBIGEO="240101", DEP="TUMBES", PROV="TUMBES", DIST="TUMBES", CODCP="000000",
            NOMCP="X", MNOMCP="X", CAPITAL=0, CON_IE=0, NIVEL="P",
            CPINEI="2401010001", CPINEI2=None, FUENTE_G="MED-GPS", Z=10.0,
        )
        base.update(kw)
        return base

    def _make_gdf(self, rows: list[dict]) -> gpd.GeoDataFrame:
        geometry = [Point(r["XGD"], r["YGD"]) for r in rows]
        return gpd.GeoDataFrame(rows, geometry=geometry, crs="EPSG:4326")

    def test_cpinei_preserved_and_district_mismatch_propagates(self, cfg, districts_gdf):
        lon_a, lat_a = POINT_IN_A
        lon_b, lat_b = POINT_IN_B
        rows = [
            self._sigmed_row(CODCP="000001", UBIGEO="240101", XGD=lon_a, YGD=lat_a, CPINEI="2401010001"),
            self._sigmed_row(CODCP="000002", UBIGEO="240101", XGD=lon_b, YGD=lat_b, CPINEI="2401010002"),
        ]
        gdf_raw = self._make_gdf(rows)
        result = process_demand(gdf_raw, cfg, districts_gdf=districts_gdf)
        out = result["gdf"]
        assert "CPINEI" in out.columns and "CPINEI2" in out.columns
        assert "qc_district_mismatch" in out.columns
        assert out.set_index("CODCP").loc["000002", "qc_district_mismatch"] == True  # noqa: E712
        assert out.set_index("CODCP").loc["000001", "qc_district_mismatch"] == False  # noqa: E712
        # CODCP conserva ceros a la izquierda
        assert set(out["CODCP"]) == {"000001", "000002"}

    def test_cpinei_absent_in_raw_is_not_invented(self, cfg, districts_gdf):
        lon_a, lat_a = POINT_IN_A
        rows = [self._sigmed_row(CODCP="000003", XGD=lon_a, YGD=lat_a)]
        gdf_raw = self._make_gdf(rows)
        gdf_raw = gdf_raw.drop(columns=["CPINEI", "CPINEI2"])  # simula un corte de SIGMED sin esas columnas
        result = process_demand(gdf_raw, cfg, districts_gdf=districts_gdf)
        assert "CPINEI" not in result["gdf"].columns  # no se inventa si no existe en el raw

    def test_near_zero_coordinate_classified_as_rule1(self, cfg, districts_gdf):
        rows = [self._sigmed_row(CODCP="000004", XGD=-7.8e-7, YGD=-6e-8)]
        gdf_raw = self._make_gdf(rows)
        result = process_demand(gdf_raw, cfg, districts_gdf=districts_gdf)
        by_rule = {o.rule: o for o in result["quality_outcomes"]}
        assert by_rule["1. coordenadas ausentes/null/cero"].n_affected == 1
        assert by_rule["2. coordenadas fuera del bbox de Perú"].n_affected == 0

    def test_design_weights_computed_when_sampling_triggers(self, cfg, districts_gdf):
        lon_a, lat_a = POINT_IN_A
        cfg2 = copy.deepcopy(cfg)
        cfg2["demand"]["max_points"] = 3  # forzar muestreo con pocos puntos sintéticos
        rows = [
            self._sigmed_row(CODCP=f"{i:06d}", XGD=lon_a + i * 0.001, YGD=lat_a, CPINEI=f"24010100{i:02d}")
            for i in range(6)
        ]
        gdf_raw = self._make_gdf(rows)
        result = process_demand(gdf_raw, cfg2, districts_gdf=districts_gdf)
        out = result["gdf"]
        assert result["was_sampled"] is True
        assert len(out) == 3
        for col in DESIGN_WEIGHT_COLS:
            assert col in out.columns
        assert (out["inclusion_prob"] == out["stratum_sample_n"] / out["stratum_n"]).all()
        assert (out["design_weight"] == 1.0 / out["inclusion_prob"]).all()
        assert out["stratum_n"].iloc[0] == 6   # los 6 sintéticos caen en el mismo distrito 240101
        assert out["stratum_sample_n"].iloc[0] == 3

    def test_no_sampling_below_threshold_gives_census_weights(self, cfg, districts_gdf):
        lon_a, lat_a = POINT_IN_A
        rows = [self._sigmed_row(CODCP=f"{i:06d}", XGD=lon_a, YGD=lat_a) for i in range(2)]
        gdf_raw = self._make_gdf(rows)
        result = process_demand(gdf_raw, cfg, districts_gdf=districts_gdf)  # max_points real = 5000
        assert result["was_sampled"] is False
        assert (result["gdf"]["inclusion_prob"] == 1.0).all()
        assert (result["gdf"]["design_weight"] == 1.0).all()


class TestBoundariesIntegration:
    def test_load_derive_filter_chain_is_consistent(self):
        # Distritos sintéticos de 2 "departamentos": 24 (en ámbito) y 99 (fuera)
        districts = gpd.GeoDataFrame(
            {
                "UBIGEO": ["240101", "240102", "990101"],
                "CODDEP": ["24", "24", "99"],
                "DEPARTAMEN": ["TUMBES", "TUMBES", "OTRO"],
                "CODPROV": ["01", "01", "01"],
                "PROVINCIA": ["TUMBES", "TUMBES", "OTRO"],
                "CODDIST": ["01", "02", "01"],
                "DISTRITO": ["TUMBES", "CORRALES", "X"],
            },
            geometry=[DIST_A, DIST_B, box(0, 0, 1, 1)],
            crs="EPSG:4326",
        )
        prov = derive_provinces(districts)
        assert len(prov) == 2  # (24,01) y (99,01)
        assert set(prov["UBIGEO_PROV"]) == {"2401", "9901"}

        dist_filtered = filter_to_study_departments(districts, ["24"], "CODDEP")
        prov_filtered = filter_to_study_departments(prov, ["24"], "CODDEP")
        assert len(dist_filtered) == 2
        assert len(prov_filtered) == 1
        assert prov_filtered.iloc[0]["UBIGEO_PROV"] == "2401"
        # área de la provincia derivada == suma de sus distritos (mismo CRS, sin huecos)
        assert prov_filtered.to_crs("EPSG:32718").area.sum() == pytest.approx(
            dist_filtered.to_crs("EPSG:32718").area.sum(), rel=1e-9
        )
