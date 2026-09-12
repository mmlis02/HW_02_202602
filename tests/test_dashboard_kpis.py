"""Tests de src/dashboard/kpis.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.dashboard.kpis import (
    kpi_header,
    population_gt_threshold_routed,
    population_le_threshold,
    population_no_time_estimate,
    total_population_frame,
    weighted_mean_access_kpi,
    weighted_median_access_kpi,
    worst_computable_district,
)


def _df():
    return pd.DataFrame({
        "t_min": [10.0, 90.0, np.nan, 40.0],
        "calibrated_weight": [100.0, 50.0, 30.0, 20.0],
    })


def test_total_population_frame_sums_all_valid_weight():
    assert total_population_frame(_df()) == pytest.approx(200.0)


def test_population_le_threshold():
    assert population_le_threshold(_df(), 60.0) == pytest.approx(120.0)  # 10min(100) + 40min(20)


def test_population_gt_threshold_routed_excludes_no_time_estimate():
    gt = population_gt_threshold_routed(_df(), 60.0)
    assert gt == pytest.approx(50.0)  # solo el de 90min, NUNCA el NaN (peso 30)


def test_population_no_time_estimate_separate_category():
    assert population_no_time_estimate(_df()) == pytest.approx(30.0)


def test_kpi_header_percentages_use_frame_denominator_not_routed_only():
    h = kpi_header(_df(), pd.DataFrame(), threshold_min=60.0)
    assert h["total_population_frame"] == pytest.approx(200.0)
    assert h["pct_le_threshold_of_frame"] == pytest.approx(60.0)  # 120/200
    assert h["pct_no_time_estimate_of_frame"] == pytest.approx(15.0)  # 30/200


def test_weighted_mean_and_median_ignore_no_time_estimate():
    mean = weighted_mean_access_kpi(_df())
    median = weighted_median_access_kpi(_df())
    assert not np.isnan(mean)
    assert not np.isnan(median)


def test_empty_dataframe_does_not_crash_and_returns_nan_or_zero():
    empty = pd.DataFrame({"t_min": [], "calibrated_weight": []})
    h = kpi_header(empty, pd.DataFrame())
    assert h["total_population_frame"] == 0.0
    assert np.isnan(h["pct_le_threshold_of_frame"])
    assert np.isnan(h["weighted_mean_access_min"])
    assert h["worst_district"] is None


def test_worst_computable_district_picks_highest_mean_only_from_computable_table():
    worst_df = pd.DataFrame({"DIST": ["A", "B"], "weighted_mean_access_min": [50.0, 200.0]})
    result = worst_computable_district(worst_df)
    assert result["DIST"] == "B"


def test_worst_computable_district_none_when_empty():
    assert worst_computable_district(pd.DataFrame()) is None
    assert worst_computable_district(None) is None
