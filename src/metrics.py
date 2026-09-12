"""metrics — Fase 3.

Funciones puras (reciben DataFrame(s), devuelven DataFrame(s)/estructuras
explícitas). **Ninguna función de este módulo lee ni escribe archivos, ni
importa Streamlit** — la orquestación (leer parquet/csv, cruzar fuentes
concretas, escribir outputs) vive en `src/analysis.py` /
`scripts/calculate_metrics.py`.

Principio rector (ver `docs/03_population_source_inspection.md`): NO se
confunde centro poblado con población, NO se usa `design_weight` como si
fuera población, NO se imputa población ni tiempo de viaje silenciosamente.
`analysis_weight_i = population_i * design_weight_i`, calculado únicamente
donde el cruce de población es válido (`population_match_status == "matched"`).

Actualizado 2026-09-11 (corrección estadística final): la fuente de
población real es CENEPRED/SIGRID (Censo 2017 INEI), cruzada por `CPINEI`
(ver `docs/03_population_source_inspection.md`). Este módulo añade además:
(a) manejo explícito de `CPINEI` duplicados del lado SIGMED (2 casos reales
en el universo de 19 370 — `flag_population_representative`,
`DUPLICATE_KEY_EXCLUDED`) para que un mismo CP censal nunca aporte su
población dos veces; (b) calibración de pesos por distrito
(`calibrate_weights_by_district`) contra la población censal real conocida
del frame SIGMED×CENEPRED (U4), preservando el resultado Horvitz-Thompson
sin calibrar para transparencia; (c) `effective_sample_size` como
diagnóstico de concentración de pesos. `design_weight` (diseño muestral),
`population` (Censo 2017), `analysis_weight`/`ht_population_weight`
(= population × design_weight, sin calibrar) y `calibrated_weight`
(= ht_population_weight × calibration_factor_distrito) son CINCO variables
distintas, nunca intercambiadas entre sí.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

MATCHED = "matched"
UNMATCHED = "unmatched"
AMBIGUOUS = "ambiguous"
#: Fila de demanda que comparte su clave (p.ej. CPINEI) con otra(s) fila(s)
#: de demanda, y NO fue elegida como representante de ese CP censal (ver
#: `flag_population_representative`) — evita que un mismo CP censal aporte
#: su población más de una vez si ambas filas cayeran en el mismo análisis.
DUPLICATE_KEY_EXCLUDED = "duplicate_key_excluded_non_representative"
POPULATION_MATCH_STATUSES = (MATCHED, UNMATCHED, AMBIGUOUS, DUPLICATE_KEY_EXCLUDED)

BAND_LE30 = "<=30"
BAND_30_60 = ">30_<=60"
BAND_60_120 = ">60_<=120"
BAND_GT120 = ">120"
BAND_UNROUTABLE = "unroutable_or_not_estimated"
COVERAGE_BANDS = (BAND_LE30, BAND_30_60, BAND_60_120, BAND_GT120)

ROUTED = "routed"  # debe coincidir con src.routing.status.ROUTED

URBAN = "urban"
RURAL = "rural"
UNKNOWN_RURALITY = "unknown"

CAUSAL_DISCLAIMER = (
    "Esta es una asociación descriptiva/correlacional entre condición "
    "urbano/rural y tiempo de acceso — NO una relación causal. No se "
    "controla por confusores (altitud, densidad vial, orografía, etc.) ni "
    "se estima ningún efecto causal."
)


def _numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


# --------------------------------------------------------------------------
# Población: cruce SIGMED <-> fuente de población, auditoría obligatoria
# --------------------------------------------------------------------------


def flag_population_representative(
    demand_df: pd.DataFrame, *, demand_key_col: str, demand_id_col: str, representative_override: dict[str, str],
) -> pd.Series:
    """Para cada grupo de filas de demanda que comparten la MISMA clave
    (p.ej. dos CODCP con el mismo CPINEI — dos filas SIGMED representan un
    único CP censal), decide cuál recibe la población (`True`) para que no
    se cuente dos veces. Nunca decide arbitrariamente "la primera fila": si
    la clave duplicada no tiene una entrada en `representative_override`
    (mapeo clave -> demand_id elegido, decidido y documentado por fuera,
    caso por caso), NINGUNA fila del grupo se marca representante — se trata
    como excepción explícita (`DUPLICATE_KEY_EXCLUDED`), no como una
    división arbitraria 50/50. Claves no duplicadas siempre son `True`."""
    key = demand_df[demand_key_col]
    is_dup_key = key.notna() & key.duplicated(keep=False)
    rep = pd.Series(True, index=demand_df.index)
    for k in key[is_dup_key].unique():
        mask = key == k
        winner = representative_override.get(str(k))
        if winner is None:
            rep.loc[mask] = False
        else:
            rep.loc[mask] = demand_df.loc[mask, demand_id_col].astype(str) == str(winner)
    return rep


def build_population_match_report(
    demand_df: pd.DataFrame,
    population_df: pd.DataFrame,
    *,
    demand_key_col: str,
    population_key_col: str,
    population_value_col: str,
    demand_id_col: str = "demand_id",
    demand_secondary_key_col: str | None = None,
    population_representative: pd.Series | None = None,
) -> pd.DataFrame:
    """Audita el cruce demand<->población por una clave dada.

    NO resuelve duplicados de la POBLACIÓN de forma arbitraria: si una clave
    de población aparece más de una vez, el registro de demanda queda
    `ambiguous` (no se promedia, no se toma el primero, no se imputa).
    Devuelve una fila por demand_id con: clave original, `population` (NaN
    salvo `matched`), `population_match_status`, `n_population_records_for_key`
    (para exponer duplicados en la fuente de población), `match_method`
    (nombre de la clave usada).

    Un `demand_key_col` nulo/vacío en el registro de demanda también produce
    `unmatched` (no se puede cruzar lo que no tiene clave) — nunca `matched`.

    `population_representative` (opcional, booleano, alineado al índice de
    `demand_df`, ver `flag_population_representative`): cuando DOS O MÁS
    filas de DEMANDA comparten la misma clave (un mismo CP censal
    representado más de una vez en el frame SIGMED), solo la fila marcada
    `True` recibe `population`; las demás quedan `DUPLICATE_KEY_EXCLUDED`
    con `population=NaN` — evita que un mismo CP censal aporte su población
    dos veces si ambas filas cayeran en el mismo análisis.
    """
    demand_keys = demand_df[[demand_id_col, demand_key_col]].copy()
    demand_keys[demand_key_col] = demand_keys[demand_key_col].astype("string")

    pop = population_df[[population_key_col, population_value_col]].copy()
    pop[population_key_col] = pop[population_key_col].astype("string")
    key_counts = pop.groupby(population_key_col).size().rename("n_population_records_for_key")

    # first() solo se usa para exponer un valor de referencia en casos
    # ambiguous al auditor; el status ambiguous ya deja claro que NO debe
    # tomarse como población resuelta.
    pop_first = pop.groupby(population_key_col)[population_value_col].first()

    out = demand_keys.merge(
        key_counts.to_frame().join(pop_first), left_on=demand_key_col, right_index=True, how="left"
    )
    out["n_population_records_for_key"] = out["n_population_records_for_key"].fillna(0).astype(int)

    has_key = out[demand_key_col].notna() & (out[demand_key_col].astype(str).str.len() > 0)
    n = out["n_population_records_for_key"]

    status = np.select(
        [~has_key, has_key & (n == 0), has_key & (n == 1), has_key & (n > 1)],
        [UNMATCHED, UNMATCHED, MATCHED, AMBIGUOUS],
        default=UNMATCHED,
    )
    out["population_match_status"] = status
    out["population"] = np.where(status == MATCHED, _numeric(out[population_value_col]), np.nan)
    out["match_method"] = np.where(has_key, demand_key_col, "no_key")
    out = out.drop(columns=[population_value_col])

    if population_representative is not None:
        not_representative = ~population_representative.reindex(out.index).fillna(True).astype(bool)
        excluded = not_representative & (out["population_match_status"] == MATCHED)
        out.loc[excluded, "population_match_status"] = DUPLICATE_KEY_EXCLUDED
        out.loc[excluded, "population"] = np.nan

    if demand_secondary_key_col is not None:
        # No se resuelve nada automáticamente: solo se expone si la clave
        # secundaria (p.ej. CPINEI2) hubiera dado un resultado DISTINTO al
        # de la clave primaria — para auditoría manual (nunca para elegir
        # población por sí sola).
        secondary = demand_df[[demand_id_col, demand_secondary_key_col]].copy()
        secondary[demand_secondary_key_col] = secondary[demand_secondary_key_col].astype("string")
        pop_keys = set(pop[population_key_col].dropna())
        out = out.merge(secondary, on=demand_id_col, how="left")
        sec = out[demand_secondary_key_col]
        prim = out[demand_key_col]
        out["secondary_key_present"] = sec.notna()
        out["secondary_key_disagrees_with_primary"] = sec.notna() & (sec != prim) & sec.isin(pop_keys)
        out = out.drop(columns=[demand_secondary_key_col])

    return out.reset_index(drop=True)


def cross_validate_population_sources(
    source_a: pd.DataFrame, source_b: pd.DataFrame, *,
    key_a: str, key_b: str, value_a: str, value_b: str,
) -> dict:
    """Compara dos fuentes de población independientes cruzadas por su
    propia clave (p.ej. CENEPRED `codccpp` vs MINAM `idccpp_17`). Reporta N
    comparable, N con población idéntica, N discrepante, diferencia
    absoluta/porcentual, y ejemplos discrepantes — nunca elige una fuente
    arbitrariamente si difieren."""
    a = source_a[[key_a, value_a]].copy()
    a[key_a] = a[key_a].astype("string")
    b = source_b[[key_b, value_b]].copy()
    b[key_b] = b[key_b].astype("string")
    merged = a.merge(b, left_on=key_a, right_on=key_b, how="inner")
    merged["diff_abs"] = (_numeric(merged[value_a]) - _numeric(merged[value_b])).abs()
    merged["diff_pct"] = 100.0 * merged["diff_abs"] / _numeric(merged[value_a]).replace(0, np.nan)
    n = len(merged)
    n_identical = int((merged["diff_abs"] == 0).sum())
    examples = merged.sort_values("diff_abs", ascending=False).head(10)
    return {
        "n_comparable": n,
        "n_identical": n_identical,
        "pct_identical": 100.0 * n_identical / n if n else np.nan,
        "n_discrepant": n - n_identical,
        "diff_abs_summary": merged["diff_abs"].describe().to_dict() if n else {},
        "discrepant_examples": examples,
    }


def population_control_by_department(
    match_report: pd.DataFrame, demand_df: pd.DataFrame, benchmark_df: pd.DataFrame, *,
    demand_id_col: str = "demand_id", dep_col: str = "DEP",
    benchmark_dep_col: str = "dep", benchmark_pop_col: str = "poblacion_censo2017_real",
) -> pd.DataFrame:
    """Compara la población matched agregada por departamento contra un
    benchmark censal oficial — NO se espera coincidencia exacta (SIGMED no
    contiene todos los CP, la muestra es de 5000, puede haber CP omitidos),
    pero la diferencia debe quedar expuesta, no oculta."""
    merged = match_report.merge(demand_df[[demand_id_col, dep_col]], on=demand_id_col, how="left")
    observed = merged[merged["population_match_status"] == MATCHED].groupby(dep_col)["population"].sum().rename("poblacion_matched_observada")
    bench = benchmark_df.set_index(benchmark_dep_col)[benchmark_pop_col].rename("poblacion_censo2017_benchmark")
    out = pd.concat([observed, bench], axis=1).reset_index().rename(columns={"index": dep_col})
    out["diff_abs"] = out["poblacion_censo2017_benchmark"] - out["poblacion_matched_observada"]
    out["pct_del_benchmark_capturado"] = 100.0 * out["poblacion_matched_observada"] / out["poblacion_censo2017_benchmark"]
    return out


def population_match_summary(match_report: pd.DataFrame, demand_df: pd.DataFrame, *, dep_col: str = "DEP", demand_id_col: str = "demand_id") -> pd.DataFrame:
    """N y % de match global y por departamento — para la Sección C del informe."""
    merged = match_report.merge(demand_df[[demand_id_col, dep_col]], on=demand_id_col, how="left")
    rows = []
    for dep, g in [("TOTAL", merged)] + list(merged.groupby(dep_col)):
        n = len(g)
        counts = g["population_match_status"].value_counts()
        rows.append({
            "dep": dep,
            "n_total": n,
            "n_matched": int(counts.get(MATCHED, 0)),
            "n_unmatched": int(counts.get(UNMATCHED, 0)),
            "n_ambiguous": int(counts.get(AMBIGUOUS, 0)),
            "pct_matched": 100.0 * counts.get(MATCHED, 0) / n if n else np.nan,
            "population_sum_matched": g.loc[g["population_match_status"] == MATCHED, "population"].sum(),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Pesos de análisis
# --------------------------------------------------------------------------


def verify_design_weights(df: pd.DataFrame, *, inclusion_prob_col: str = "inclusion_prob", design_weight_col: str = "design_weight", stratum_col: str | None = None, rtol: float = 1e-6) -> dict:
    """Re-verifica `design_weight = 1/inclusion_prob` (no recalibra nada)."""
    expected = 1.0 / _numeric(df[inclusion_prob_col])
    actual = _numeric(df[design_weight_col])
    diff = (expected - actual).abs()
    result = {
        "n": len(df),
        "max_abs_diff": float(diff.max()) if len(df) else np.nan,
        "all_consistent_within_rtol": bool(np.allclose(expected, actual, rtol=rtol, equal_nan=True)),
        "design_weight_min": float(actual.min()) if len(df) else np.nan,
        "design_weight_max": float(actual.max()) if len(df) else np.nan,
    }
    if stratum_col is not None:
        per_stratum_nunique = df.assign(_dw=actual).groupby(stratum_col)["_dw"].nunique()
        result["design_weight_constant_within_stratum"] = bool((per_stratum_nunique <= 1).all())
        result["strata_with_varying_weight"] = int((per_stratum_nunique > 1).sum())
    return result


def build_analysis_weights(match_report: pd.DataFrame, demand_df: pd.DataFrame, *, demand_id_col: str = "demand_id", design_weight_col: str = "design_weight") -> pd.DataFrame:
    """`analysis_weight_i = population_i * design_weight_i`, SOLO donde
    `population_match_status == "matched"`. Nunca se calcula (queda NaN) para
    `unmatched`/`ambiguous` — no se sustituye `design_weight` por población."""
    out = match_report.merge(demand_df[[demand_id_col, design_weight_col]], on=demand_id_col, how="left")
    out["analysis_weight"] = np.where(
        out["population_match_status"] == MATCHED,
        out["population"] * _numeric(out[design_weight_col]),
        np.nan,
    )
    return out


CALIBRATED = "calibrated"
CALIBRATION_IMPOSSIBLE = "impossible_no_sample"


def calibrate_weights_by_district(
    df: pd.DataFrame,
    known_population_by_group: pd.DataFrame,
    *,
    group_cols: list[str],
    ht_weight_col: str = "ht_population_weight",
    known_population_col: str = "known_population",
) -> dict[str, pd.DataFrame]:
    """Calibra `ht_weight_col` (Horvitz-Thompson, = population × design_weight,
    SIN calibrar) contra la población censal real conocida del frame matched
    (U4) por grupo (distrito). Para cada grupo h:

        HT_total_h = Σ ht_weight_col  (sobre las filas de `df` de ese grupo)
        calibration_factor_h = known_population_h / HT_total_h
        calibrated_weight_i = ht_weight_col_i × calibration_factor_h

    Si `HT_total_h == 0` (sin ninguna fila de muestra con peso válido en ese
    grupo) pero `known_population_h > 0`, el grupo queda
    `calibration_status = "impossible_no_sample"` — NO se inventa un peso;
    `calibration_factor` y `calibrated_weight` quedan `NaN` para ese grupo
    (el HT sin calibrar de ese grupo, si existe, ya era 0/NaN de por sí).

    Devuelve `{"row_level": df con calibrated_weight añadido,
    "district_level": una fila por grupo con HT_total, known_population,
    calibration_factor, calibration_status}`."""
    ht_by_group = df.groupby(group_cols)[ht_weight_col].apply(lambda s: _numeric(s).sum(min_count=1)).rename("ht_total")
    known = known_population_by_group.set_index(group_cols)[known_population_col].rename("known_population")
    dist = pd.concat([ht_by_group, known], axis=1).reset_index()
    dist["ht_total"] = dist["ht_total"].fillna(0.0)

    impossible = (dist["known_population"] > 0) & (dist["ht_total"] == 0)
    dist["calibration_status"] = np.where(impossible, CALIBRATION_IMPOSSIBLE, CALIBRATED)
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = dist["known_population"] / dist["ht_total"]
    dist["calibration_factor"] = np.where(dist["calibration_status"] == CALIBRATED, factor, np.nan)

    row = df.merge(dist[group_cols + ["calibration_factor", "calibration_status", "ht_total", "known_population"]], on=group_cols, how="left")
    row["calibrated_weight"] = row[ht_weight_col] * row["calibration_factor"]

    return {"row_level": row, "district_level": dist}


def effective_sample_size(weights: pd.Series | np.ndarray) -> float:
    """`n_eff = (Σw)^2 / Σ(w^2)` — diagnóstico de CONCENTRACIÓN de pesos
    (cuántas observaciones "equivalentes" de peso igual aportarían la misma
    varianza que los pesos reales), NO el tamaño muestral literal (que es
    simplemente `w.notna().sum()`)."""
    w = _numeric(pd.Series(weights)).dropna()
    w = w[w > 0]
    if len(w) == 0:
        return np.nan
    return float((w.sum() ** 2) / (w**2).sum())


def sample_representativeness_summary(demand_df: pd.DataFrame, match_report: pd.DataFrame, *, dep_col: str = "DEP", demand_id_col: str = "demand_id", design_weight_col: str = "design_weight") -> pd.DataFrame:
    """Suma de población observada, estimación expandida por design_weight,
    participación estimada por departamento. Requiere `population` real
    (columna de `match_report`); si todo es `unmatched`, las columnas de
    población salen en 0/NaN de forma honesta (no se inventa un valor)."""
    df = match_report.merge(demand_df[[demand_id_col, dep_col, design_weight_col]], on=demand_id_col, how="left")
    df["design_weight"] = _numeric(df[design_weight_col])
    rows = []
    for dep, g in [("TOTAL", df)] + list(df.groupby(dep_col)):
        matched = g[g["population_match_status"] == MATCHED]
        rows.append({
            "dep": dep,
            "n_cp": len(g),
            "n_cp_population_matched": len(matched),
            "observed_sample_population_sum": matched["population"].sum(),
            "design_weight_expanded_population_estimate": (matched["population"] * matched["design_weight"]).sum(),
        })
    out = pd.DataFrame(rows)
    total_est = out.loc[out["dep"] == "TOTAL", "design_weight_expanded_population_estimate"].iloc[0]
    out["estimated_participation_pct"] = np.where(
        (out["dep"] != "TOTAL") & (total_est not in (0, None) and not pd.isna(total_est)),
        100.0 * out["design_weight_expanded_population_estimate"] / total_est if total_est else np.nan,
        np.nan,
    )
    return out


# --------------------------------------------------------------------------
# Métrica 1 — tiempo de acceso
# --------------------------------------------------------------------------


def compute_access_time(df: pd.DataFrame, *, routing_status_col: str = "routing_status_car", travel_time_col: str = "travel_time_min_car") -> pd.Series:
    """`t_min`: tiempo en auto SOLO donde `routing_status_col == "routed"`.
    Nunca imputa 0 ni infinito; el resto queda `NaN` (la razón se preserva
    aparte, en `routing_status_col`, no se pierde)."""
    is_routed = df[routing_status_col] == ROUTED
    return pd.Series(np.where(is_routed, _numeric(df[travel_time_col]), np.nan), index=df.index, name="t_min")


# --------------------------------------------------------------------------
# Completitud de ruteo (universo completo, en CP y en población)
# --------------------------------------------------------------------------


def routing_completeness_summary(df: pd.DataFrame, *, status_col: str = "routing_status_car", weight_col: str = "analysis_weight") -> pd.DataFrame:
    """Tabla `Estado | N CP | población ponderada | % población ponderada`.
    Incluye TODOS los estados presentes (routed, snap_failed,
    no_route_same_department, y — si están codificados como estado en
    `status_col` — population_unmatched/population_ambiguous). La suma de
    `pop_ponderada` es auditable: coincide con la suma total de `weight_col`
    sobre filas con peso no nulo."""
    g = df.groupby(status_col, dropna=False)
    n_cp = g.size().rename("n_cp")
    pop_w = g[weight_col].apply(lambda s: _numeric(s).sum(min_count=1)).rename("poblacion_ponderada")
    out = pd.concat([n_cp, pop_w], axis=1).reset_index().rename(columns={status_col: "estado"})
    total_w = out["poblacion_ponderada"].sum(min_count=1)
    out["pct_poblacion_ponderada"] = 100.0 * out["poblacion_ponderada"] / total_w if total_w else np.nan
    out["n_cp_total"] = out["n_cp"].sum()
    out["pct_n_cp"] = 100.0 * out["n_cp"] / out["n_cp_total"]
    return out.drop(columns=["n_cp_total"])


# --------------------------------------------------------------------------
# Métrica 2 — bandas de cobertura
# --------------------------------------------------------------------------


def _assign_band(t: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [t <= 30, (t > 30) & (t <= 60), (t > 60) & (t <= 120), t > 120],
            [BAND_LE30, BAND_30_60, BAND_60_120, BAND_GT120],
            default=BAND_UNROUTABLE,
        ),
        index=t.index,
    )


def compute_coverage_bands(df: pd.DataFrame, *, time_col: str = "t_min", weight_col: str = "analysis_weight") -> dict:
    """Dos lecturas, nunca mezcladas:

    - `reading_a` (`sobre_poblacion_con_tiempo_estimable`): SOLO filas con
      `t_min` no nulo y peso no nulo. Las 4 bandas suman 100%.
    - `reading_b` (`sobre_poblacion_total_estimada`): todas las filas con
      peso no nulo (tenga o no `t_min`). Incluye `unroutable_or_not_estimated`
      como categoría propia — nunca fusionada con `>120`.
    """
    w = _numeric(df[weight_col])
    valid_w = w.notna()
    t = _numeric(df[time_col])

    has_time = valid_w & t.notna()
    a = df.loc[has_time].assign(_band=_assign_band(t.loc[has_time]), _w=w.loc[has_time])
    a_sum = a.groupby("_band")["_w"].sum(min_count=1).reindex(COVERAGE_BANDS).fillna(0.0)
    total_a = a_sum.sum()
    reading_a = pd.DataFrame({
        "band": COVERAGE_BANDS,
        "poblacion_ponderada": a_sum.values,
        "pct": (100.0 * a_sum / total_a).values if total_a else np.full(len(COVERAGE_BANDS), np.nan),
    })

    band_b = pd.Series(np.where(has_time, _assign_band(t).astype(object), BAND_UNROUTABLE), index=df.index)
    b = pd.DataFrame({"_band": band_b, "_w": w}).loc[valid_w]
    all_bands_b = list(COVERAGE_BANDS) + [BAND_UNROUTABLE]
    b_sum = b.groupby("_band")["_w"].sum(min_count=1).reindex(all_bands_b).fillna(0.0)
    total_b = b_sum.sum()
    cum = b_sum.reindex([BAND_LE30, BAND_30_60, BAND_60_120]).cumsum()
    reading_b = pd.DataFrame({
        "band": all_bands_b,
        "poblacion_ponderada": b_sum.values,
        "pct": (100.0 * b_sum / total_b).values if total_b else np.full(len(all_bands_b), np.nan),
    })
    reading_b_cumulative = pd.DataFrame({
        "band": ["<=30", "<=60 (cum)", "<=120 (cum)", ">120", "sin_tiempo_estimable"],
        "poblacion_ponderada": [
            b_sum.get(BAND_LE30, 0.0), cum.get(BAND_30_60, np.nan), cum.get(BAND_60_120, np.nan),
            b_sum.get(BAND_GT120, 0.0), b_sum.get(BAND_UNROUTABLE, 0.0),
        ],
    })
    reading_b_cumulative["pct"] = 100.0 * reading_b_cumulative["poblacion_ponderada"] / total_b if total_b else np.nan

    return {
        "reading_a_sobre_poblacion_con_tiempo_estimable": reading_a,
        "reading_b_sobre_poblacion_total": reading_b,
        "reading_b_cumulative": reading_b_cumulative,
        "n_valid_weight": int(valid_w.sum()),
        "n_valid_weight_with_time": int(has_time.sum()),
    }


# --------------------------------------------------------------------------
# Métrica 3 — media ponderada por población
# --------------------------------------------------------------------------


def weighted_mean_access(df: pd.DataFrame, group_cols: list[str] | None, *, time_col: str = "t_min", weight_col: str = "analysis_weight", population_col: str = "population") -> pd.DataFrame:
    """Media ponderada de `t_min`, calculada SOLO sobre filas con tiempo
    ruteado y peso válido. Por cada grupo también reporta la población
    total estimada, la población con tiempo, y el % con tiempo — para que
    nunca se presente una media como representativa si la cobertura de
    ruteo del grupo es baja (eso lo decide `rank_critical_gaps` con el flag)."""
    d = df.copy()
    d["_t"] = _numeric(d[time_col])
    d["_w"] = _numeric(d[weight_col])
    d["_pop"] = _numeric(d[population_col])
    keys = group_cols if group_cols else []

    def _agg(g: pd.DataFrame) -> pd.Series:
        has_weight = g["_w"].notna()
        has_time_and_weight = g["_t"].notna() & has_weight
        w = g.loc[has_time_and_weight, "_w"]
        t = g.loc[has_time_and_weight, "_t"]
        wsum = w.sum()
        mean = float((t * w).sum() / wsum) if wsum else np.nan
        total_pop = g["_pop"].sum(min_count=1)
        # OJO: min_count=1 aquí (a diferencia de total_pop) daría NaN cuando
        # NINGÚN CP del grupo tiene tiempo ruteado, aunque sí haya población
        # matched — eso confundiría "0% con tiempo estimable" (dato real,
        # cobertura de ruteo nula) con "sin dato de población" (NaN real).
        pop_with_time = g.loc[has_time_and_weight, "_pop"].sum()
        return pd.Series({
            "weighted_mean_access_min": mean,
            "n_cp": len(g),
            "n_cp_with_weight": int(has_weight.sum()),  # CP de la muestra con poblacion (peso) valido en el grupo, tenga o no tiempo ruteado
            "n_cp_with_time": int(has_time_and_weight.sum()),
            "total_estimated_population": total_pop,
            "population_with_travel_time": pop_with_time,
            "share_population_with_travel_time_pct": 100.0 * pop_with_time / total_pop if total_pop else np.nan,
        })

    if keys:
        out = d.groupby(keys, dropna=False).apply(_agg, include_groups=False).reset_index()
    else:
        out = _agg(d).to_frame().T
        out.insert(0, "scope", "total")
    return out


def weighted_median(values: pd.Series | np.ndarray, weights: pd.Series | np.ndarray) -> float:
    """Mediana ponderada — usada en la comparación urbano/rural (Metric 6)."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = ~np.isnan(v) & ~np.isnan(w) & (w > 0)
    v, w = v[mask], w[mask]
    if len(v) == 0:
        return np.nan
    order = np.argsort(v)
    v, w = v[order], w[order]
    cum = np.cumsum(w)
    cutoff = cum[-1] / 2.0
    idx = np.searchsorted(cum, cutoff)
    return float(v[min(idx, len(v) - 1)])


