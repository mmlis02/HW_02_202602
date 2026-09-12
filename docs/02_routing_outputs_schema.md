# 02 — Esquema de outputs de Fase 2 (routing)

Todos en `data/outputs/`, generados por `scripts/run_routing.py`. Ninguno
sustituye Fase 3 (sin cobertura 30/60/120, sin Gini, sin población).

**Actualizado 2026-09-11 (corrección de auditoría)**: todos los outputs con
pares/demand points ahora llevan `routing_status` explícito (ver
`src/routing/status.py`) — `reachable` (booleano) se conserva por
compatibilidad pero **no** distingue por sí solo las 4 situaciones reales:

| `routing_status` | Significa | `reachable` |
|---|---|---|
| `routed` | Se encontró una ruta real en el grafo | `True` |
| `snap_failed` | El punto nunca se pudo ubicar en la red (a >`snap_max_distance_m` del nodo más cercano) | `False` |
| `no_route_same_department` | Se ubicó en la red, pero dentro de su propio departamento no hay camino hasta ninguna facility de destino (incluye tanto "nodo sin aristas transitables para el perfil" como "componente conectado pero sin la facility") | `False` |
| `cross_department_not_evaluated` | El demand point y la facility están en departamentos distintos — la arquitectura de grafos separados por departamento (ver `docs/01_routing_decision.md`) nunca evaluó si habría ruta. **No es "sin ruta"**, es "no evaluado". La auditoría del 2026-09-11 demostró (cota geodésica) que esto no puede cambiar el nearest resolutive de ningún demand point actualmente ruteado | `False` |

`cross_department_not_evaluated` solo aparece a nivel **matriz** (un par
concreto demand×facility); a nivel **demand point** (`nearest_resolutive_by_mode.parquet`,
`demand_routing_status.parquet`) el estado es siempre uno de los otros 3,
porque "nearest" nunca necesita evaluar cross-departamento (ver demostración
en la auditoría).

## `routing_matrix_resolutive.parquet`
Matriz COMPLETA demand × facility resolutiva × {car,bike,foot} — **TODAS las
filas, incluidos los 326 demand points con snap fallido** (antes ausentes por
completo del archivo). `demand_id, facility_id, mode, distance_m,
travel_time_min, reachable, routing_status, origin_node, dest_node`.
`distance_m`/`travel_time_min` son `null` salvo `routing_status="routed"`
(nunca se imputa Haversine). Filas: 40 facilities × 5000 demand × 3 modos =
600 000.

## `routing_matrix_upgrade_candidates_car.parquet`
Igual esquema (con `routing_status`), pero **solo car** y solo
establecimientos I-3/I-4 **activos** con coordenadas usables y no excluidos
por Fase 1. Añade `current_resolutive` (siempre `False`) y
`upgrade_candidate` (siempre `True`). 372 facilities × 5000 demand =
1 860 000 filas.

## `nearest_resolutive_by_mode.parquet`
Una fila por (demand_id, mode) — **universo completo de 5000**, incluidos los
snap-failed (`facility_id=None`, `routing_status="snap_failed"`). La facility
resolutiva más cercana en ESE modo (mínimo `travel_time_min` entre las
`routed`). Calculado con un Dijkstra multi-fuente propio (sin materializar
rutas completas, ver `docs/01`) por modo.

## `nearest_any_facility_foot.parquet`
`demand_id, facility_id, mode="foot", distance_m, travel_time_min,
reachable`. Nearest facility de **cualquier categoría** (I-1..I-4, II-*,
III-*) con coordenadas usables, a pie, universo completo de 5000. Para
Fase 3: filtrar por el subconjunto urbano una vez definido ese criterio.

## `demand_routing_status.parquet` (NUEVO — corrección de auditoría)
**Una fila por demand point (5000, universo completo, igual que
`demand.parquet`)** — el output consolidado que Fase 3 debe usar para saber
qué pasó con cada punto sin tener que cruzar contra la matriz completa:
`demand_id, dep, snap_status, snap_distance_m, routing_status_{car,bike,foot},
nearest_facility_{car,bike,foot}, travel_time_min_{car,bike,foot},
distance_m_{car,bike,foot}`. Los 326 con `snap_status="failure"` están
presentes con `routing_status_*="snap_failed"` y valores `null` — **no
desaparecen**. Se une a `demand.parquet` por `demand_id`/`CODCP` (string) para
recuperar `stratum_n`/`design_weight`/`CPINEI`/población futura.

