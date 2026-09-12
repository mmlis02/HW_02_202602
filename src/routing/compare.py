"""Comparaciones diagnósticas — car vs bike vs foot, red vs línea recta.

Todo aquí es diagnóstico para Fase 2/discusión del informe. NO calcula
cobertura 30/60/120 min (Fase 3) ni aplica ningún factor de corrección: el
"detour factor" (red/línea recta) se reporta como distribución empírica, no se
usa para nada todavía.

**Nota metodológica (auditoría 2026-09-11) — `straight_line_vs_network`**: la
distancia recta se calcula sobre la coordenada ORIGINAL del punto (demanda o
facility); la distancia de red se calcula sobre su NODO SNAPEADO. Son dos
sistemas de referencia ligeramente distintos (difieren por la distancia de
snap, típicamente unos pocos a unas pocas decenas de metros). Para viajes muy
cortos, esa diferencia puede ser una fracción no despreciable del viaje total
y ocasionalmente produce `network_distance / straight_distance < 1` — algo
imposible en teoría (la recta es siempre ≤ la ruta real), pero explicable y
negligible aquí: verificado sobre datos reales, ocurre en ~0.1% de los pares y
con magnitud acotada por la suma de las dos distancias de snap involucradas.
No se fuerza el ratio a ≥1 ni se descartan esos casos — se documentan tal
cual, como una limitación conocida de comparar coordenada cruda contra nodo
snapeado, no como una corrección aplicada a los datos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_EARTH_RADIUS_M = 6371000.0


def haversine_m(lon1, lat1, lon2, lat2) -> np.ndarray:
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _numeric(series: pd.Series) -> pd.Series:
    """Fuerza a float64/NaN — un parquet con una columna enteramente None (caso
    típico en subconjuntos pequeños sin ningún par alcanzable) puede releerse
    como dtype=object con `None` de Python en vez de NaN, y `None / None`
    lanza TypeError en vez de dar NaN."""
    return pd.to_numeric(series, errors="coerce")


def nearest_by_mode(matrix_df: pd.DataFrame) -> pd.DataFrame:
    """Para cada (demand_id, mode), la facility RESOLUTIVA más cercana (mínimo
    travel_time_min entre las alcanzables). No incluye demand points sin
    ninguna facility alcanzable en ese modo (se puede inferir por conteo)."""
    matrix_df = matrix_df.copy()
    matrix_df["travel_time_min"] = _numeric(matrix_df["travel_time_min"])
    matrix_df["distance_m"] = _numeric(matrix_df["distance_m"])
    reachable = matrix_df[matrix_df["reachable"] == True]  # noqa: E712 (evita comparar con None/NaN)
    if reachable.empty:
        return reachable.copy()
    idx = reachable.groupby(["demand_id", "mode"])["travel_time_min"].idxmin()
    return reachable.loc[idx].reset_index(drop=True)


#: Categorías MUTUAMENTE EXCLUYENTES para comparar dos modos por nearest
#: facility (corrección de auditoría, 2026-09-11): el cálculo anterior
#: contaba "reachability mixta" (un modo sin nearest) como "cambió de
#: facility", inflando el % de cambio real (66.8% reportado -> solo 24.5% era
#: un cambio genuino con ambos modos alcanzables).
BOTH_SAME = "both_reachable_same_facility"
BOTH_DIFFERENT = "both_reachable_different_facility"
CAR_ONLY = "car_only_reachable"
FOOT_ONLY = "foot_only_reachable"
BOTH_UNREACHABLE = "both_unreachable"


def car_vs_foot(nearest_df: pd.DataFrame) -> dict:
    """`nearest_df` debe traer una fila por (demand_id, mode) para TODOS los
    demand points del universo (alcanzables o no, `reachable` indica cuál)."""
    car = nearest_df[nearest_df["mode"] == "car"].set_index("demand_id")
    foot = nearest_df[nearest_df["mode"] == "foot"].set_index("demand_id")
    common = car.index.intersection(foot.index)
    car_c, foot_c = car.loc[common], foot.loc[common]

    if len(common) == 0:
        empty = pd.DataFrame(columns=["demand_id", "category", "facility_id_car", "facility_id_foot", "car_time_min", "foot_time_min", "foot_over_car_ratio"])
        return {"n_total": 0, "counts": {}, "pct_different_nearest_of_both_reachable": None, "ratio_summary": {}, "extreme_cases": empty, "table": empty}

    car_reach = car_c["reachable"].astype(bool).values
    foot_reach = foot_c["reachable"].astype(bool).values
    car_time = _numeric(car_c["travel_time_min"]).values
    foot_time = _numeric(foot_c["travel_time_min"]).values
    car_fac = car_c["facility_id"].values
    foot_fac = foot_c["facility_id"].values

    both_reach = car_reach & foot_reach
    same_fac = both_reach & (car_fac == foot_fac)
    diff_fac = both_reach & (car_fac != foot_fac)
    car_only = car_reach & ~foot_reach
    foot_only = ~car_reach & foot_reach
    both_un = ~car_reach & ~foot_reach

    category = np.select(
        [same_fac, diff_fac, car_only, foot_only, both_un],
        [BOTH_SAME, BOTH_DIFFERENT, CAR_ONLY, FOOT_ONLY, BOTH_UNREACHABLE],
        default="unclassified",
    )
    ratio = np.where(both_reach, foot_time / np.where(car_time == 0, np.nan, car_time), np.nan)

    merged = pd.DataFrame({
        "demand_id": common, "category": category,
        "facility_id_car": car_fac, "facility_id_foot": foot_fac,
        "car_time_min": car_time, "foot_time_min": foot_time,
        "foot_over_car_ratio": ratio,
    })
    counts = merged["category"].value_counts().to_dict()
    n_both_reachable = int(same_fac.sum() + diff_fac.sum())
    pct_diff = 100.0 * diff_fac.sum() / n_both_reachable if n_both_reachable else None

    extremes = merged[merged["category"] == BOTH_DIFFERENT].reindex(
        merged["foot_over_car_ratio"].sort_values(ascending=False, na_position="last").index
    ).dropna(subset=["foot_over_car_ratio"]).head(20)

    return {
        "n_total": len(common),
        "counts": counts,
        "n_both_reachable": n_both_reachable,
        "pct_different_nearest_of_both_reachable": pct_diff,
        "ratio_summary": pd.Series(ratio[both_reach]).describe().to_dict(),
        "extreme_cases": extremes,
        "table": merged,
    }


#: Categorías de la Parte A (corrección 2026-09-11): cuántos de los 3 modos
#: tienen un nearest válido para ese demand point — independiente de si el
#: nearest es la MISMA facility o no (eso es una pregunta aparte, ver abajo).
ALL_THREE = "all_three_reachable"
EXACTLY_TWO = "exactly_two_reachable"
EXACTLY_ONE = "exactly_one_reachable"
NONE_REACHABLE = "none_reachable"


def three_mode_comparison(nearest_df: pd.DataFrame, all_demand_ids: list[str]) -> pd.DataFrame:
    """Una fila por demand_id con facility/tiempo/reachable por modo.

    Corrección de auditoría (2026-09-11): además de `reachable_<mode>`, añade
    (a) una categoría explícita de CUÁNTOS modos son alcanzables
    (`all_three_reachable`/`exactly_two_reachable`/`exactly_one_reachable`/
    `none_reachable`), y (b) comparaciones de identidad de facility
    (`car_bike_same_facility`, etc.) que son `pd.NA` — no `False` — cuando
    alguno de los dos modos comparados no tiene nearest válido. Antes no
    existía esta comparación de identidad; se agrega ya con la semántica
    correcta desde el principio (nunca se llama "distinta facility" a un caso
    donde un modo es unreachable)."""
    wide = nearest_df.pivot_table(index="demand_id", columns="mode", values=["facility_id", "travel_time_min"], aggfunc="first")
    out = pd.DataFrame(index=pd.Index(all_demand_ids, name="demand_id"))
    for mode in ("car", "bike", "foot"):
        if ("travel_time_min", mode) in wide.columns:
            out[f"time_{mode}_min"] = _numeric(wide[("travel_time_min", mode)])
            out[f"facility_{mode}"] = wide[("facility_id", mode)]
        else:
            out[f"time_{mode}_min"] = np.nan
            out[f"facility_{mode}"] = None
        out[f"reachable_{mode}"] = out[f"time_{mode}_min"].notna()

    out["bike_over_car_ratio"] = out["time_bike_min"] / out["time_car_min"].replace(0, np.nan)
    out["foot_over_car_ratio"] = out["time_foot_min"] / out["time_car_min"].replace(0, np.nan)
    out["foot_over_bike_ratio"] = out["time_foot_min"] / out["time_bike_min"].replace(0, np.nan)

    n_reachable = out[["reachable_car", "reachable_bike", "reachable_foot"]].sum(axis=1)
    out["n_modes_reachable"] = n_reachable
    out["reachability_category"] = np.select(
        [n_reachable == 3, n_reachable == 2, n_reachable == 1, n_reachable == 0],
        [ALL_THREE, EXACTLY_TWO, EXACTLY_ONE, NONE_REACHABLE],
        default=NONE_REACHABLE,
    )

    for a, b in (("car", "bike"), ("car", "foot"), ("bike", "foot")):
        both = out[f"reachable_{a}"] & out[f"reachable_{b}"]
        same = pd.Series(pd.NA, index=out.index, dtype="boolean")
        same.loc[both] = (out.loc[both, f"facility_{a}"] == out.loc[both, f"facility_{b}"])
        out[f"{a}_{b}_same_facility"] = same  # pd.NA (no False) si algún modo no tiene nearest

    return out.reset_index()


def straight_line_vs_network(
    nearest_df: pd.DataFrame,
    demand_coords: dict[str, tuple[float, float]],
    facility_coords: dict[str, tuple[float, float]],
    mode: str,
) -> pd.DataFrame:
    sub = nearest_df[nearest_df["mode"] == mode].copy()
    sub = sub[sub["facility_id"].notna()]
    d_lon = sub["demand_id"].map(lambda i: demand_coords.get(i, (np.nan, np.nan))[0])
    d_lat = sub["demand_id"].map(lambda i: demand_coords.get(i, (np.nan, np.nan))[1])
    f_lon = sub["facility_id"].map(lambda i: facility_coords.get(i, (np.nan, np.nan))[0])
    f_lat = sub["facility_id"].map(lambda i: facility_coords.get(i, (np.nan, np.nan))[1])
    sub["straight_line_m"] = haversine_m(d_lon.values, d_lat.values, f_lon.values, f_lat.values)
    sub["distance_m"] = _numeric(sub["distance_m"])
    sub["network_over_straight_ratio"] = sub["distance_m"] / sub["straight_line_m"].replace(0, np.nan)
    return sub[["demand_id", "facility_id", "mode", "distance_m", "straight_line_m", "network_over_straight_ratio"]]
