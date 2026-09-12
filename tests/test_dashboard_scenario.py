"""Tests de src/dashboard/scenario.py — simulador de upgrade. Todo sintético,
sin Streamlit, sin routing nuevo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.dashboard.scenario import baseline_vs_scenario_summary, compute_scenario_time, rank_candidates, summarize_population_by_bands


def _baseline():
    return pd.Series([50.0, np.nan, 200.0, 10.0], index=["d1", "d2", "d3", "d4"])


def _upgrade():
    return pd.DataFrame({
        "demand_id": ["d1", "d2", "d3", "d1", "d4"],
        "facility_id": ["c1", "c1", "c1", "c2", "c1"],
        "travel_time_min": [10.0, 20.0, np.nan, 5.0, 100.0],  # d3 sin ruta valida a c1
    })


def test_scenario_no_selection_equals_baseline():
    out = compute_scenario_time(_baseline(), _upgrade(), [])
    pd.testing.assert_series_equal(out.sort_index(), _baseline().sort_index(), check_names=False)


def test_scenario_no_selection_none_equals_baseline():
    out = compute_scenario_time(_baseline(), _upgrade(), None)
    pd.testing.assert_series_equal(out.sort_index(), _baseline().sort_index(), check_names=False)


def test_scenario_single_upgrade_improves_reachable_points_only():
    out = compute_scenario_time(_baseline(), _upgrade(), ["c1"])
    assert out["d1"] == 10.0  # mejora: min(50, 10)
    assert out["d2"] == 20.0  # antes sin ruta, ahora 20
    assert out["d3"] == 200.0  # candidato sin ruta valida a d3 -> NO mejora, NO se imputa
    assert out["d4"] == 10.0  # 100 > 10, no mejora (min correcto)


def test_scenario_unreachable_candidate_never_improves_point():
    # c1 no tiene fila para d3 -> ese punto no debe cambiar.
    out = compute_scenario_time(_baseline(), _upgrade(), ["c1"])
    assert out["d3"] == _baseline()["d3"]


def test_scenario_multiple_upgrades_takes_minimum_not_sum():
    out = compute_scenario_time(_baseline(), _upgrade(), ["c1", "c2"])
    assert out["d1"] == 5.0  # min(50, 10, 5) -- NUNCA 10+5 ni 50-10-5


def test_scenario_reset_is_equivalent_to_empty_selection():
    with_selection = compute_scenario_time(_baseline(), _upgrade(), ["c1"])
    reset = compute_scenario_time(_baseline(), _upgrade(), [])
    assert not with_selection.equals(reset)
    assert reset.equals(_baseline())


def test_summarize_population_by_bands_reading_b_sums_to_total():
    t = [10.0, 40.0, 90.0, np.nan]
    w = [10.0, 20.0, 30.0, 40.0]
    s = summarize_population_by_bands(t, w)
    total_bands = s["pop_le_30"] + (s["pop_le_60_cum"] - s["pop_le_30"]) + (s["pop_le_120_cum"] - s["pop_le_60_cum"]) + s["pop_gt_120"] + s["pop_no_time_estimate"]
    assert total_bands == pytest.approx(s["total_population"])
    assert s["total_population"] == pytest.approx(100.0)


def test_baseline_vs_scenario_no_selection_zero_marginal_gain():
    da = pd.DataFrame({"demand_id": ["d1", "d2", "d3", "d4"], "t_min": _baseline().values, "calibrated_weight": [1.0, 2.0, 3.0, 4.0]})
    res = baseline_vs_scenario_summary(da, _upgrade(), [])
    assert res["marginal_gain"]["pop_gain_le_30"] == pytest.approx(0.0)
    assert res["marginal_gain"]["pop_gain_le_60"] == pytest.approx(0.0)
    assert res["marginal_gain"]["population_newly_routed"] == pytest.approx(0.0)
    assert res["n_selected"] == 0


def test_baseline_vs_scenario_population_never_double_counted_with_overlapping_candidates():
    # d1 es alcanzable por c1 (10) Y c2 (5) -- seleccionar ambos NO debe sumar
    # ganancia dos veces, el resultado usa el minimo.
    da = pd.DataFrame({"demand_id": ["d1"], "t_min": [50.0], "calibrated_weight": [100.0]})
    upgrade = pd.DataFrame({"demand_id": ["d1", "d1"], "facility_id": ["c1", "c2"], "travel_time_min": [10.0, 5.0]})
    res_single = baseline_vs_scenario_summary(da, upgrade, ["c1"])
    res_both = baseline_vs_scenario_summary(da, upgrade, ["c1", "c2"])
    assert res_both["scenario"]["weighted_mean"] == pytest.approx(5.0)
    assert res_both["scenario"]["weighted_mean"] <= res_single["scenario"]["weighted_mean"]


def test_baseline_vs_scenario_population_newly_routed():
    da = pd.DataFrame({"demand_id": ["d1", "d2"], "t_min": [np.nan, 200.0], "calibrated_weight": [10.0, 20.0]})
    upgrade = pd.DataFrame({"demand_id": ["d1"], "facility_id": ["c1"], "travel_time_min": [15.0]})
    res = baseline_vs_scenario_summary(da, upgrade, ["c1"])
    assert res["marginal_gain"]["population_newly_routed"] == pytest.approx(10.0)


def test_baseline_vs_scenario_outside_frame_population_not_redistributed():
    # calibrated_weight ya excluye la poblacion fuera de frame (NaN) -- el
    # simulador no debe inventarle un peso.
    da = pd.DataFrame({"demand_id": ["d1", "d2"], "t_min": [50.0, np.nan], "calibrated_weight": [100.0, np.nan]})
    upgrade = pd.DataFrame({"demand_id": ["d2"], "facility_id": ["c1"], "travel_time_min": [5.0]})
    res = baseline_vs_scenario_summary(da, upgrade, ["c1"])
    assert res["baseline"]["total_population"] == pytest.approx(100.0)
    assert res["scenario"]["total_population"] == pytest.approx(100.0)  # d2 sigue sin peso -> no aporta poblacion nueva


def test_scenario_candidate_id_not_in_matrix_is_a_noop_not_an_error():
    out = compute_scenario_time(_baseline(), _upgrade(), ["candidato_inexistente"])
    assert out.equals(_baseline())


def test_rank_candidates_orders_by_chosen_metric_and_adds_rank():
    scores = pd.DataFrame({"facility_id": ["a", "b", "c"], "pop_gain_le_60": [10.0, 100.0, 50.0]})
    ranked = rank_candidates(scores, by="pop_gain_le_60")
    assert ranked["facility_id"].tolist() == ["b", "c", "a"]
    assert ranked["rank"].tolist() == [1, 2, 3]


def test_scenario_weighted_coverage_sums_to_total_population_baseline_and_scenario():
    da = pd.DataFrame({"demand_id": ["d1", "d2", "d3", "d4"], "t_min": _baseline().values, "calibrated_weight": [10.0, 20.0, 30.0, 40.0]})
    res = baseline_vs_scenario_summary(da, _upgrade(), ["c1", "c2"])
    for scope in ("baseline", "scenario"):
        s = res[scope]
        bands_sum = s["pop_le_30"] + (s["pop_le_60_cum"] - s["pop_le_30"]) + (s["pop_le_120_cum"] - s["pop_le_60_cum"]) + s["pop_gt_120"] + s["pop_no_time_estimate"]
        assert bands_sum == pytest.approx(s["total_population"])
        assert s["total_population"] == pytest.approx(100.0)


def test_simulator_baseline_reproducible_from_demand_analysis_directly():
    # El baseline del simulador (con selección vacía) debe coincidir
    # exactamente con calcular la media ponderada directo sobre demand_analysis.
    from src import metrics as _m

    da = pd.DataFrame({"demand_id": ["d1", "d2"], "t_min": [10.0, 30.0], "calibrated_weight": [1.0, 3.0]})
    direct = _m.weighted_mean_access(da, None, weight_col="calibrated_weight", population_col="calibrated_weight")["weighted_mean_access_min"].iloc[0]
    upgrade = pd.DataFrame({"demand_id": [], "facility_id": [], "travel_time_min": []})
    res = baseline_vs_scenario_summary(da, upgrade, [])
    assert res["baseline"]["weighted_mean"] == pytest.approx(direct)
    assert res["scenario"]["weighted_mean"] == pytest.approx(direct)


def test_rank_candidates_top_n():
    scores = pd.DataFrame({"facility_id": ["a", "b", "c"], "pop_gain_le_60": [10.0, 100.0, 50.0]})
    ranked = rank_candidates(scores, by="pop_gain_le_60", top_n=2)
    assert len(ranked) == 2
