"""Tests de src/metrics.py — Fase 3. Todo sintético, no requiere descargar
la fuente completa de INEI."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import metrics as m


# --------------------------------------------------------------------------
# Población: 1:1 / unmatched / ambiguous
# --------------------------------------------------------------------------


def _demand(ids, keys, dep=None, design_weight=None):
    return pd.DataFrame({
        "demand_id": ids,
        "CPINEI": keys,
        "DEP": dep if dep is not None else ["CUSCO"] * len(ids),
        "design_weight": design_weight if design_weight is not None else [2.0] * len(ids),
    })


def test_population_match_1to1():
    demand_df = _demand(["d1", "d2"], ["k1", "k2"])
    pop_df = pd.DataFrame({"CODIGO": ["k1", "k2"], "pop": [100, 200]})
    out = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop")
    assert set(out["population_match_status"]) == {m.MATCHED}
    assert out.set_index("demand_id").loc["d1", "population"] == 100
    assert out.set_index("demand_id").loc["d2", "population"] == 200


def test_population_match_unmatched_including_missing_key():
    demand_df = _demand(["d1", "d2"], ["k1", None])
    pop_df = pd.DataFrame({"CODIGO": ["kX"], "pop": [50]})
    out = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop")
    assert set(out["population_match_status"]) == {m.UNMATCHED}
    assert out["population"].isna().all()


def test_population_match_ambiguous_not_silently_resolved():
    demand_df = _demand(["d1"], ["k1"])
    pop_df = pd.DataFrame({"CODIGO": ["k1", "k1"], "pop": [100, 300]})
    out = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop")
    row = out.iloc[0]
    assert row["population_match_status"] == m.AMBIGUOUS
    assert pd.isna(row["population"])  # nunca promedia ni toma el primero como población final
    assert row["n_population_records_for_key"] == 2


def test_demand_ids_preserved_as_strings_with_leading_zeros():
    demand_df = _demand(["0000113033"], ["0808070024"])
    pop_df = pd.DataFrame({"CODIGO": ["0808070024"], "pop": [10]})
    out = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop")
    assert out["demand_id"].iloc[0] == "0000113033"
    assert isinstance(out["demand_id"].iloc[0], str)


# --------------------------------------------------------------------------
# analysis_weight
# --------------------------------------------------------------------------


def test_analysis_weight_is_population_times_design_weight_only_when_matched():
    demand_df = _demand(["d1", "d2"], ["k1", "k2"], design_weight=[2.0, 5.0])
    pop_df = pd.DataFrame({"CODIGO": ["k1"], "pop": [100]})  # k2 unmatched
    match = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop")
    out = m.build_analysis_weights(match, demand_df)
    row1 = out.set_index("demand_id").loc["d1"]
    row2 = out.set_index("demand_id").loc["d2"]
    assert row1["analysis_weight"] == pytest.approx(200.0)
    assert pd.isna(row2["analysis_weight"])  # nunca se imputa


def test_design_weight_never_confused_with_population_weight():
    # Un demand_id con population NaN (unmatched) pero design_weight grande
    # NO debe producir un analysis_weight numérico "por accidente".
    demand_df = _demand(["d1"], [None], design_weight=[100.0])
    pop_df = pd.DataFrame({"CODIGO": [], "pop": []})
    match = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop")
    out = m.build_analysis_weights(match, demand_df)
    assert pd.isna(out["analysis_weight"].iloc[0])


def test_verify_design_weights_detects_inconsistency():
    df = pd.DataFrame({"inclusion_prob": [0.5, 0.25], "design_weight": [2.0, 5.0]})
    res = m.verify_design_weights(df)
    assert res["all_consistent_within_rtol"] is False
    df_ok = pd.DataFrame({"inclusion_prob": [0.5, 0.25], "design_weight": [2.0, 4.0]})
    res_ok = m.verify_design_weights(df_ok)
    assert res_ok["all_consistent_within_rtol"] is True


# --------------------------------------------------------------------------
# access time / coverage bands (bordes exactos 30/60/120)
# --------------------------------------------------------------------------


def _demand_analysis(times, routing_status=None, weights=None):
    n = len(times)
    routing_status = routing_status or [m.ROUTED] * n
    weights = weights if weights is not None else [1.0] * n
    return pd.DataFrame({
        "demand_id": [f"d{i}" for i in range(n)],
        "t_min": times,
        "routing_status_car": routing_status,
        "analysis_weight": weights,
    })


def test_compute_access_time_never_imputes_for_non_routed():
    df = pd.DataFrame({
        "routing_status_car": ["routed", "snap_failed", "no_route_same_department"],
        "travel_time_min_car": [42.0, 999.0, 999.0],
    })
    t = m.compute_access_time(df)
    assert t.iloc[0] == 42.0
    assert pd.isna(t.iloc[1])
    assert pd.isna(t.iloc[2])


def test_coverage_band_boundaries_exact():
    df = _demand_analysis([30.0, 30.0001, 60.0, 60.0001, 120.0, 120.0001])
    bands = m.compute_coverage_bands(df)["reading_a_sobre_poblacion_con_tiempo_estimable"].set_index("band")
    assert bands.loc[m.BAND_LE30, "poblacion_ponderada"] == 1.0
    assert bands.loc[m.BAND_30_60, "poblacion_ponderada"] == 2.0
    assert bands.loc[m.BAND_60_120, "poblacion_ponderada"] == 2.0
    assert bands.loc[m.BAND_GT120, "poblacion_ponderada"] == 1.0


def test_unroutable_not_classified_as_gt120():
    df = _demand_analysis([np.nan, 200.0], routing_status=["snap_failed", "routed"])
    result = m.compute_coverage_bands(df)
    reading_b = result["reading_b_sobre_poblacion_total"].set_index("band")
    assert reading_b.loc[m.BAND_UNROUTABLE, "poblacion_ponderada"] == 1.0
    assert reading_b.loc[m.BAND_GT120, "poblacion_ponderada"] == 1.0  # no se fusionan


def test_reading_a_sums_to_100_pct():
    df = _demand_analysis([10.0, 45.0, 90.0, 200.0])
    reading_a = m.compute_coverage_bands(df)["reading_a_sobre_poblacion_con_tiempo_estimable"]
    assert reading_a["pct"].sum() == pytest.approx(100.0)


def test_coverage_bands_are_weighted_not_counted():
    # Un CP de peso 100 con tiempo 10 min debe dominar sobre 3 CP de peso 1 con 200 min.
    df = _demand_analysis([10.0, 200.0, 200.0, 200.0], weights=[100.0, 1.0, 1.0, 1.0])
    reading_a = m.compute_coverage_bands(df)["reading_a_sobre_poblacion_con_tiempo_estimable"].set_index("band")
    assert reading_a.loc[m.BAND_LE30, "pct"] == pytest.approx(100.0 * 100 / 103)


# --------------------------------------------------------------------------
# weighted mean + aggregation por distrito/provincia/departamento
# --------------------------------------------------------------------------


def test_weighted_mean_access_basic():
    df = _demand_analysis([10.0, 30.0], weights=[1.0, 3.0])
    out = m.weighted_mean_access(df, group_cols=None, population_col="analysis_weight")
    expected = (10 * 1 + 30 * 3) / 4
    assert out["weighted_mean_access_min"].iloc[0] == pytest.approx(expected)


def test_weighted_mean_access_excludes_non_routed_from_mean_but_counts_population():
    df = _demand_analysis([10.0, np.nan], routing_status=["routed", "snap_failed"], weights=[1.0, 5.0])
    out = m.weighted_mean_access(df, group_cols=None, population_col="analysis_weight")
    assert out["weighted_mean_access_min"].iloc[0] == pytest.approx(10.0)
    assert out["total_estimated_population"].iloc[0] == pytest.approx(6.0)
    assert out["population_with_travel_time"].iloc[0] == pytest.approx(1.0)


def test_weighted_mean_access_group_by_district_province_department():
    df = _demand_analysis([10.0, 50.0, 90.0, 130.0])
    df["dist"] = ["A", "A", "B", "B"]
    df["prov"] = ["P1", "P1", "P1", "P1"]
    df["dep"] = ["D1", "D1", "D1", "D1"]
    by_dist = m.weighted_mean_access(df, group_cols=["dep", "prov", "dist"], population_col="analysis_weight")
    assert set(by_dist["dist"]) == {"A", "B"}
    a_mean = by_dist.set_index("dist").loc["A", "weighted_mean_access_min"]
    assert a_mean == pytest.approx(30.0)


# --------------------------------------------------------------------------
# rank_critical_gaps + low coverage warning
# --------------------------------------------------------------------------


def test_weighted_mean_access_zero_coverage_district_is_0pct_not_nan_when_population_exists():
    # Un distrito con poblacion matched pero CERO CP con tiempo ruteado debe
    # reportar 0% (dato real: no hay cobertura), no NaN (que significaría
    # "no hay dato de poblacion" -- una situacion distinta).
    df = _demand_analysis([np.nan, np.nan], routing_status=["snap_failed", "no_route_same_department"], weights=[10.0, 20.0])
    out = m.weighted_mean_access(df, group_cols=None, population_col="analysis_weight")
    assert out["total_estimated_population"].iloc[0] == pytest.approx(30.0)
    assert out["population_with_travel_time"].iloc[0] == 0.0
    assert out["share_population_with_travel_time_pct"].iloc[0] == 0.0
    assert pd.isna(out["weighted_mean_access_min"].iloc[0])  # no se puede promediar sobre 0 observaciones


def test_rank_critical_gaps_treats_nan_share_as_low_coverage_warning():
    by_district = pd.DataFrame({
        "dist": ["ZeroRouting", "Good"],
        "weighted_mean_access_min": [np.nan, 20.0],
        "share_population_with_travel_time_pct": [np.nan, 90.0],
    })
    out = m.rank_critical_gaps(by_district, district_cols=["dist"])
    zero_routing = out.set_index("dist").loc["ZeroRouting"]
    assert zero_routing["low_routing_coverage_warning"] == True  # noqa: E712


def test_rank_critical_gaps_orders_worst_first_and_flags_low_coverage():
    by_district = pd.DataFrame({
        "dist": ["Good", "Bad", "SmallSampleGoodLooking"],
        "weighted_mean_access_min": [20.0, 100.0, 15.0],
        "share_population_with_travel_time_pct": [90.0, 80.0, 10.0],
    })
    out = m.rank_critical_gaps(by_district, district_cols=["dist"], low_routing_coverage_threshold_pct=50.0)
    assert out.iloc[0]["dist"] == "Bad"
    small = out.set_index("dist").loc["SmallSampleGoodLooking"]
    assert small["low_routing_coverage_warning"] == True  # noqa: E712
    good = out.set_index("dist").loc["Good"]
    assert good["low_routing_coverage_warning"] == False  # noqa: E712
    # No se excluye ningún distrito por baja cobertura:
    assert len(out) == 3


# --------------------------------------------------------------------------
# Gini + Lorenz
# --------------------------------------------------------------------------


def test_weighted_gini_zero_when_all_times_equal():
    res = m.weighted_gini(values=[30.0, 30.0, 30.0], weights=[1.0, 2.0, 3.0])
    assert res["gini"] == pytest.approx(0.0, abs=1e-9)


def test_weighted_gini_known_case_two_groups():
    # Población total 100: 90 con t=10, 10 con t=100 -> desigualdad conocida.
    res = m.weighted_gini(values=[10.0, 100.0], weights=[90.0, 10.0])
    assert 0.0 < res["gini"] < 1.0
    # Gini debe crecer si concentramos aún más el tiempo alto en menos gente.
    res2 = m.weighted_gini(values=[10.0, 1000.0], weights=[90.0, 10.0])
    assert res2["gini"] > res["gini"]


def test_weighted_gini_excludes_non_estimated_and_reports_pct_excluded():
    res = m.weighted_gini(values=[10.0, np.nan], weights=[50.0, 50.0])
    assert res["n_included"] == 1
    assert res["pct_population_excluded"] == pytest.approx(50.0)


def test_lorenz_curve_monotonic_and_bounded():
    curve = m.build_lorenz_curve(values=[10.0, 20.0, 5.0], weights=[1.0, 1.0, 1.0])
    assert curve["cum_pop_share"].iloc[0] == 0.0
    assert curve["cum_pop_share"].iloc[-1] == pytest.approx(1.0)
    assert curve["cum_time_share"].is_monotonic_increasing


# --------------------------------------------------------------------------
# urban/rural
# --------------------------------------------------------------------------


def test_urban_rural_summary_basic():
    df = _demand_analysis([10.0, 200.0, 40.0, 40.0])
    df["urban_rural"] = ["urban", "rural", "urban", "unknown"]
    out = m.urban_rural_summary(df)
    urban_row = out.set_index("urban_rural").loc["urban"]
    assert urban_row["n_cp"] == 2
    assert urban_row["weighted_mean_access_min"] == pytest.approx(25.0)


def test_rurality_cross_analysis_never_claims_causality():
    df = _demand_analysis([10.0, 200.0])
    df["urban_rural"] = ["urban", "rural"]
    res = m.rurality_access_cross_analysis(df)
    assert res["causal_claim_made"] is False
    assert "correlacional" in res["interpretation"].lower() or "correlational" in res["interpretation"].lower()
    assert "no" in res["interpretation"].lower()


# --------------------------------------------------------------------------
# ausencia de población / routing completeness
# --------------------------------------------------------------------------


def test_routing_completeness_summary_all_unmatched_population_is_honest_not_hidden():
    df = pd.DataFrame({
        "routing_status_car": ["routed", "snap_failed", "no_route_same_department"],
        "analysis_weight": [np.nan, np.nan, np.nan],
    })
    out = m.routing_completeness_summary(df)
    assert set(out["estado"]) == {"routed", "snap_failed", "no_route_same_department"}
    assert out["poblacion_ponderada"].isna().all() or (out["poblacion_ponderada"] == 0).all()


def test_extreme_cases_does_not_drop_outliers():
    df = _demand_analysis([10.0, 500.0, 20.0])
    top = m.top_extreme_access_cases(df, n=2)
    assert list(top["t_min"]) == [500.0, 20.0]


def test_foot_over_car_extreme_ratio_filters_correctly():
    df = pd.DataFrame({"demand_id": ["a", "b", "c"], "foot_over_car_ratio": [5.0, 150.0, 300.0]})
    out = m.foot_over_car_extreme_ratio(df, threshold=100.0)
    assert set(out["demand_id"]) == {"b", "c"}


def test_cross_validate_population_sources_agreement():
    a = pd.DataFrame({"codccpp": ["k1", "k2"], "pob_total": [100, 200]})
    b = pd.DataFrame({"idccpp_17": ["k1", "k2"], "pob17": [100, 200]})
    res = m.cross_validate_population_sources(a, b, key_a="codccpp", key_b="idccpp_17", value_a="pob_total", value_b="pob17")
    assert res["n_comparable"] == 2
    assert res["n_identical"] == 2
    assert res["pct_identical"] == pytest.approx(100.0)
    assert res["n_discrepant"] == 0


def test_cross_validate_population_sources_detects_discrepancy():
    a = pd.DataFrame({"codccpp": ["k1", "k2"], "pob_total": [100, 200]})
    b = pd.DataFrame({"idccpp_17": ["k1", "k2"], "pob17": [100, 999]})
    res = m.cross_validate_population_sources(a, b, key_a="codccpp", key_b="idccpp_17", value_a="pob_total", value_b="pob17")
    assert res["n_identical"] == 1
    assert res["n_discrepant"] == 1
    assert res["discrepant_examples"]["diff_abs"].iloc[0] == pytest.approx(799.0)


def test_population_control_by_department_reports_gap_not_silent():
    match_report = pd.DataFrame({
        "demand_id": ["d1", "d2", "d3"],
        "population": [100.0, 200.0, np.nan],
        "population_match_status": [m.MATCHED, m.MATCHED, m.UNMATCHED],
    })
    demand_df = pd.DataFrame({"demand_id": ["d1", "d2", "d3"], "DEP": ["CUSCO", "CUSCO", "TUMBES"]})
    benchmark = pd.DataFrame({"dep": ["CUSCO", "TUMBES"], "poblacion_censo2017_real": [1000.0, 500.0]})
    out = m.population_control_by_department(match_report, demand_df, benchmark)
    cusco = out.set_index("DEP").loc["CUSCO"]
    assert cusco["poblacion_matched_observada"] == pytest.approx(300.0)
    assert cusco["pct_del_benchmark_capturado"] == pytest.approx(30.0)


def test_population_match_report_flags_secondary_key_disagreement_without_resolving():
    demand_df = pd.DataFrame({"demand_id": ["d1"], "CPINEI": ["k1"], "CPINEI2": ["k2"]})
    pop_df = pd.DataFrame({"CODIGO": ["k1", "k2"], "pop": [100, 300]})
    out = m.build_population_match_report(
        demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop",
        demand_id_col="demand_id", demand_secondary_key_col="CPINEI2",
    )
    row = out.iloc[0]
    assert row["population"] == 100  # se usa la clave primaria (CPINEI), no se resuelve mezclando
    assert row["secondary_key_disagrees_with_primary"] == True  # noqa: E712 -- expuesto para auditoria manual


def test_duplicated_cpinei_does_not_double_count_population():
    demand_df = pd.DataFrame({
        "demand_id": ["a", "b", "c"], "CPINEI": ["k1", "k1", "k2"], "DEP": ["X", "X", "X"],
    })
    pop_df = pd.DataFrame({"CODIGO": ["k1", "k2"], "pop": [100, 200]})
    rep = m.flag_population_representative(demand_df, demand_key_col="CPINEI", demand_id_col="demand_id", representative_override={"k1": "a"})
    out = m.build_population_match_report(demand_df, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop", demand_id_col="demand_id", population_representative=rep)
    out_idx = out.set_index("demand_id")
    assert out_idx.loc["a", "population"] == 100
    assert out_idx.loc["a", "population_match_status"] == m.MATCHED
    assert pd.isna(out_idx.loc["b", "population"])
    assert out_idx.loc["b", "population_match_status"] == m.DUPLICATE_KEY_EXCLUDED
    # nunca se cuenta dos veces si alguien suma population sobre todas las filas:
    assert out["population"].sum() == 300  # 100 (a) + 200 (c), NUNCA 100+100+200


def test_flag_population_representative_no_override_excludes_all_of_duplicate_group():
    demand_df = pd.DataFrame({"demand_id": ["a", "b"], "CPINEI": ["k1", "k1"]})
    rep = m.flag_population_representative(demand_df, demand_key_col="CPINEI", demand_id_col="demand_id", representative_override={})
    assert not rep.any()  # sin override explicito, NINGUNA fila del grupo duplicado es representante (no se divide 50/50)


def test_flag_population_representative_unique_keys_always_true():
    demand_df = pd.DataFrame({"demand_id": ["a", "b"], "CPINEI": ["k1", "k2"]})
    rep = m.flag_population_representative(demand_df, demand_key_col="CPINEI", demand_id_col="demand_id", representative_override={})
    assert rep.all()


# --------------------------------------------------------------------------
# Calibración de pesos por distrito
# --------------------------------------------------------------------------


def test_calibration_factor_exact_known_example():
    # 2 CP en el distrito D con HT_total=100+50=150; poblacion censal real conocida=300 -> factor=2.0
    df = pd.DataFrame({"DIST": ["D", "D"], "ht_population_weight": [100.0, 50.0]})
    known = pd.DataFrame({"DIST": ["D"], "known_population": [300.0]})
    result = m.calibrate_weights_by_district(df, known, group_cols=["DIST"])
    dist = result["district_level"].set_index("DIST").loc["D"]
    assert dist["calibration_factor"] == pytest.approx(2.0)
    assert dist["calibration_status"] == m.CALIBRATED
    row = result["row_level"]
    assert row["calibrated_weight"].tolist() == pytest.approx([200.0, 100.0])


def test_calibrated_weights_reproduce_known_population_by_district():
    df = pd.DataFrame({"DIST": ["A", "A", "B"], "ht_population_weight": [10.0, 30.0, 5.0]})
    known = pd.DataFrame({"DIST": ["A", "B"], "known_population": [1000.0, 250.0]})
    result = m.calibrate_weights_by_district(df, known, group_cols=["DIST"])
    row = result["row_level"]
    sums = row.groupby("DIST")["calibrated_weight"].sum()
    assert sums["A"] == pytest.approx(1000.0)
    assert sums["B"] == pytest.approx(250.0)


def test_calibration_impossible_when_no_sample():
    df = pd.DataFrame({"DIST": ["A"], "ht_population_weight": [10.0]})
    known = pd.DataFrame({"DIST": ["A", "B"], "known_population": [1000.0, 500.0]})  # B sin ninguna fila en df
    result = m.calibrate_weights_by_district(df, known, group_cols=["DIST"])
    dist_b = result["district_level"].set_index("DIST").loc["B"]
    assert dist_b["calibration_status"] == m.CALIBRATION_IMPOSSIBLE
    assert pd.isna(dist_b["calibration_factor"])


def test_effective_sample_size_all_equal_weights_equals_n():
    assert m.effective_sample_size([10.0, 10.0, 10.0, 10.0]) == pytest.approx(4.0)


def test_effective_sample_size_concentrated_weight_less_than_n():
    # Un peso domina totalmente -> n_eff cercano a 1, mucho menor que n=3.
    ess = m.effective_sample_size([1000.0, 1.0, 1.0])
    assert ess < 1.1


# --------------------------------------------------------------------------
# Estados de calidad por distrito / split de ranking
# --------------------------------------------------------------------------


def test_classify_district_data_quality_all_six_paths():
    df = pd.DataFrame({
        "calibration_status": [m.CALIBRATION_IMPOSSIBLE, m.CALIBRATED, m.CALIBRATED, m.CALIBRATED, m.CALIBRATED, m.CALIBRATED],
        "n_cp_with_weight": [0, 0, 2, 10, 10, 10],
        "n_cp_with_time": [0, 0, 0, 0, 3, 10],
        "share_population_with_travel_time_pct": [np.nan, np.nan, np.nan, np.nan, 20.0, 90.0],
    })
    status = m.classify_district_data_quality(df, low_routing_coverage_threshold_pct=50.0, min_cp_with_weight_for_low_population_flag=3)
    assert list(status) == [
        m.DISTRICT_CALIBRATION_IMPOSSIBLE,        # calibration_status impossible pesa mas que cualquier otra condicion
        m.DISTRICT_ZERO_POPULATION_SAMPLE_COVERAGE,  # calibrado pero 0 CP con peso en la muestra
        m.DISTRICT_LOW_POPULATION_SAMPLE_COVERAGE,
        m.DISTRICT_ZERO_ROUTING_COVERAGE,
        m.DISTRICT_LOW_ROUTING_COVERAGE,
        m.DISTRICT_COMPUTABLE,
    ]


def test_split_critical_gaps_excludes_noncomputable_from_worst_list():
    df = pd.DataFrame({
        "dist": ["Bad", "Good", "NoData"],
        "weighted_mean_access_min": [200.0, 20.0, np.nan],
        "district_status": [m.DISTRICT_COMPUTABLE, m.DISTRICT_COMPUTABLE, m.DISTRICT_ZERO_ROUTING_COVERAGE],
    })
    split = m.split_critical_gaps(df)
    worst = split["worst_computable_districts"]
    insufficient = split["districts_with_insufficient_data"]
    assert "NoData" not in worst["dist"].tolist()
    assert worst["dist"].tolist() == ["Bad", "Good"]  # ordenado DESC, solo computables
    assert insufficient["dist"].tolist() == ["NoData"]


def test_outside_frame_population_never_redistributed():
    # U2 (12332) - U4 (12220) = 112 CP fuera del frame SIGMED; su poblacion
    # nunca debe aparecer sumada dentro de ningun distrito de known_population.
    sigmed_like = pd.DataFrame({"demand_id": ["a", "b"], "CPINEI": ["k1", "k2"], "DEP": ["X", "X"], "PROV": ["P", "P"], "DIST": ["D", "D"]})
    pop_df = pd.DataFrame({"CODIGO": ["k1", "k2", "k_outside_frame"], "pop": [100, 200, 999]})
    match = m.build_population_match_report(sigmed_like, pop_df, demand_key_col="CPINEI", population_key_col="CODIGO", population_value_col="pop", demand_id_col="demand_id")
    assert match["population"].sum() == 300  # los 999 de k_outside_frame (fuera del frame) NUNCA entran


def test_ht_and_calibrated_metrics_both_generated_and_differ_when_calibration_applied():
    df = pd.DataFrame({
        "DIST": ["A", "A"], "t_min": [10.0, 30.0],
        "ht_population_weight": [1.0, 1.0],
    })
    known = pd.DataFrame({"DIST": ["A"], "known_population": [1000.0]})
    calib = m.calibrate_weights_by_district(df, known, group_cols=["DIST"])
    row = calib["row_level"]
    ht_mean = m.weighted_mean_access(row, None, weight_col="ht_population_weight", population_col="ht_population_weight")["weighted_mean_access_min"].iloc[0]
    cal_mean = m.weighted_mean_access(row, None, weight_col="calibrated_weight", population_col="calibrated_weight")["weighted_mean_access_min"].iloc[0]
    assert ht_mean == pytest.approx(cal_mean)  # aqui el factor es igual para ambas filas -> misma media ponderada
    assert row["calibrated_weight"].sum() == pytest.approx(1000.0)
    assert row["ht_population_weight"].sum() == pytest.approx(2.0)  # confirma que SI son escalas distintas


def test_gini_uses_the_weight_column_passed_in():
    # Mismos tiempos, pesos HT vs calibrados MUY distintos -> Gini debe diferir.
    values = [10.0, 100.0]
    gini_ht = m.weighted_gini(values, weights=[50.0, 50.0])
    gini_cal = m.weighted_gini(values, weights=[95.0, 5.0])
    assert gini_ht["gini"] != pytest.approx(gini_cal["gini"])


def test_urban_rural_summary_uses_the_weight_column_passed_in():
    df = pd.DataFrame({"t_min": [10.0, 100.0], "urban_rural": ["urban", "urban"], "ht_w": [1.0, 1.0], "cal_w": [10.0, 1.0]})
    ht = m.urban_rural_summary(df, weight_col="ht_w")
    cal = m.urban_rural_summary(df, weight_col="cal_w")
    ht_mean = ht.set_index("urban_rural").loc["urban", "weighted_mean_access_min"]
    cal_mean = cal.set_index("urban_rural").loc["urban", "weighted_mean_access_min"]
    assert ht_mean == pytest.approx(55.0)
    assert cal_mean == pytest.approx((10 * 10 + 100 * 1) / 11)
    assert ht_mean != pytest.approx(cal_mean)


def test_coverage_reading_b_sums_to_100_pct_total():
    df = _demand_analysis([10.0, np.nan, 200.0], routing_status=["routed", "snap_failed", "routed"])
    reading_b = m.compute_coverage_bands(df)["reading_b_sobre_poblacion_total"]
    assert reading_b["pct"].sum() == pytest.approx(100.0)


def test_coverage_reading_a_sums_to_100_pct_routed_only():
    df = _demand_analysis([10.0, 50.0, 200.0])
    reading_a = m.compute_coverage_bands(df)["reading_a_sobre_poblacion_con_tiempo_estimable"]
    assert reading_a["pct"].sum() == pytest.approx(100.0)


def test_track_impact_table_reuses_given_counts_no_recompute():
    out = m.track_impact_table(routed_before=3313, routed_after=3721, points_recovered=408, universe_n=5000)
    assert out["absolute_increase"].iloc[0] == 408
    assert out["pct_increase"].iloc[0] == pytest.approx(100.0 * 408 / 3313)