# --------------------------------------------------------------------------
# Métrica 4 — ranking de brechas críticas
# --------------------------------------------------------------------------


def rank_critical_gaps(
    weighted_access_by_district: pd.DataFrame,
    coverage_bands_by_district: pd.DataFrame | None = None,
    *,
    district_cols: list[str],
    low_routing_coverage_threshold_pct: float = 50.0,
) -> pd.DataFrame:
    """Ordena distritos por `weighted_mean_access_min` descendente
    (peor acceso primero). Añade `low_routing_coverage_warning` (umbral
    configurable, documentado aquí: {threshold}% de la población con tiempo
    estimable) — NUNCA excluye automáticamente distritos con baja cobertura,
    solo los marca."""
    out = weighted_access_by_district.copy()
    share = out["share_population_with_travel_time_pct"]
    # NaN (no se pudo estimar ni el % con tiempo -- ni siquiera hay CP con
    # tiempo ruteado) se trata como el caso MÁS bajo de cobertura posible,
    # no como "sin advertencia" (NaN < umbral evalúa False por defecto).
    out["low_routing_coverage_warning"] = share.isna() | (share < low_routing_coverage_threshold_pct)
    out["low_routing_coverage_threshold_pct"] = low_routing_coverage_threshold_pct
    if coverage_bands_by_district is not None:
        out = out.merge(coverage_bands_by_district, on=district_cols, how="left")
    out = out.sort_values("weighted_mean_access_min", ascending=False, na_position="first").reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    return out


