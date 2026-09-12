"""Tests de src/analysis.py — clasificación urbano/rural censal (MINAM) y
adquisición paginada ArcGIS (CENEPRED/MINAM). Todo sintético/mockeado, no
descarga nada real."""

from __future__ import annotations

import pandas as pd
import pytest

from src.analysis import build_population_universe_unique, build_urban_rural_classification_censal
from src import acquisition as acq
from src import metrics as m


def test_urban_rural_censal_mapping_and_unknown_for_unmatched_or_value3():
    demand_df = pd.DataFrame({
        "CODCP": ["d1", "d2", "d3", "d4"],
        "CPINEI": ["k1", "k2", "k3", None],
    })
    minam_df = pd.DataFrame({"idccpp_17": ["k1", "k2", "k3"], "area_17": [1, 2, 3]})
    out = build_urban_rural_classification_censal(demand_df, minam_df)
    out = out.set_index("demand_id")
    assert out.loc["d1", "urban_rural"] == "urban"
    assert out.loc["d2", "urban_rural"] == "rural"
    assert out.loc["d3", "urban_rural"] == "unknown"  # area_17==3, sin documentacion oficial -> no se adivina
    assert out.loc["d4", "urban_rural"] == "unknown"  # sin CPINEI


def test_urban_rural_censal_ids_preserved_as_strings_with_leading_zeros():
    demand_df = pd.DataFrame({"CODCP": ["d1"], "CPINEI": ["0808070024"]})
    minam_df = pd.DataFrame({"idccpp_17": ["0808070024"], "area_17": [1]})
    out = build_urban_rural_classification_censal(demand_df, minam_df)
    assert out["urban_rural"].iloc[0] == "urban"


# --------------------------------------------------------------------------
# Paginación ArcGIS (mockeada) + preservación de IDs con ceros
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_arcgis_pagination_follows_offset_until_empty_page(monkeypatch):
    pages = [
        {"features": [{"attributes": {"codccpp": "0000000001"}}, {"attributes": {"codccpp": "0000000002"}}]},
        {"features": [{"attributes": {"codccpp": "0000000003"}}]},
        {"features": []},
    ]
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params["resultOffset"])
        return _FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr(acq.requests, "get", fake_get)
    feats = acq.fetch_arcgis_layer_paginated(
        "http://fake/query", where="1=1", out_fields="codccpp", page_size=2,
    )
    assert [f["attributes"]["codccpp"] for f in feats] == ["0000000001", "0000000002", "0000000003"]
    assert calls == [0, 2]  # se detiene apenas una página trae menos de page_size


def test_arcgis_pagination_raises_on_service_error(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse({"error": {"code": 500, "message": "boom"}})

    monkeypatch.setattr(acq.requests, "get", fake_get)
    with pytest.raises(RuntimeError):
        acq.fetch_arcgis_layer_paginated("http://fake/query", where="1=1", out_fields="codccpp", page_size=2)


def test_acquire_arcgis_ccpp_preserves_leading_zero_ids(monkeypatch, tmp_path):
    pages_by_dep = {
        "TUMBES": [{"attributes": {"codccpp": "0000000099", "nomb_dep": "TUMBES"}}],
        "CUSCO": [],
    }

    def fake_fetch(url, *, where, out_fields, page_size, order_by_field=None):
        dep = where.split("'")[1]
        return pages_by_dep.get(dep, [])

    monkeypatch.setattr(acq, "fetch_arcgis_layer_paginated", fake_fetch)
    result = acq.acquire_arcgis_ccpp(
        source_name="fake", service_query_url="http://fake/query",
        departments=["TUMBES", "CUSCO"], dep_field="nomb_dep",
        out_fields="codccpp,nomb_dep", id_field="codccpp", dest_dir=tmp_path,
    )
    df = pd.read_parquet(result.path)
    assert df["codccpp"].iloc[0] == "0000000099"
    assert isinstance(df["codccpp"].iloc[0], str)
    assert result.manifest["n_records_by_department"] == {"TUMBES": 1, "CUSCO": 0}


# --------------------------------------------------------------------------
# Universo censal matched único (U4) sin doble conteo
# --------------------------------------------------------------------------


def test_population_universe_unique_counts_duplicated_census_cp_once():
    # 2 filas SIGMED comparten CPINEI=k1 (mismo CP censal); solo la elegida
    # como representante debe aportar la poblacion, UNA sola vez.
    sigmed_full = pd.DataFrame({
        "CODCP": ["a", "b", "c"], "CPINEI": ["k1", "k1", "k2"],
        "DEP": ["X", "X", "Y"], "PROV": ["P1", "P1", "P2"], "DIST": ["D1", "D1", "D2"],
    })
    pop_df = pd.DataFrame({"codigo": ["k1", "k2"], "pob": [69, 100]})
    out = build_population_universe_unique(
        sigmed_full, pop_df, population_key_col="codigo", population_value_col="pob",
        representative_override={"k1": "a"},
    )
    assert len(out) == 2  # una fila por CP censal UNICO, no por fila SIGMED
    assert out["population"].sum() == 169  # 69 + 100, NUNCA 69+69+100
    assert out.set_index("census_cp_id").loc["k1", "representative_demand_id"] == "a"


def test_population_universe_unique_excludes_duplicate_without_override():
    sigmed_full = pd.DataFrame({
        "CODCP": ["a", "b"], "CPINEI": ["k1", "k1"], "DEP": ["X"] * 2, "PROV": ["P"] * 2, "DIST": ["D"] * 2,
    })
    pop_df = pd.DataFrame({"codigo": ["k1"], "pob": [69]})
    out = build_population_universe_unique(sigmed_full, pop_df, population_key_col="codigo", population_value_col="pob", representative_override={})
    assert len(out) == 0  # sin override, la clave duplicada queda como excepcion explicita, no se cuenta


def test_acquire_arcgis_ccpp_is_idempotent_second_call_skips_network(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_fetch(url, *, where, out_fields, page_size, order_by_field=None):
        call_count["n"] += 1
        return [{"attributes": {"codccpp": "1", "nomb_dep": "TUMBES"}}]

    monkeypatch.setattr(acq, "fetch_arcgis_layer_paginated", fake_fetch)
    kwargs = dict(
        source_name="fake", service_query_url="http://fake/query",
        departments=["TUMBES"], dep_field="nomb_dep",
        out_fields="codccpp,nomb_dep", id_field="codccpp", dest_dir=tmp_path,
    )
    r1 = acq.acquire_arcgis_ccpp(**kwargs)
    r2 = acq.acquire_arcgis_ccpp(**kwargs)
    assert r1.was_downloaded is True
    assert r2.was_downloaded is False
    assert call_count["n"] == 1  # la segunda llamada no volvió a pedir la red
