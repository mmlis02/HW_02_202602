"""Tests de muestreo de demanda — sintéticos, sin leer SIGMED real."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.demand import (
    capacity_constrained_proportional_allocation,
    sample_if_needed,
    stratified_sample_by_district,
)


def _synthetic_cp(n_a: int, n_b: int, n_c: int) -> gpd.GeoDataFrame:
    rows = []
    for i in range(n_a):
        rows.append({"CODCP": f"A{i:04d}", "UBIGEO": "010101", "geometry": Point(-77.5, -5.0)})
    for i in range(n_b):
        rows.append({"CODCP": f"B{i:04d}", "UBIGEO": "080101", "geometry": Point(-71.9, -13.5)})
    for i in range(n_c):
        rows.append({"CODCP": f"C{i:04d}", "UBIGEO": "240101", "geometry": Point(-80.4, -3.5)})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def test_capacity_constrained_allocation_sums_to_target_and_respects_capacity():
    sizes = pd.Series({"d1": 100, "d2": 50, "d3": 5})
    quotas = capacity_constrained_proportional_allocation(sizes, 60)
    assert quotas.sum() == 60
    assert (quotas <= sizes).all()


def test_capacity_constrained_allocation_saturates_small_strata():
    # d3 tiene capacidad 2; pedir 90 de 102 disponibles fuerza a saturar d3 (2) y repartir el resto
    sizes = pd.Series({"d1": 100, "d2": 0, "d3": 2})
    quotas = capacity_constrained_proportional_allocation(sizes, 90)
    assert quotas["d3"] == 2  # saturado, no puede dar más de lo que tiene
    assert quotas.sum() == 90


def test_stratified_sample_is_deterministic_with_same_seed():
    gdf = _synthetic_cp(600, 300, 100)  # total 1000
    s1 = stratified_sample_by_district(gdf, "UBIGEO", 200, seed=42)
    s2 = stratified_sample_by_district(gdf, "UBIGEO", 200, seed=42)
    assert sorted(s1["CODCP"]) == sorted(s2["CODCP"])
    assert len(s1) == 200


def test_stratified_sample_is_proportional_to_district_count():
    gdf = _synthetic_cp(600, 300, 100)  # 60% / 30% / 10%
    sample = stratified_sample_by_district(gdf, "UBIGEO", 100, seed=42)
    counts = sample["UBIGEO"].value_counts()
    assert counts.get("010101", 0) in range(55, 66)   # ~60 ± tolerancia de redondeo
    assert counts.get("080101", 0) in range(25, 36)   # ~30
    assert counts.get("240101", 0) in range(5, 16)    # ~10


def test_sample_if_needed_no_sampling_below_threshold():
    gdf = _synthetic_cp(10, 10, 10)  # 30 <= 5000
    out, was_sampled = sample_if_needed(gdf, "UBIGEO", 5000, seed=42)
    assert was_sampled is False
    assert len(out) == 30


def test_sample_if_needed_samples_above_threshold():
    gdf = _synthetic_cp(4000, 3000, 3000)  # 10000 > 5000
    out, was_sampled = sample_if_needed(gdf, "UBIGEO", 5000, seed=42)
    assert was_sampled is True
    assert len(out) == 5000
