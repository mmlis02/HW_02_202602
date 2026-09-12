"""data — carga y cache de outputs precomputados (Fase 4).

Todas las funciones leen de `data/processed/`/`data/outputs/` — NUNCA llaman
routing, NUNCA abren el PBF, NUNCA reconstruyen grafos ni recalculan pesos.
`@st.cache_data` evita releer/reparsear archivos en cada interacción de la
UI. Los archivos GRANDES (matriz de upgrade, 1.86M filas) tienen su propio
loader para poder diferir la carga hasta que el usuario abra el tab del
simulador (sección 25 del enunciado — performance).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import streamlit as st

from src.config import get_path, load_config

_CFG = load_config()
_OUT = get_path("data_outputs", _CFG)
_PROC = get_path("data_processed", _CFG)


@st.cache_data(show_spinner=False)
def load_demand_analysis() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "demand_analysis.parquet")


@st.cache_data(show_spinner=False)
def load_district_metrics() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "dashboard_district_metrics.parquet")


@st.cache_data(show_spinner=False)
def load_district_geometries() -> gpd.GeoDataFrame:
    return gpd.read_parquet(_OUT / "dashboard_district_geometries_simplified.parquet")


@st.cache_data(show_spinner=False)
def load_facilities() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "dashboard_facilities.parquet")


@st.cache_data(show_spinner=False)
def load_worst_computable_districts() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "worst_computable_districts.parquet")


@st.cache_data(show_spinner=False)
def load_districts_with_insufficient_data() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "districts_with_insufficient_data.parquet")


@st.cache_data(show_spinner=False)
def load_urban_rural_summary() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "urban_rural_summary.parquet")


@st.cache_data(show_spinner=False)
def load_candidate_scores() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "dashboard_candidate_scores.parquet")


@st.cache_data(show_spinner=False)
def load_nearest_resolutive_car() -> pd.DataFrame:
    """Solo para el simulador — tiempo BASELINE actual (Fase 2/3, ya
    calculado). ~5000 filas, liviano."""
    df = pd.read_parquet(_OUT / "nearest_resolutive_by_mode.parquet")
    return df[df["mode"] == "car"]


@st.cache_data(show_spinner=False)
def load_upgrade_matrix() -> pd.DataFrame:
    """Matriz completa demand×candidato (1.86M filas, ~372 candidatos) — se
    carga SOLO cuando el usuario abre/usa el simulador, nunca en el resto de
    tabs (performance, sección 25/11)."""
    return pd.read_parquet(
        _OUT / "routing_matrix_upgrade_candidates_car.parquet",
        columns=["demand_id", "facility_id", "travel_time_min", "reachable", "routing_status"],
    )


@st.cache_data(show_spinner=False)
def load_phase3_summary() -> dict:
    df = pd.read_csv(_OUT / "phase3_summary.csv")
    return df.iloc[0].to_dict()


@st.cache_data(show_spinner=False)
def load_routing_quality_report() -> dict:
    df = pd.read_csv(_OUT / "routing_quality_report.csv")
    return dict(zip(df["metric"], df["value"]))


@st.cache_data(show_spinner=False)
def load_data_quality_report() -> pd.DataFrame:
    return pd.read_csv(_OUT / "data_quality_report.csv")


@st.cache_data(show_spinner=False)
def load_weight_diagnostics() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "weight_diagnostics.parquet")


@st.cache_data(show_spinner=False)
def load_weight_calibration_by_district() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "weight_calibration_by_district.parquet")


@st.cache_data(show_spinner=False)
def load_phase3_metrics_ht_vs_calibrated() -> pd.DataFrame:
    return pd.read_parquet(_OUT / "phase3_metrics_ht_vs_calibrated.parquet")