#: Estados de calidad de dato a nivel distrito (corrección estadística
#: final, 2026-09-11) — evita que un distrito NO COMPUTABLE (sin muestra,
#: sin ruteo) aparezca al inicio del ranking de peor acceso solo por
#: ordenamiento de NaN. `computable` es el único estado que entra al ranking
#: de brechas críticas; el resto va a `districts_with_insufficient_data`.
DISTRICT_COMPUTABLE = "computable"
DISTRICT_LOW_ROUTING_COVERAGE = "low_routing_coverage"
DISTRICT_ZERO_ROUTING_COVERAGE = "zero_routing_coverage"
DISTRICT_LOW_POPULATION_SAMPLE_COVERAGE = "low_population_sample_coverage"
DISTRICT_ZERO_POPULATION_SAMPLE_COVERAGE = "zero_population_sample_coverage"
DISTRICT_CALIBRATION_IMPOSSIBLE = "calibration_impossible"


def classify_district_data_quality(
    df: pd.DataFrame,
    *,
    n_cp_with_weight_col: str = "n_cp_with_weight",
    n_cp_with_time_col: str = "n_cp_with_time",
    share_col: str = "share_population_with_travel_time_pct",
    calibration_status_col: str = "calibration_status",
    low_routing_coverage_threshold_pct: float = 50.0,
    min_cp_with_weight_for_low_population_flag: int = 3,
) -> pd.Series:
    """Clasifica cada distrito en exactamente uno de 6 estados, evaluados en
    orden de severidad/prioridad (un distrito con calibración imposible NO
    se re-etiqueta también como baja cobertura de ruteo, aunque ambas
    condiciones puedan coexistir):

    1. `calibration_impossible` — no se pudo calibrar (sin muestra con peso
       en un distrito con población censal conocida > 0).
    2. `zero_population_sample_coverage` — 0 CP de la MUESTRA con población
       válida en el distrito (sin `calibration_status`, p.ej. sensibilidad HT).
    3. `low_population_sample_coverage` — menos de
       `min_cp_with_weight_for_low_population_flag` CP con población válida.
    4. `zero_routing_coverage` — 0 CP con tiempo ruteado (aunque haya
       población).
    5. `low_routing_coverage` — % de población con tiempo estimable por
       debajo del umbral (o no calculable).
    6. `computable` — ninguna de las anteriores.
    """
    calib_impossible = (
        df[calibration_status_col] == CALIBRATION_IMPOSSIBLE if calibration_status_col in df.columns else pd.Series(False, index=df.index)
    )
    zero_pop = df[n_cp_with_weight_col] == 0
    low_pop = (~zero_pop) & (df[n_cp_with_weight_col] < min_cp_with_weight_for_low_population_flag)
    zero_routing = df[n_cp_with_time_col] == 0
    share = df[share_col]
    low_routing = share.isna() | (share < low_routing_coverage_threshold_pct)

    status = np.select(
        [calib_impossible, zero_pop, low_pop, zero_routing, low_routing],
        [DISTRICT_CALIBRATION_IMPOSSIBLE, DISTRICT_ZERO_POPULATION_SAMPLE_COVERAGE, DISTRICT_LOW_POPULATION_SAMPLE_COVERAGE, DISTRICT_ZERO_ROUTING_COVERAGE, DISTRICT_LOW_ROUTING_COVERAGE],
        default=DISTRICT_COMPUTABLE,
    )
    return pd.Series(status, index=df.index)


