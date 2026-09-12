"""Tests de src/dashboard/quality.py — preparación del panel de calidad."""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.quality import summarize_facility_quality, summarize_population_quality, summarize_routing_quality, summarize_statistical_quality


def test_summarize_facility_quality_filters_only_facilities_dataset():
    df = pd.DataFrame({
        "dataset": ["facilities", "demand"], "regla": ["coords ausentes", "coords ausentes"],
        "n_afectados": [602, 0], "accion": ["keep_flag", "keep_flag"], "justificacion": ["x", "y"],
    })
    out = summarize_facility_quality(df)
    assert len(out) == 1
    assert out.iloc[0]["n_afectados"] == 602


def test_summarize_routing_quality_computes_percentages():
    rq = {"demand_total": "5000", "car_snap_failed": "326", "car_no_route_same_department": "953", "car_matrix_cross_department_pct": "40.47", "car_track_fallback_speed_kmh": "12", "car_track_recovers_route_to_resolutive": "408"}
    out = summarize_routing_quality(rq)
    assert out["car_snap_failed_pct"] == pytest.approx(100 * 326 / 5000)
    assert out["car_no_route_same_department_pct"] == pytest.approx(100 * 953 / 5000)


def test_summarize_population_quality_reports_outside_frame_and_impossible_districts():
    phase3_summary = {"u2_total_population": 1809774.0, "u4_total_population": 1800859.0, "frame_coverage_u4_over_u2_pct": 99.51, "pct_population_matched": 62.78}
    calib = pd.DataFrame({"calibration_status": ["calibrated", "impossible_no_sample", "impossible_no_sample"], "known_population": [100.0, 6.0, 58541.0]})
    out = summarize_population_quality(phase3_summary, calib)
    assert out["outside_sigmed_frame_population"] == pytest.approx(8915.0)
    assert out["n_districts_calibration_impossible"] == 2
    assert out["population_calibration_impossible"] == pytest.approx(58547.0)


def test_summarize_statistical_quality_extreme_factor_counts():
    phase3_summary = {"weighted_mean_access_min_ht": 39.1, "weighted_mean_access_min_calibrated": 32.4, "weighted_gini_access": 0.5}
    diag = pd.DataFrame({"scope": ["TOTAL", "CUSCO"], "n_eff_ht": [31.5, 15.8], "n_eff_calibrated": [88.9, 63.0]})
    calib = pd.DataFrame({"calibration_factor": [0.1, 0.6, 3.0, None]})
    out = summarize_statistical_quality(phase3_summary, diag, calib)
    assert out["n_eff_total_ht"] == pytest.approx(31.5)
    assert out["n_districts_extreme_calibration_factor_low"] == 1
    assert out["n_districts_extreme_calibration_factor_high"] == 1


def test_summarize_population_quality_handles_no_impossible_districts():
    calib = pd.DataFrame({"calibration_status": ["calibrated"], "known_population": [100.0]})
    out = summarize_population_quality({"u2_total_population": 100.0, "u4_total_population": 100.0}, calib)
    assert out["n_districts_calibration_impossible"] == 0