## `snap_report.csv` / `snap_report.parquet` (corrección de auditoría)
Detalle por punto: `point_id, node_id, snap_distance_m, status, fail_reason,
point_type` (`demand` | `resolutive_facility` | `upgrade_candidate_facility` |
`any_facility_foot`). **El `.csv` por sí solo, releído con pandas por
defecto, pierde los ceros a la izquierda de `point_id`** (se infiere
`int64`) — se mantiene por ser inspeccionable a simple vista, pero **el
`.parquet` es el formato canónico para cualquier cruce posterior** (preserva
`point_id` como string). Ningún punto con snap fallido se descarta
silenciosamente.

## `comparison_car_vs_foot.parquet`
Corrección de auditoría: antes contaba "reachability mixta" (un modo sin
nearest) como "cambio de facility", inflando el resultado (66.8% reportado
vs. 24.5% real en los datos de esa corrida). Ahora cada demand_id cae en una
de 5 categorías **mutuamente excluyentes**
(`src/routing/compare.py::BOTH_SAME/BOTH_DIFFERENT/CAR_ONLY/FOOT_ONLY/BOTH_UNREACHABLE`),
y el % de "cambia de facility" usa como denominador **solo** los casos con
ambos modos `routed` (`both_reachable_same_facility` +
`both_reachable_different_facility`).

## `comparison_car_bike_foot.parquet`, `comparison_straight_vs_network_car.parquet`
Sin cambios de esquema. **Nota metodológica sobre straight-line vs network**
(auditoría 2026-09-11): la distancia recta usa la coordenada ORIGINAL del
punto; la distancia de red usa su NODO SNAPEADO — son dos sistemas de
referencia ligeramente distintos (difieren por la distancia de snap). Para
viajes muy cortos esto puede producir `network/straight < 1` (imposible en
teoría, la recta siempre es ≤ la ruta real) — verificado que ocurre en ~0.1%
de los pares y con magnitud acotada por la suma de las distancias de snap
involucradas. No se fuerza el ratio a ≥1 ni se descartan esos casos.

## `routing_quality_report.csv`
`metric,value`. Incluye, por modo: `{mode}_snap_failed`,
`{mode}_snap_success`, `{mode}_routed`, `{mode}_no_route_same_department`;
para car además `car_matrix_cross_department_not_evaluated_cells`
(+ `_pct`), `profile_hash_{car,bike,foot}`, `car_track_fallback_speed_kmh`, y
el diagnóstico de track: `car_track_previously_isolated`,
`car_track_recovers_edges`, `car_track_recovers_route_to_resolutive`,
`car_track_still_isolated` (comparación contra el grafo car cacheado de la
corrida anterior, sin track).

## `data/cache/`
- `osm_network/{DEPT}_{nodes,edges}.parquet`: red cruda extraída por
  departamento (evita re-tocar el PBF).
- `osm_network/combined_{nodes,edges}.parquet`: red de los 3 departamentos
  combinada y deduplicada.
- `graphs/graph_{mode}_{profile_hash}.pkl`: grafo NetworkX por perfil,
  **versionado por `profile_hash`** (`src/routing/profiles.py::profile_hash`)
  — un cambio de velocidades/reglas produce un nombre de archivo distinto,
  invalidando el cache anterior automáticamente (corrección de auditoría: el
  esquema previo sin versión obligaba a borrar la carpeta a mano).
- `routing_matrix_resolutive/{mode}/{cache_version}__{profile_hash}/{facility_id}.parquet`,
  `routing_matrix_upgrade/car/{cache_version}__{profile_hash}/{facility_id}.parquet`:
  chunks de cache por facility — una segunda corrida los reutiliza sin
  recalcular Dijkstra, siempre que el `profile_hash` y el universo de demand
  points coincidan.