def split_critical_gaps(
    weighted_access_by_district: pd.DataFrame, *, status_col: str = "district_status",
) -> dict[str, pd.DataFrame]:
    """Separa el ranking en `worst_computable_districts` (solo
    `district_status == "computable"`, ordenado por peor tiempo medio
    ponderado DESC — un distrito no-computable NUNCA aparece aquí, ni al
    inicio ni al final) y `districts_with_insufficient_data` (todo lo
    demás, con su motivo explícito)."""
    computable = weighted_access_by_district[weighted_access_by_district[status_col] == DISTRICT_COMPUTABLE].copy()
    computable = computable.sort_values("weighted_mean_access_min", ascending=False).reset_index(drop=True)
    computable.insert(0, "rank", np.arange(1, len(computable) + 1))

    insufficient = weighted_access_by_district[weighted_access_by_district[status_col] != DISTRICT_COMPUTABLE].copy()
    insufficient = insufficient.sort_values(status_col).reset_index(drop=True)
    return {"worst_computable_districts": computable, "districts_with_insufficient_data": insufficient}


# --------------------------------------------------------------------------
# Métrica 5 — Gini ponderado + curva de Lorenz
# --------------------------------------------------------------------------


def weighted_gini(values: pd.Series | np.ndarray, weights: pd.Series | np.ndarray) -> dict:
    """Gini ponderado por población (Lorenz discreta) del tiempo de acceso.

    Por qué Gini aquí: mide qué tan desigualmente se distribuye el tiempo de
    acceso ENTRE la población (no entre CP) — un Gini alto indica que unos
    pocos habitantes concentran tiempos de acceso muy altos frente a la
    mayoría, más allá de cuál sea la media. Es una medida de desigualdad de
    un "mal" (tiempo), no de un "bien" (ingreso): un Gini=0 significa acceso
    perfectamente homogéneo (no necesariamente bueno), y valores más altos
    indican mayor concentración de la carga de tiempo de viaje en una
    fracción pequeña de la población.

    Se calcula ÚNICAMENTE sobre población con tiempo estimado (no se asigna
    un tiempo arbitrario a quienes no tienen ruta) — se reporta aparte el
    % de población excluida por no tener tiempo estimable."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask_all = ~np.isnan(w) & (w > 0)
    total_w = w[mask_all].sum()
    mask_valid = mask_all & ~np.isnan(v)
    v, w = v[mask_valid], w[mask_valid]
    n = len(v)
    excluded_w = total_w - w.sum() if total_w else np.nan
    pct_excluded = 100.0 * excluded_w / total_w if total_w else np.nan

    if n == 0 or w.sum() == 0:
        return {"gini": np.nan, "n_included": 0, "population_included": 0.0, "pct_population_excluded": pct_excluded}

    order = np.argsort(v)
    v, w = v[order], w[order]
    cum_w = np.cumsum(w)
    cum_wv = np.cumsum(w * v)
    total_wv = cum_wv[-1]
    total_ww = cum_w[-1]
    # Gini ponderado (forma discreta del índice de Brown / trapezoidal Lorenz)
    lorenz_y = np.concatenate([[0.0], cum_wv / total_wv]) if total_wv else np.zeros(n + 1)
    lorenz_x = np.concatenate([[0.0], cum_w / total_ww])
    area_under_lorenz = np.trapezoid(lorenz_y, lorenz_x)
    gini = 1.0 - 2.0 * area_under_lorenz
    return {
        "gini": float(gini),
        "n_included": int(n),
        "population_included": float(w.sum()),
        "pct_population_excluded": float(pct_excluded),
    }


def build_lorenz_curve(values: pd.Series | np.ndarray, weights: pd.Series | np.ndarray) -> pd.DataFrame:
    """Puntos (x=% población acumulada, y=% tiempo de acceso acumulado)
    ordenando por tiempo ascendente — insumo de la Figura 2."""
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = ~np.isnan(v) & ~np.isnan(w) & (w > 0)
    v, w = v[mask], w[mask]
    if len(v) == 0:
        return pd.DataFrame(columns=["cum_pop_share", "cum_time_share"])
    order = np.argsort(v)
    v, w = v[order], w[order]
    cum_w = np.cumsum(w) / w.sum()
    cum_wv = np.cumsum(w * v)
    cum_wv = cum_wv / cum_wv[-1] if cum_wv[-1] else cum_wv
    return pd.DataFrame({
        "cum_pop_share": np.concatenate([[0.0], cum_w]),
        "cum_time_share": np.concatenate([[0.0], cum_wv]),
    })


# --------------------------------------------------------------------------
# Métrica 6 — urbano vs rural
# --------------------------------------------------------------------------


def urban_rural_summary(df: pd.DataFrame, *, urban_rural_col: str = "urban_rural", time_col: str = "t_min", weight_col: str = "analysis_weight") -> pd.DataFrame:
    rows = []
    for cat in (URBAN, RURAL, UNKNOWN_RURALITY):
        g = df[df[urban_rural_col] == cat]
        w = _numeric(g[weight_col])
        t = _numeric(g[time_col])
        valid = w.notna()
        has_time = valid & t.notna()
        wv = w[has_time]
        tv = t[has_time]
        bands = compute_coverage_bands(g, time_col=time_col, weight_col=weight_col)["reading_a_sobre_poblacion_con_tiempo_estimable"]
        band_pct = dict(zip(bands["band"], bands["pct"]))
        rows.append({
            "urban_rural": cat,
            "n_cp": len(g),
            "weighted_mean_access_min": float((tv * wv).sum() / wv.sum()) if wv.sum() else np.nan,
            "weighted_median_access_min": weighted_median(tv, wv),
            "pct_le_30": band_pct.get(BAND_LE30, np.nan),
            "pct_30_60": band_pct.get(BAND_30_60, np.nan),
            "pct_60_120": band_pct.get(BAND_60_120, np.nan),
            "pct_gt_120": band_pct.get(BAND_GT120, np.nan),
            "n_valid_weight": int(valid.sum()),
            "n_valid_weight_with_time": int(has_time.sum()),
            "pct_without_routable_estimate": 100.0 * (valid & ~has_time).sum() / valid.sum() if valid.sum() else np.nan,
        })
    return pd.DataFrame(rows)


def rurality_access_cross_analysis(df: pd.DataFrame, *, urban_rural_col: str = "urban_rural", time_col: str = "t_min", weight_col: str = "analysis_weight") -> dict:
    """Cruce rural/urbano x acceso x cobertura <=60/<=120 — Sección K.
    Declaración explícita de no-causalidad incluida en el resultado."""
    summary = urban_rural_summary(df, urban_rural_col=urban_rural_col, time_col=time_col, weight_col=weight_col)
    summary["cum_pct_le_60"] = summary["pct_le_30"] + summary["pct_30_60"]
    summary["cum_pct_le_120"] = summary["cum_pct_le_60"] + summary["pct_60_120"]
    return {"table": summary, "interpretation": CAUSAL_DISCLAIMER, "causal_claim_made": False}


# --------------------------------------------------------------------------
# Casos extremos y auditorías puntuales
# --------------------------------------------------------------------------


def top_extreme_access_cases(df: pd.DataFrame, n: int = 20, *, time_col: str = "t_min") -> pd.DataFrame:
    """Top-N por tiempo de acceso en auto ruteado más alto — NO elimina
    outliers, solo los expone para auditoría (Sección M)."""
    t = _numeric(df[time_col])
    valid = df.loc[t.notna()].assign(_t=t[t.notna()])
    return valid.sort_values("_t", ascending=False).head(n).drop(columns=["_t"])


def unroutable_concentration_summary(df: pd.DataFrame, *, status_col: str = "routing_status_car", group_cols: list[str] | None = None, weight_col: str = "analysis_weight") -> pd.DataFrame:
    """Distribución de `snap_failed` / `no_route_same_department` por
    departamento y/o urbano-rural, en N y en población ponderada — Sección L.
    No convierte estos estados en ">120 min"; se agrupan tal cual están."""
    group_cols = group_cols or []
    keys = group_cols + [status_col]
    g = df.groupby(keys, dropna=False)
    n = g.size().rename("n_cp")
    w = g[weight_col].apply(lambda s: _numeric(s).sum(min_count=1)).rename("poblacion_ponderada")
    out = pd.concat([n, w], axis=1).reset_index()
    total_w = _numeric(df[weight_col]).sum(min_count=1)
    out["pct_poblacion_ponderada_del_total"] = 100.0 * out["poblacion_ponderada"] / total_w if total_w else np.nan
    return out


def foot_over_car_extreme_ratio(three_mode_df: pd.DataFrame, *, ratio_col: str = "foot_over_car_ratio", threshold: float = 100.0) -> pd.DataFrame:
    """Casos con `foot_time/car_time > threshold` (pendiente de Fase 2) —
    para clasificación manual documentada (Sección N), no corrige nada."""
    r = _numeric(three_mode_df[ratio_col])
    return three_mode_df.loc[r > threshold].sort_values(ratio_col, ascending=False)


def track_impact_table(*, routed_before: int, routed_after: int, points_recovered: int, universe_n: int) -> pd.DataFrame:
    """Tabla metodológica (NO resultado principal): reusa los conteos ya
    calculados en Fase 2 (`routing_quality_report.csv`:
    `car_track_recovers_route_to_resolutive`) — no vuelve a rutear nada."""
    abs_increase = routed_after - routed_before
    pct_increase = 100.0 * abs_increase / routed_before if routed_before else np.nan
    return pd.DataFrame([{
        "routed_car_before_track": routed_before,
        "routed_car_after_track": routed_after,
        "absolute_increase": abs_increase,
        "pct_increase": pct_increase,
        "points_recovered_route": points_recovered,
        "universe_n": universe_n,
        "note": "Sensibilidad/metodología (Fase 2->3), no es resultado principal.",
    }])
