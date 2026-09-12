# 05 — Auditoría de representatividad poblacional y calibración final (Fase 3, 2026-09-11)

## Universos

| Universo | N | Descripción |
|---|---|---|
| U1 | — (población) | Población oficial departamental Censo 2017 (benchmark MIMP/INEI) |
| U2 | 12,332 CP | Universo CENEPRED/MINAM (Tumbes+Amazonas+Cusco), población = 1,809,774 |
| U3 | 19,370 CP | Universo SIGMED (3 departamentos, pre-muestreo) |
| U4 | 12,220 CP censales únicos | Intersección SIGMED×CENEPRED, población = **1,800,859** |
| U5 | 5,000 CP | Muestra SIGMED |
| U6 | 3,139 CP | Muestra con población matched |
| U7 | 2,416 CP | Muestra con población matched + car routed |

## Los 2 `CPINEI` duplicados de SIGMED — explicación completa

| census_cp_id | CODCP | Nombre SIGMED | Nombre CENEPRED | Población CENEPRED | En U5 | Routing | Distancia entre puntos SIGMED |
|---|---|---|---|---|---|---|---|
| 0808040208 | 529339 | Llactacunca | LLACTACUNCA | 0 | No | — | 1426 m |
| 0808040208 | 670431 | Llactacunca Huillcana | LLACTACUNCA | 0 | **Sí** | routed | 1426 m |
| 0809060005 | 651194 | Yavero | PENETRACION YAVERO | 69 | No | — | 236 m |
| 0809060005 | 614684 | Penetracion | PENETRACION YAVERO | 69 | No | — | 236 m |

**La diferencia de 69 personas** reportada entre "población CENEPRED capturada por SIGMED" (1,800,859) y un cálculo ingenuo sumando población por CADA FILA SIGMED (1,800,928) es **exactamente** el CP `0809060005` (69 habitantes) contado dos veces — una por "Yavero", otra por "Penetracion". Confirmado matemáticamente: `1,800,928 − 1,800,859 = 69`.

**Resolución (caso por caso, nunca 50/50)**: se consultó CENEPRED con geometría para ambos códigos y se midió la distancia real a cada candidato SIGMED:
- `0808040208`: CODCP 529339 "Llactacunca" (nombre EXACTO, 2796 m de CENEPRED) elegido sobre 670431 "Llactacunca Huillcana" (4177 m). Población=0 → esta elección no afecta ninguna métrica ponderada.
- `0809060005`: CODCP 614684 "Penetracion" (277 m de CENEPRED) elegido sobre 651194 "Yavero" (505 m).

Ninguno de los dos pares tiene **ambos** miembros en la muestra de 5000 — esta corrección no cambia ningún resultado de Fase 3 ya publicado, solo corrige el conteo de población del universo U4. Implementado en `src/analysis.py::POPULATION_REPRESENTATIVE_OVERRIDE` + `src/metrics.py::flag_population_representative`/`DUPLICATE_KEY_EXCLUDED`.

## Población CENEPRED == Censo 2017 exacto

Sumando `pob_total` de los 12,332 registros CENEPRED por departamento y por provincia (21 provincias) contra el benchmark MIMP/INEI: **diferencia = 0 en las tres departamentos y en las 21 provincias comparables** (las 2 "sin match" son solo diferencias de tilde en el nombre). CENEPRED **es** la población censal 2017 completa, no una fracción.

## Cuánta población CENEPRED captura SIGMED

Del 1,809,774 (U2), SIGMED captura **1,800,859 (99.51%)** — solo 112 CP de CENEPRED (8,915 personas, 0.49%) no tienen ningún CP SIGMED correspondiente. Por departamento: Tumbes 100.00%, Cusco 99.81%, Amazonas 98.24%. La aparente tasa de match baja por CONTEO de CP (63.1%) es mucho menos preocupante en términos de POBLACIÓN.

## Caracterización de los 7,148 SIGMED sin match (universo de 19,370)

- **A. `CPINEI` ausente: 7,062 (98.8%)** — 91% (6,438/7,062) tiene `CON_IE="0"` (sin institución educativa activa): son localidades de referencia del sistema educativo sin escuela y sin código INEI asignado, no errores de cruce. Explica por qué SIGMED (19,370) tiene más puntos que CENEPRED (12,332): enumera localidades más finas que el catálogo censal oficial.
- **B. `CPINEI` presente pero no existe en CENEPRED: 86 (1.2%)** — pequeño, concentrado en Cusco (72)/Amazonas (14), 0 en Tumbes.
- **C. `CPINEI2` rescataría: 0** — ninguna fila unmatched-por-CPINEI tiene un CPINEI2 que sí matchee.
- No se asignó población a ninguno de los 7,148.

## Calibración de pesos por distrito

**Target de calibración = U4 (frame SIGMED-Censo), NUNCA U1/U2 completo** — la diferencia U2−U4 (112 CP, 8,915 personas, 0.49%) se reporta como `outside_SIGMED_frame`, nunca redistribuida.

Para cada distrito h: `HT_total_h = Σ(population_i × design_weight_i)` sobre la muestra matched; `known_population_h = Σ(population)` sobre los CP censales únicos de U4 en ese distrito; `calibration_factor_h = known_population_h / HT_total_h`; `calibrated_weight_i = ht_population_weight_i × calibration_factor_h`.

**Resultado**: 207/209 distritos calibrables (`Σ calibrated_weight` reproduce `known_population_h` con diferencia ≤1e-11, verificado también a nivel provincia/departamento/total — 1,742,312 en ambos lados). **2 distritos `impossible_no_sample`** (0 CP de la muestra con población válida, pese a tener población censal conocida): Wanchaq (Cusco, 58,541 hab.) y Luya Viejo (Amazonas, 6 hab.) — 58,547 personas (3.25% de U4) sin peso calibrado, documentado como limitación explícita, **nunca inventado**.

`calibration_factor`: min 0.25, P5 0.33, mediana 1.28, P95 22.9, max 177.6 — dispersión alta y esperable (estratos finos ~24 CP/estrato en promedio, población muy sesgada entre CP grandes/pequeños). 31/207 distritos <0.5, 62/207 >2.0 — diagnóstico, no regla de exclusión, ningún distrito se elimina.

Ver `docs/04_phase3_notes.md` para el hallazgo original (Wanchaq/Luya Viejo aparecían con "0% cobertura" en la versión sin calibrar) — la calibración por distrito formaliza exactamente esa distinción como `calibration_impossible`.
